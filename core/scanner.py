"""ROM Scanner - walks directories, identifies ROMs, extracts metadata."""

import os
import re
import zlib
import hashlib
import zipfile
import struct
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

# ── Console definitions ───────────────────────────────────────────────────────

CONSOLE_EXTENSIONS = {
    "NES":        [".nes"],
    "SNES":       [".sfc", ".smc"],
    "GB":         [".gb"],
    "GBC":        [".gbc"],
    "GBA":        [".gba"],
    "N64":        [".z64", ".n64", ".v64"],
    "NDS":        [".nds"],
    "GameCube":   [".gcm", ".gcz"],
    "Wii":        [".wbfs", ".wad"],
    "PS1":        [".bin", ".cue", ".pbp", ".chd", ".ecm"],
    "PS2":        [".iso", ".chd"],
    "PSP":        [".cso", ".iso"],
    "Dreamcast":  [".gdi", ".cdi", ".chd"],
    "Saturn":     [".cue", ".chd"],
    "Genesis":    [".md", ".gen"],
    "MasterSys":  [".sms"],
    "GameGear":   [".gg"],
    "PICO-8":     [".p8"],
    "Lynx":       [".lnx"],
    "WonderSwan": [".ws", ".wsc"],
    "PCE":        [".pce"],
    "FDS":        [".fds"],
    "Vectrex":    [".vec"],
    "Atari2600":  [".a26"],
    "Atari7800":  [".a78"],
    "Atari Lynx": [".lnx"],
    "NeoGeo":     [".neo"],
}

FOLDER_CONSOLE_HINTS = {
    "nes": "NES", "famicom": "NES",
    "snes": "SNES", "sfc": "SNES", "super famicom": "SNES", "super nintendo": "SNES",
    "gb": "GB", "game boy": "GB", "gameboy": "GB",
    "gbc": "GBC", "game boy color": "GBC",
    "gba": "GBA", "game boy advance": "GBA",
    "n64": "N64", "nintendo 64": "N64", "nds": "NDS", "ds": "NDS",
    "gamecube": "GameCube", "gc": "GameCube", "wii": "Wii",
    "ps1": "PS1", "psx": "PS1", "playstation": "PS1", "ps2": "PS2",
    "psp": "PSP", "dreamcast": "Dreamcast", "dc": "Dreamcast",
    "saturn": "Saturn", "genesis": "Genesis", "megadrive": "Genesis",
    "game gear": "GameGear", "gamegear": "GameGear",
    "master system": "MasterSys", "sms": "MasterSys",
    "mame": "MAME", "arcade": "MAME",
}

# ── Region detection ──────────────────────────────────────────────────────────

REGION_PRIORITY = [
    "USA", "World", "Europe", "Australia",
    "UK", "Japan", "Spain", "France", "Germany",
    "Italy", "Korea", "China", "Brazil", "Unknown",
]

REGION_PATTERNS = [
    ("USA",       r"\((?:USA|U|US)\)"),
    ("World",     r"\((?:World|W)\)"),
    ("Europe",    r"\((?:Europe|E|EU)\)"),
    ("Australia", r"\(Aus(?:tralia)?\)"),
    ("UK",        r"\((?:UK|United Kingdom)\)"),
    ("Japan",     r"\((?:Japan|J|JPN)\)"),
    ("Spain",     r"\((?:Spain|S|Esp)\)"),
    ("France",    r"\((?:France|F|Fra)\)"),
    ("Germany",   r"\((?:Germany|G|Ger|De)\)"),
    ("Italy",     r"\((?:Italy|I|Ita)\)"),
    ("Korea",     r"\((?:Korea|K)\)"),
    ("China",     r"\((?:China|C|Ch)\)"),
    ("Brazil",    r"\((?:Brazil|B|Bra|Br)\)"),
]

BAD_TAG_LABELS = [
    (r"\(Proto(?:type)?\)",    "Prototype"),
    (r"\(Beta[^)]*\)",         "Beta"),
    (r"\(Demo[^)]*\)",         "Demo"),
    (r"\(Sample\)",            "Sample"),
    (r"\(Test[^)]*\)",         "Test"),
    (r"\(Hack[^)]*\)",         "Hack"),
    (r"\(Unl(?:icensed)?\)",   "Unlicensed"),
    (r"\(Pirate[^)]*\)",       "Pirate"),
    (r"\[BIOS\]",              "BIOS"),
    (r"\(BIOS[^)]*\)",         "BIOS"),
    (r"\(Program\)",           "Program"),
    (r"\(Debug\)",             "Debug"),
    (r"\(Not for Resale\)",    "Not for Resale"),
    (r"\(Kiosk[^)]*\)",        "Kiosk"),
    (r"\(Promo[^)]*\)",        "Promo"),
]


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class RomFile:
    path: str
    name: str          # filename without extension
    ext: str
    console: str
    region: str
    size: int          # bytes
    md5: str = ""
    crc32: str = ""
    bad_tags: str = ""
    revision: int = 0
    region_score: int = 0
    verified: bool = False   # matched against DAT
    duplicate_of: Optional[str] = None
    keep: bool = True
    group_key: str = ""

    def to_dict(self):
        return asdict(self)


# ── Detection helpers ─────────────────────────────────────────────────────────

def detect_console(path: Path) -> str:
    ext = path.suffix.lower()
    # Unambiguous extension
    for console, exts in CONSOLE_EXTENSIONS.items():
        if ext in exts:
            return console
    # Folder name hint
    for part in path.parts:
        lower = part.lower()
        for hint, console in FOLDER_CONSOLE_HINTS.items():
            if hint in lower:
                return console
    # .zip/.7z could be MAME
    if ext in (".zip", ".7z"):
        return "MAME"
    # .iso is ambiguous - check folder
    if ext == ".iso":
        for part in path.parts:
            lower = part.lower()
            if "ps2" in lower:
                return "PS2"
            if "ps1" in lower or "psx" in lower:
                return "PS1"
            if "wii" in lower:
                return "Wii"
            if "gamecube" in lower or "gc" in lower:
                return "GameCube"
        return "Unknown"
    return "Unknown"


def detect_region(name: str) -> str:
    for region, pattern in REGION_PATTERNS:
        if re.search(pattern, name, re.IGNORECASE):
            return region
    return "Unknown"


def region_score(region: str) -> int:
    try:
        return REGION_PRIORITY.index(region)
    except ValueError:
        return len(REGION_PRIORITY)




def detect_bad_tags(name: str) -> str:
    """Return the human-readable bad tag label, or '' if none."""
    for pattern, label in BAD_TAG_LABELS:
        if re.search(pattern, name, re.IGNORECASE):
            return label
    return ""


def detect_revision(name: str) -> int:
    m = re.search(r"\(Rev\s*([A-Z0-9]+)\)", name, re.IGNORECASE)
    if m:
        val = m.group(1)
        try:
            return int(val)
        except ValueError:
            return ord(val[0].upper()) - ord('A') + 1
    m = re.search(r"\(v(\d+)[._]?(\d*)\)", name, re.IGNORECASE)
    if m:
        major = int(m.group(1))
        minor = int(m.group(2)) if m.group(2) else 0
        return major * 100 + minor
    return 0


_RELEASE_NUM = re.compile(r'^\d{3,}\s*-\s+')


def strip_release_number(name: str) -> str:
    """Remove leading DAT release numbers like '0001 - ' or '004 - '."""
    return _RELEASE_NUM.sub("", name).strip()


_NUM_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12",
}
_NUM_WORD_RE = re.compile(r'\b(' + '|'.join(_NUM_WORDS) + r')\b')


def normalize_title(name: str) -> str:
    """Strip region/revision/publisher tags to get a grouping key."""
    n = strip_release_number(name)
    n = re.sub(r"\([^)]*\)", "", n)   # strip (USA), (Rev 1), (Enix)(8Mb), etc.
    n = re.sub(r"\[[^\]]*\]", "", n)  # strip [!], [T-En], etc.
    n = re.sub(r"\s+", " ", n).strip().rstrip(".")
    n = n.lower()
    n = re.sub(r"^the\s+", "", n)
    n = re.sub(r"[^a-z0-9 ]", "", n)
    n = _NUM_WORD_RE.sub(lambda m: _NUM_WORDS[m.group(1)], n)  # "vol one" → "vol 1"
    return re.sub(r"\s+", " ", n).strip()


def _find_chdman() -> str:
    """Return path to chdman binary, or '' if not found."""
    import shutil
    return shutil.which("chdman") or ""


def _crc32_file_slice(path: Path, offset: int, length: int, chunk: int = 1 << 16) -> str:
    """Compute CRC32 of a byte slice of a file."""
    crc = 0
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            remaining = length
            while remaining > 0:
                data = f.read(min(chunk, remaining))
                if not data:
                    break
                crc = zlib.crc32(data, crc)
                remaining -= len(data)
        return format(crc & 0xFFFFFFFF, "08x")
    except OSError:
        return ""


def _parse_cue_tracks(cue_path: Path) -> list:
    """
    Parse a CUE sheet and return list of dicts per track with:
      'start'   — INDEX 01 LBA (actual track data start)
      'pregap'  — INDEX 00 LBA (pregap start, or None if no pregap)

    Redump per-track BIN boundaries:
      Track N ends where Track N+1's pregap begins (INDEX 00 of N+1).
      If Track N+1 has no INDEX 00, it ends at INDEX 01 of N+1.
    """
    tracks = []
    current_track = None
    try:
        for line in cue_path.read_text(errors="replace").splitlines():
            line = line.strip()
            m = re.match(r"TRACK\s+(\d+)\s+(\S+)", line, re.IGNORECASE)
            if m:
                if current_track is not None:
                    tracks.append(current_track)
                current_track = {"num": int(m.group(1)), "type": m.group(2),
                                 "start": None, "pregap": None}
                continue
            if current_track is not None:
                m0 = re.match(r"INDEX\s+00\s+(\d+):(\d+):(\d+)", line, re.IGNORECASE)
                if m0:
                    mm, ss, ff = int(m0.group(1)), int(m0.group(2)), int(m0.group(3))
                    current_track["pregap"] = (mm * 60 + ss) * 75 + ff
                    continue
                m1 = re.match(r"INDEX\s+01\s+(\d+):(\d+):(\d+)", line, re.IGNORECASE)
                if m1:
                    mm, ss, ff = int(m1.group(1)), int(m1.group(2)), int(m1.group(3))
                    current_track["start"] = (mm * 60 + ss) * 75 + ff
        if current_track is not None:
            tracks.append(current_track)
    except OSError:
        pass
    return tracks


def _crc32_per_track(bin_path: Path, cue_path: Path, sector_size: int = 2352) -> list:
    """
    Given a merged BIN and its CUE sheet, return a list of CRC32 strings,
    one per track. Track boundaries follow Redump's convention:
      - Track N ends at the INDEX 00 (pregap start) of Track N+1.
      - If Track N+1 has no pregap, it ends at Track N+1's INDEX 01.
    """
    tracks = _parse_cue_tracks(cue_path)
    if not tracks:
        return []

    file_size = bin_path.stat().st_size
    crcs = []
    for i, track in enumerate(tracks):
        # Redump convention:
        #   Track 01: starts at INDEX 01 (no pregap on first track).
        #   Track N>1: starts at INDEX 00 (its own pregap is the first bytes of its BIN).
        if i == 0:
            start_lba = track.get("start")
        else:
            start_lba = track.get("pregap") or track.get("start")
        if start_lba is None:
            continue
        start_byte = start_lba * sector_size

        if i + 1 < len(tracks):
            next_t = tracks[i + 1]
            # End at next track's pregap start (or INDEX 01 if no pregap)
            boundary_lba = next_t.get("pregap") or next_t.get("start")
            end_byte = boundary_lba * sector_size if boundary_lba is not None else file_size
        else:
            end_byte = file_size

        length = end_byte - start_byte
        if length <= 0:
            continue
        crc = _crc32_file_slice(bin_path, start_byte, length)
        if crc:
            crcs.append(crc)
    return crcs


def _crc32_from_chd_extract(path: Path) -> list:
    """
    Extract a CHD to a temp dir using chdman, compute per-track CRC32s,
    cache the result (pipe-separated), and clean up.
    Returns list of CRC32 strings (one per track), or [] on failure.
    """
    import tempfile
    import subprocess
    from core.db import cache_get, cache_set

    chdman = _find_chdman()
    if not chdman:
        return []

    try:
        stat = path.stat()
        size, mtime = stat.st_size, stat.st_mtime
    except OSError:
        return []

    # Check cache — stored as pipe-separated CRC32 list
    cached = cache_get(str(path), size, mtime)
    if cached:
        return cached.split("|")

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            cue_out = Path(tmpdir) / "disc.cue"
            result = subprocess.run(
                [chdman, "extractcd", "-i", str(path), "-o", str(cue_out)],
                capture_output=True, timeout=300
            )
            if result.returncode != 0:
                return []

            bins = sorted(Path(tmpdir).glob("*.bin"))
            if not bins:
                return []

            if len(bins) > 1:
                # chdman produced separate track files — CRC32 each directly
                crcs = [compute_crc32_raw(b) for b in bins]
                crcs = [c for c in crcs if c]
            else:
                # Single merged BIN — split by CUE track offsets
                crcs = _crc32_per_track(bins[0], cue_out)
                if not crcs:
                    # Fallback: whole-file CRC32
                    c = compute_crc32_raw(bins[0])
                    crcs = [c] if c else []

            if crcs:
                cache_set(str(path), size, mtime, "|".join(crcs))
            return crcs
    except Exception:
        return []


def _sha1_from_chd(path: Path) -> str:
    """Read SHA1 from a CHD v5 header (offset 64, 20 bytes). Returns hex string or ''."""
    try:
        with open(path, "rb") as f:
            magic = f.read(8)
            if magic != b"MComprHD":
                return ""
            f.read(4)  # header length (unused)
            version = int.from_bytes(f.read(4), "big")
            if version == 5:
                f.seek(64)
                sha1_bytes = f.read(20)
                if len(sha1_bytes) == 20:
                    return sha1_bytes.hex()
        return ""
    except OSError:
        return ""


def _crc32_from_7z(path: Path) -> str:
    """Extract stored CRC32 from 7z archive metadata without decompressing."""
    try:
        import py7zr
        with py7zr.SevenZipFile(path, mode="r") as z:
            for info in z.list():
                if info.crc32 is not None:
                    return format(info.crc32 & 0xFFFFFFFF, "08x")
        return ""
    except Exception:
        return ""


def _crc32_from_cso(path: Path, chunk: int = 1 << 16) -> str:
    """Decompress a CSO (Compressed ISO) to compute CRC32 of the original data."""
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
            if magic != b"CISO":
                return ""
            header_size = struct.unpack_from("<I", f.read(4))[0]
            total_bytes  = struct.unpack_from("<Q", f.read(8))[0]
            block_size   = struct.unpack_from("<I", f.read(4))[0]
            ver          = struct.unpack_from("<B", f.read(1))[0]
            f.read(1)    # align
            f.read(2)    # reserved

            if block_size == 0:
                return ""

            num_blocks = (total_bytes + block_size - 1) // block_size
            # Read block index (num_blocks + 1 entries, each 4 bytes)
            index_raw = f.read((num_blocks + 1) * 4)
            index = struct.unpack_from(f"<{num_blocks + 1}I", index_raw)

            crc = 0
            for i in range(num_blocks):
                raw_offset = index[i]
                is_compressed = not bool(raw_offset & 0x80000000)
                offset = raw_offset & 0x7FFFFFFF
                next_offset = index[i + 1] & 0x7FFFFFFF

                f.seek(offset)
                data = f.read(next_offset - offset)

                if is_compressed:
                    data = zlib.decompress(data, -15)  # raw deflate
                crc = zlib.crc32(data, crc)

        return format(crc & 0xFFFFFFFF, "08x")
    except Exception:
        return ""


def _crc32_from_ecm(path: Path, chunk: int = 1 << 16) -> str:
    """Decompress ECM-encoded BIN to compute CRC32 of the original data."""
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
            if magic != b"ECM\x00":
                return ""
            crc = 0
            while True:
                b = f.read(1)
                if not b:
                    break
                t = b[0] & 3
                n_raw = b[0] >> 2
                # read variable-length count
                shift = 0
                while b[0] & 0x80:
                    b = f.read(1)
                    if not b:
                        break
                    n_raw |= (b[0] & 0x7F) << (shift + 5)
                    shift += 7
                n = n_raw + 1

                if t == 0:
                    # raw bytes
                    remaining = n
                    while remaining:
                        blk = f.read(min(remaining, chunk))
                        if not blk:
                            break
                        crc = zlib.crc32(blk, crc)
                        remaining -= len(blk)
                elif t in (1, 2, 3):
                    # sync + header + edc + ecc sectors; just skip
                    # Sector sizes: Mode1=2352, Mode2=2336, Mode2-Form2=2336
                    sector_sizes = {1: 2352, 2: 2336, 3: 2336}
                    skip = sector_sizes[t] * n
                    f.seek(skip, 1)
                else:
                    break
        return format(crc & 0xFFFFFFFF, "08x")
    except Exception:
        return ""


def compute_md5(path: Path, chunk: int = 1 << 16) -> str:
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            while True:
                data = f.read(chunk)
                if not data:
                    break
                h.update(data)
        return h.hexdigest()
    except OSError:
        return ""


def compute_crc32_raw(path: Path, chunk: int = 1 << 16) -> str:
    """CRC32 of a plain file — no special format handling."""
    crc = 0
    try:
        with open(path, "rb") as f:
            while True:
                data = f.read(chunk)
                if not data:
                    break
                crc = zlib.crc32(data, crc)
        return format(crc & 0xFFFFFFFF, "08x")
    except OSError:
        return ""


def compute_crc32_candidates(path: Path) -> list:
    """
    Return all CRC32 candidates to try when matching a ROM against a DAT.
    For most formats this is a single-element list; for multi-track CHDs it
    returns one CRC32 per track so any track can trigger a Redump match.
    """
    ext = path.suffix.lower()
    if ext == ".chd":
        crcs = _crc32_from_chd_extract(path)
        if crcs:
            return crcs
        sha1 = _sha1_from_chd(path)
        return [f"sha1:{sha1}"] if sha1 else []
    crc = compute_crc32(path)
    return [crc] if crc else []


def compute_crc32(path: Path, chunk: int = 1 << 16) -> str:
    """
    Compute a lookup key for a ROM file.
    - ZIP:  CRC32 of the first compressed entry (uncompressed data matches DAT)
    - CHD:  first per-track CRC32 from chdman extraction (use compute_crc32_candidates
            for full multi-track matching against Redump DATs)
    - 7z:   CRC32 from archive metadata (no decompression needed)
    - CSO:  CRC32 of decompressed ISO data
    - ECM:  CRC32 of decoded sector data
    - else: raw CRC32 of file
    """
    ext = path.suffix.lower()
    crc = 0
    try:
        if ext == ".chd":
            # Return first track CRC32; use compute_crc32_candidates for full matching
            crcs = _crc32_from_chd_extract(path)
            if crcs:
                return crcs[0]
            sha1 = _sha1_from_chd(path)
            return f"sha1:{sha1}" if sha1 else ""

        if ext == ".7z":
            return _crc32_from_7z(path)

        if ext == ".cso":
            return _crc32_from_cso(path)

        if ext == ".ecm":
            return _crc32_from_ecm(path)

        # For zip files, hash the first ROM inside (No-Intro DATs use uncompressed CRC32)
        if ext == ".zip":
            with zipfile.ZipFile(path, "r") as zf:
                entries = [e for e in zf.infolist() if not e.filename.endswith("/")]
                if entries:
                    with zf.open(entries[0]) as rom:
                        while True:
                            data = rom.read(chunk)
                            if not data:
                                break
                            crc = zlib.crc32(data, crc)
                    return format(crc & 0xFFFFFFFF, "08x")
            return ""

        with open(path, "rb") as f:
            while True:
                data = f.read(chunk)
                if not data:
                    break
                crc = zlib.crc32(data, crc)
        return format(crc & 0xFFFFFFFF, "08x")
    except (OSError, zipfile.BadZipFile, zlib.error):
        return ""


# ── Main scanner ──────────────────────────────────────────────────────────────

KNOWN_EXTENSIONS = set()
for exts in CONSOLE_EXTENSIONS.values():
    KNOWN_EXTENSIONS.update(exts)
KNOWN_EXTENSIONS.update([".zip", ".7z", ".iso", ".rom", ".bin", ".chd", ".cso", ".ecm", ".pbp", ".cue", ".gdi", ".cdi"])

SKIP_DIRS = {"__MACOSX", ".Spotlight-V100", ".fseventsd", ".Trashes", "System Volume Information"}


def scan_for_crcs(root: str, progress_cb=None) -> list:
    """
    Walk root, compute CRC32 for every ROM file.
    Returns list of {path, crc32, crcs, size} dicts.
    'crcs' is a list of all candidate CRC32s (>1 for multi-track CHDs).
    Names are NOT derived from filenames — DAT matching happens in the caller.
    """
    root_path = Path(root)
    all_paths = []

    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.suffix.lower() in KNOWN_EXTENSIONS:
                all_paths.append(p)

    total = len(all_paths)
    results = []

    for i, p in enumerate(all_paths):
        if progress_cb:
            progress_cb(i + 1, total, str(p))
        size = p.stat().st_size if p.exists() else 0
        if size < 2 * 1024 * 1024 * 1024:
            crcs = compute_crc32_candidates(p)
        else:
            crcs = []
        primary = crcs[0] if crcs else ""
        results.append({"path": str(p), "crc32": primary, "crcs": crcs, "size": size})

    return results


def scan_directory(root: str, progress_cb=None, hash_files: bool = True):
    """
    Walk root, yield RomFile objects.
    progress_cb(current, total, current_path) called periodically.
    """
    root_path = Path(root)
    all_paths = []

    for dirpath, dirnames, filenames in os.walk(root_path):
        # Skip system dirs
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.suffix.lower() in KNOWN_EXTENSIONS:
                all_paths.append(p)

    total = len(all_paths)
    results = []

    for i, p in enumerate(all_paths):
        if progress_cb:
            progress_cb(i + 1, total, str(p))

        name = p.stem  # raw filename; canonical name set later from DAT if matched
        ext = p.suffix.lower()
        console = detect_console(p)
        region = detect_region(name)
        rscore = region_score(region)
        bad = detect_bad_tags(name)
        rev = detect_revision(name)
        size = p.stat().st_size if p.exists() else 0

        md5 = ""
        crc = ""
        if hash_files and size < 2 * 1024 * 1024 * 1024:  # skip >2GB for now
            crc = compute_crc32(p)
            md5 = compute_md5(p)

        group_key = f"{console}::{normalize_title(name)}"

        rom = RomFile(
            path=str(p),
            name=name,
            ext=ext,
            console=console,
            region=region,
            size=size,
            md5=md5,
            crc32=crc,
            bad_tags=bad,
            revision=rev,
            region_score=rscore,
            group_key=group_key,
        )
        results.append(rom)

    return results
