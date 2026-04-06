"""SQLite persistence - DAT-first Pokedex model.

Games table = the master catalog (populated from DAT files).
Collection table = ROMs you own (populated by scanning).
No names are ever derived from filenames.
"""

import re
import sqlite3
from pathlib import Path
from typing import List, Dict

# ── Title normalisation (inline to avoid circular imports) ────────────────────

_RELEASE_NUM_RE = re.compile(r'^\d{3,}\s*-\s+')
_TAGS_RE        = re.compile(r'\([^)]*\)|\[[^\]]*\]')
_NONALNUM_RE    = re.compile(r'[^a-z0-9 ]')
_SPACE_RE       = re.compile(r'\s+')

_NUM_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12",
}
_NUM_WORD_RE = re.compile(r'\b(' + '|'.join(_NUM_WORDS) + r')\b')


def _normalize_num_words(s: str) -> str:
    return _NUM_WORD_RE.sub(lambda m: _NUM_WORDS[m.group(1)], s)


def _export_group_key(console: str, name: str) -> str:
    """Stable group key used at export time — strips release numbers + tags."""
    n = _RELEASE_NUM_RE.sub("", name)
    n = _TAGS_RE.sub("", n)
    n = _SPACE_RE.sub(" ", n).strip().rstrip(".")
    n = n.lower()
    n = re.sub(r"^the\s+", "", n)
    n = _NONALNUM_RE.sub("", n).strip()
    n = _normalize_num_words(n)          # "vol one" → "vol 1"
    n = _SPACE_RE.sub(" ", n).strip()
    return f"{console}::{n}"

APPDATA = Path.home() / "Library" / "Application Support" / "ROMeo"
DB_PATH = APPDATA / "library.db"

SCHEMA = """
DROP TABLE IF EXISTS roms;

CREATE TABLE IF NOT EXISTS games (
    crc32       TEXT PRIMARY KEY,
    console     TEXT NOT NULL,
    name        TEXT NOT NULL,
    region      TEXT DEFAULT '',
    size        INTEGER DEFAULT 0,
    md5         TEXT DEFAULT '',
    bad_tags    TEXT DEFAULT '',
    revision    INTEGER DEFAULT 0,
    group_key   TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS collection (
    crc32       TEXT PRIMARY KEY,
    rom_path    TEXT,
    scanned_at  TEXT
);

CREATE TABLE IF NOT EXISTS scans (
    id          TEXT PRIMARY KEY,
    root_path   TEXT,
    started_at  TEXT,
    finished_at TEXT,
    total_files INTEGER DEFAULT 0,
    matched     INTEGER DEFAULT 0,
    status      TEXT
);

CREATE TABLE IF NOT EXISTS hash_cache (
    path        TEXT PRIMARY KEY,
    size        INTEGER NOT NULL,
    mtime       REAL NOT NULL,
    crc32       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pbp_links (
    pbp_path     TEXT PRIMARY KEY,
    game_crc32   TEXT NOT NULL,
    sfo_title    TEXT DEFAULT '',
    sfo_id       TEXT DEFAULT '',
    confirmed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_games_console ON games(console);
CREATE INDEX IF NOT EXISTS idx_games_group   ON games(group_key);
CREATE INDEX IF NOT EXISTS idx_pbp_crc       ON pbp_links(game_crc32);
"""


_db_initialized = False


def init_db():
    """Create tables once. Safe to call multiple times (idempotent)."""
    global _db_initialized
    if _db_initialized:
        return
    APPDATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.executescript(SCHEMA)
    try:
        conn.execute("ALTER TABLE scans ADD COLUMN matched INTEGER DEFAULT 0")
        conn.commit()
    except Exception:
        pass
    conn.close()
    _db_initialized = True


def get_conn() -> sqlite3.Connection:
    init_db()
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def upsert_games(entries: List[dict]) -> int:
    """Populate catalog from a parsed DAT. Returns count inserted."""
    if not entries:
        return 0
    conn = get_conn()
    conn.executemany("""
        INSERT OR REPLACE INTO games
        (crc32, console, name, region, size, md5, bad_tags, revision, group_key)
        VALUES (:crc32, :console, :name, :region, :size, :md5, :bad_tags, :revision, :group_key)
    """, entries)
    conn.commit()
    conn.close()
    return len(entries)


def bulk_add_collection(matches: List[dict]):
    """matches: list of {crc32, rom_path, scanned_at}"""
    if not matches:
        return
    conn = get_conn()
    conn.executemany("""
        INSERT OR REPLACE INTO collection (crc32, rom_path, scanned_at)
        VALUES (:crc32, :rom_path, :scanned_at)
    """, matches)
    conn.commit()
    conn.close()


def get_catalog_groups(console: str = None, show: str = "all", search: str = "", letter: str = "") -> List[dict]:
    """
    Return games grouped by group_key, with collection status.
    show: 'all' | 'collected' | 'missing'
    """
    conn = get_conn()
    query = """
        SELECT g.crc32, g.console, g.name, g.region, g.size,
               g.bad_tags, g.revision, g.group_key,
               CASE WHEN c.crc32 IS NOT NULL THEN 1 ELSE 0 END AS collected,
               c.rom_path
        FROM games g
        LEFT JOIN collection c ON g.crc32 = c.crc32
        WHERE 1=1
    """
    params = []
    if console:
        query += " AND g.console = ?"
        params.append(console)
    if search:
        query += " AND LOWER(g.name) LIKE ?"
        params.append(f"%{search.lower()}%")
    query += " ORDER BY g.group_key, g.name"
    rows = conn.execute(query, params).fetchall()
    conn.close()

    groups: Dict[str, dict] = {}
    for row in rows:
        r = dict(row)
        key = r["group_key"]
        if key not in groups:
            groups[key] = {
                "key":             key,
                "title":           "",   # resolved below from best variant name
                "console":         r["console"],
                "variants":        [],
                "collected_count": 0,
            }
        groups[key]["variants"].append(r)
        if r["collected"]:
            groups[key]["collected_count"] += 1

    # Resolve display title from the best variant (prefer USA/World, no bad tags)
    _RS = {"USA": 0, "World": 1, "Europe": 2, "Australia": 3,
           "UK": 4, "Japan": 5, "Unknown": 50}
    for group in groups.values():
        best = min(group["variants"],
                   key=lambda v: (bool(v["bad_tags"]), _RS.get(v["region"], 50)))
        # Strip region/revision tags from name for a clean display title
        clean = re.sub(r"\([^)]*\)|\[[^\]]*\]", "", best["name"]).strip().rstrip(".")
        clean = re.sub(r"\s+", " ", clean).strip()
        group["title"] = clean or best["name"]

    result = []
    for group in groups.values():
        total = len(group["variants"])
        have = group["collected_count"]
        group["total_count"] = total
        group["has_collected"] = have > 0
        group["has_missing"] = have < total

        if show == "collected" and not group["has_collected"]:
            continue
        if show == "missing" and not group["has_missing"]:
            continue

        # Letter filter
        if letter:
            first = group["title"][0:1].upper() if group["title"] else ""
            if letter == "#":
                if first.isalpha():
                    continue
            elif first != letter.upper():
                continue

        result.append(group)

    return result


def get_catalog_stats() -> dict:
    conn = get_conn()
    total     = conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    collected = conn.execute(
        "SELECT COUNT(*) FROM collection WHERE crc32 IN (SELECT crc32 FROM games)"
    ).fetchone()[0]
    consoles  = conn.execute("""
        SELECT g.console,
               COUNT(g.crc32) AS total,
               COUNT(c.crc32) AS have
        FROM games g
        LEFT JOIN collection c ON g.crc32 = c.crc32
        GROUP BY g.console
        ORDER BY total DESC
    """).fetchall()
    conn.close()
    return {
        "total": total,
        "collected": collected,
        "missing": total - collected,
        "consoles": {
            r["console"]: {"total": r["total"], "have": r["have"]}
            for r in consoles
        },
    }


_REGION_SCORE = {
    "USA": 0, "World": 1, "Europe": 2, "Australia": 3,
    "UK": 4, "Japan": 5, "Spain": 6, "France": 7,
    "Germany": 8, "Italy": 9, "Korea": 10, "China": 11,
    "Brazil": 12, "Unknown": 50,
}


def get_collection_for_export(one_per_game: bool = False,
                               skip_bad_tags: bool = False,
                               consoles: list = None) -> List[dict]:
    """Return collected ROMs ready for export, with optional filtering."""
    conn = get_conn()
    q = """
        SELECT g.console, g.name, g.region, g.bad_tags, g.revision,
               g.size, g.group_key, c.rom_path AS path
        FROM collection c
        JOIN games g ON c.crc32 = g.crc32
        WHERE c.rom_path IS NOT NULL
    """
    params = []
    if consoles:
        q += f" AND g.console IN ({','.join('?'*len(consoles))})"
        params.extend(consoles)
    rows = conn.execute(q, params).fetchall()
    conn.close()

    roms = [dict(r) for r in rows]

    if skip_bad_tags:
        roms = [r for r in roms if not r["bad_tags"]]

    if one_per_game:
        def _sort_key(r):
            return (
                bool(r["bad_tags"]),
                _REGION_SCORE.get(r["region"], 50),
                -(r["revision"] or 0),
            )
        groups: Dict[str, list] = {}
        for rom in roms:
            # Use stored group_key (DAT parent_id for XML DATs, normalised title
            # for ClrMamePro DATs). Fall back to inline normalisation only if blank.
            key = rom.get("group_key") or _export_group_key(rom["console"], rom["name"])
            groups.setdefault(key, []).append(rom)
        roms = [min(g, key=_sort_key) for g in groups.values()]

    return roms


def clear_catalog(console: str = None):
    conn = get_conn()
    if console:
        conn.execute(
            "DELETE FROM collection WHERE crc32 IN (SELECT crc32 FROM games WHERE console=?)",
            (console,)
        )
        conn.execute("DELETE FROM games WHERE console = ?", (console,))
    else:
        conn.execute("DELETE FROM collection")
        conn.execute("DELETE FROM games")
        conn.execute("DELETE FROM scans")
    conn.commit()
    conn.close()


def save_scan(scan_id: str, root_path: str, started_at: str, finished_at: str,
              total_files: int, matched: int, status: str):
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO scans
        (id, root_path, started_at, finished_at, total_files, matched, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (scan_id, root_path, started_at, finished_at, total_files, matched, status))
    conn.commit()
    conn.close()


def cache_get(path: str, size: int, mtime: float) -> str:
    """Return cached CRC32 if path/size/mtime match, else ''."""
    conn = get_conn()
    row = conn.execute(
        "SELECT crc32 FROM hash_cache WHERE path=? AND size=? AND mtime=?",
        (path, size, mtime)
    ).fetchone()
    conn.close()
    return row["crc32"] if row else ""


def cache_set(path: str, size: int, mtime: float, crc32: str):
    """Store a computed CRC32 in the cache."""
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO hash_cache (path, size, mtime, crc32) VALUES (?,?,?,?)",
        (path, size, mtime, crc32)
    )
    conn.commit()
    conn.close()


def add_pbp_links(links: List[dict]):
    """
    Confirm PBP→game associations.
    Each link: {pbp_path, game_crc32, sfo_title, sfo_id, confirmed_at}
    Also inserts into collection with INSERT OR IGNORE so CRC-matched entries
    are never overwritten.
    """
    if not links:
        return
    conn = get_conn()
    conn.executemany("""
        INSERT OR REPLACE INTO pbp_links
        (pbp_path, game_crc32, sfo_title, sfo_id, confirmed_at)
        VALUES (:pbp_path, :game_crc32, :sfo_title, :sfo_id, :confirmed_at)
    """, links)
    # Add to collection only if not already present (keeps CRC match intact)
    conn.executemany("""
        INSERT OR IGNORE INTO collection (crc32, rom_path, scanned_at)
        VALUES (:game_crc32, :pbp_path, :confirmed_at)
    """, links)
    conn.commit()
    conn.close()


def get_pbp_links_map() -> Dict[str, str]:
    """Return {pbp_path: game_crc32} for all confirmed links."""
    conn = get_conn()
    rows = conn.execute("SELECT pbp_path, game_crc32 FROM pbp_links").fetchall()
    conn.close()
    return {r["pbp_path"]: r["game_crc32"] for r in rows}


def get_recent_scans(limit: int = 10) -> List[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM scans ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
