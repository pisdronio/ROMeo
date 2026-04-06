"""PBP identification — reads PARAM.SFO metadata and matches against catalog."""

import re
import struct
from pathlib import Path
from typing import Optional


# ── SFO reader ────────────────────────────────────────────────────────────────

def read_pbp_sfo(path: Path) -> Optional[dict]:
    """
    Read PARAM.SFO embedded in a PBP file.
    Returns dict of SFO key→value pairs, or None if not a valid PBP.
    """
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
            if magic != b"\x00PBP":
                return None
            f.seek(8)
            sfo_off  = struct.unpack("<I", f.read(4))[0]
            icon_off = struct.unpack("<I", f.read(4))[0]
            sfo_size = icon_off - sfo_off
            if sfo_size <= 0 or sfo_size > 0x10000:
                return None
            f.seek(sfo_off)
            sfo = f.read(sfo_size)

        if sfo[:4] != b"\x00PSF":
            return None

        key_table_off  = struct.unpack_from("<I", sfo, 8)[0]
        data_table_off = struct.unpack_from("<I", sfo, 12)[0]
        num_entries    = struct.unpack_from("<I", sfo, 16)[0]

        result = {}
        for i in range(num_entries):
            base    = 20 + i * 16
            key_off = struct.unpack_from("<H", sfo, base)[0]
            fmt     = struct.unpack_from("<H", sfo, base + 2)[0]
            dlen    = struct.unpack_from("<I", sfo, base + 4)[0]
            doff    = struct.unpack_from("<I", sfo, base + 12)[0]

            key = sfo[key_table_off + key_off:].split(b"\x00")[0].decode("utf-8", "replace")
            raw = sfo[data_table_off + doff: data_table_off + doff + dlen]

            if fmt == 0x0204:
                result[key] = raw.rstrip(b"\x00").decode("utf-8", "replace")
            elif fmt == 0x0404:
                result[key] = struct.unpack_from("<I", raw)[0] if len(raw) >= 4 else 0

        return result
    except Exception:
        return None


# ── Title normalisation ───────────────────────────────────────────────────────

_TAG_RE    = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_NONALNUM  = re.compile(r"[^a-z0-9 ]")
_SPACES    = re.compile(r"\s+")

# Common title articles to strip for comparison
_ARTICLES = re.compile(r"^(the|a|an)\s+", re.IGNORECASE)

def _norm(s: str) -> str:
    s = _TAG_RE.sub(" ", s)       # strip (USA), [T-En], etc.
    s = _NONALNUM.sub(" ", s.lower())
    s = _ARTICLES.sub("", s)
    return _SPACES.sub(" ", s).strip()


def _fuzzy_score(sfo_title: str, game_name: str) -> float:
    """Score 0–1 how well an SFO title matches a catalog game name."""
    a = _norm(sfo_title)
    b = _norm(game_name)

    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # One is a prefix of the other
    if b.startswith(a) or a.startswith(b):
        return 0.92
    # One contains the other
    if a in b or b in a:
        return 0.85

    words_a = set(a.split())
    words_b = set(b.split())
    overlap  = len(words_a & words_b)
    union    = len(words_a | words_b)
    return overlap / union if union else 0.0


# ── Candidate search ──────────────────────────────────────────────────────────

def find_game_candidates(sfo_title: str, sfo_id: str = "",
                         limit: int = 5) -> list:
    """
    Return the top `limit` games from the catalog that best match the SFO title.
    Each result: {crc32, name, console, region, score}
    """
    from .db import get_conn

    if not sfo_title:
        return []

    # Pull key words (>2 chars) from the normalised title for the SQL filter
    words = [w for w in _norm(sfo_title).split() if len(w) > 2]
    if not words:
        return []

    conn = get_conn()

    # Use the two most distinctive words to narrow the result set cheaply
    anchor_words = sorted(words, key=len, reverse=True)[:2]
    conditions = " AND ".join("LOWER(g.name) LIKE ?" for _ in anchor_words)
    params     = [f"%{w}%" for w in anchor_words]

    rows = conn.execute(
        f"""SELECT g.crc32, g.name, g.console, g.region
            FROM games g
            WHERE {conditions}
            LIMIT 60""",
        params,
    ).fetchall()
    conn.close()

    scored = sorted(
        [{"crc32":   r["crc32"],
          "name":    r["name"],
          "console": r["console"],
          "region":  r["region"],
          "score":   _fuzzy_score(sfo_title, r["name"])}
         for r in rows],
        key=lambda x: -x["score"],
    )
    return scored[:limit]


# ── Batch identify ────────────────────────────────────────────────────────────

def identify_pbp(path: Path) -> Optional[dict]:
    """
    Read SFO from a PBP and return:
      {path, filename, sfo_title, sfo_id, candidates}
    Returns None if not a valid PBP.
    """
    sfo = read_pbp_sfo(path)
    if not sfo:
        return None

    title = sfo.get("TITLE", "")
    disc_id = sfo.get("DISC_ID", "")

    return {
        "path":      str(path),
        "filename":  path.name,
        "sfo_title": title,
        "sfo_id":    disc_id,
        "candidates": find_game_candidates(title, disc_id),
    }
