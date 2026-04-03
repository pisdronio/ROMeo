"""ROM Scanner - walks directories, identifies ROMs, extracts metadata."""

import os
import re
import hashlib
import zipfile
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
    "PS1":        [".bin", ".cue", ".pbp"],
    "PS2":        [".iso"],
    "PSP":        [".cso"],
    "Dreamcast":  [".gdi", ".cdi", ".chd"],
    "Saturn":     [".cue"],
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


def compute_crc32(path: Path, chunk: int = 1 << 16) -> str:
    import zlib
    crc = 0
    try:
        # For zip files, hash the first ROM inside (No-Intro DATs use uncompressed CRC32)
        if path.suffix.lower() == ".zip":
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
        with open(path, "rb") as f:
            while True:
                data = f.read(chunk)
                if not data:
                    break
                crc = zlib.crc32(data, crc)
        return format(crc & 0xFFFFFFFF, "08x")
    except (OSError, zipfile.BadZipFile):
        return ""


# ── Main scanner ──────────────────────────────────────────────────────────────

KNOWN_EXTENSIONS = set()
for exts in CONSOLE_EXTENSIONS.values():
    KNOWN_EXTENSIONS.update(exts)
KNOWN_EXTENSIONS.update([".zip", ".7z", ".iso", ".rom", ".bin"])

SKIP_DIRS = {"__MACOSX", ".Spotlight-V100", ".fseventsd", ".Trashes", "System Volume Information"}


def scan_for_crcs(root: str, progress_cb=None) -> list:
    """
    Walk root, compute CRC32 for every ROM file.
    Returns list of {path, crc32, size} dicts.
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
        crc = compute_crc32(p) if size < 2 * 1024 * 1024 * 1024 else ""
        results.append({"path": str(p), "crc32": crc, "size": size})

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
