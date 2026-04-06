"""DAT manager - downloads No-Intro DATs and verifies ROMs against them."""

import os
import re
import json
import zipfile
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Optional, Callable

DAT_DIR = Path.home() / "Library" / "Application Support" / "ROMeo" / "dats"

# No-Intro provides a DAT-o-MATIC download pack.
# We link to the public daily update zip.
NOINTRO_DAT_URL = "https://datomatic.no-intro.org/dat-pack/?content=daily"

# Fallback: use the Libretro-database which bundles No-Intro DATs in a GitHub repo
# This is openly redistributed, frequently updated, and no login required.
LIBRETRO_DB_BASE = "https://raw.githubusercontent.com/libretro/libretro-database/master/dat"

LIBRETRO_DATS = {
    # Nintendo
    "NES":          "Nintendo - Nintendo Entertainment System.dat",
    "SNES":         "Nintendo - Super Nintendo Entertainment System.dat",
    "GameCube":     "Nintendo - GameCube.dat",
    "Wii":          "Nintendo - Wii.dat",
    "WiiU":         "Nintendo - Wii U.dat",
    # Sega
    "Saturn":       "Sega - Saturn.dat",
    # SNK
    "NeoGeo":       "SNK - Neo Geo.dat",
    # NEC
    "PC98":         "NEC - PC-98.dat",
    # Sony
    "PS3":          "Sony - PlayStation 3.dat",
    "PSMinis":      "Sony - PlayStation Minis.dat",
    # Commodore
    "Amiga":        "Commodore - Amiga.dat",
    "CD32":         "Commodore - CD32.dat",
    # Sinclair
    "ZXSpectrum":   "Sinclair - ZX Spectrum.dat",
    "ZX81":         "Sinclair - ZX 81.dat",
    # Amstrad
    "AmstradCPC":   "Amstrad - CPC.dat",
    # DOS / ScummVM
    "DOS":          "DOS.dat",
    "ScummVM":      "ScummVM.dat",
    # Arcade / MAME variants
    "Atomiswave":   "Atomiswave.dat",
    "HBMAME":       "HBMAME.dat",
    # Indie / fantasy consoles
    "PICO-8":       "PICO-8.dat",
    "TIC80":        "TIC-80.dat",
    "LowResNX":     "LowRes NX.dat",
    "Arduboy":      "Arduboy Inc - Arduboy.dat",
    "CHIP8":        "CHIP-8.dat",
    "Uzebox":       "Uzebox.dat",
    "Vircon32":     "Vircon32.dat",
    "WASM4":        "WASM-4.dat",
    "MicroW8":      "MicroW8.dat",
    # Game engines / ports
    "DOOM":         "DOOM.dat",
    "Quake":        "Quake.dat",
    "QuakeII":      "Quake II.dat",
    "QuakeIII":     "Quake III.dat",
    "Wolfenstein3D":"Wolfenstein 3D.dat",
    "TombRaider":   "Tomb Raider.dat",
    "Flashback":    "Flashback.dat",
    "CaveStory":    "Cave Story.dat",
    "RPGMaker":     "RPG Maker.dat",
    "ChaiLove":     "ChaiLove.dat",
    "Lutro":        "Lutro.dat",
    "PuzzleScript": "PuzzleScript.dat",
    "ZMachine":     "Infocom - Z-Machine.dat",
}

# In-memory cache: crc32 -> {name, size, md5}
_dat_cache: Dict[str, Dict[str, dict]] = {}  # console -> {crc32: info}


def dat_path(console: str) -> Path:
    return DAT_DIR / f"{console}.dat"


def is_downloaded(console: str) -> bool:
    return dat_path(console).exists()


def download_dat(console: str, progress_cb: Optional[Callable] = None) -> bool:
    """Download a single DAT from libretro-database."""
    filename = LIBRETRO_DATS.get(console)
    if not filename:
        return False

    url = f"{LIBRETRO_DB_BASE}/{requests.utils.quote(filename)}"
    DAT_DIR.mkdir(parents=True, exist_ok=True)
    dest = dat_path(console)

    try:
        if progress_cb:
            progress_cb(f"Downloading {console} DAT...")
        r = requests.get(url, timeout=30, stream=True)
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
                downloaded += len(chunk)
                if progress_cb and total:
                    pct = int(downloaded / total * 100)
                    progress_cb(f"Downloading {console} DAT... {pct}%")
        return True
    except Exception as e:
        print(f"Failed to download {console} DAT: {e}")
        if dest.exists():
            dest.unlink()
        return False


def download_all_dats(progress_cb: Optional[Callable] = None) -> dict:
    """Download all available DATs. Returns {console: success}."""
    results = {}
    for console in LIBRETRO_DATS:
        if is_downloaded(console):
            results[console] = True
            continue
        results[console] = download_dat(console, progress_cb)
    return results


def parse_dat(console: str) -> Dict[str, dict]:
    """
    Parse a No-Intro/Logiqx XML DAT file.
    Returns dict: crc32 -> {name, size, md5, sha1}
    """
    path = dat_path(console)
    if not path.exists():
        return {}

    db = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        # Detect format: ClrMamePro (.dat text) or Logiqx XML
        if text.lstrip().startswith("<"):
            db = _parse_xml_dat(text, console)
        else:
            db = _parse_clrmame_dat(text, console)
    except Exception as e:
        print(f"Failed to parse {console} DAT: {e}")

    return db


def _parse_clrmame_dat(text: str, console: str) -> dict:
    """Parse ClrMamePro format DAT files (used by libretro-database)."""
    db = {}
    in_game = False
    game_name = None

    for line in text.splitlines():
        s = line.strip()

        if s.startswith("game (") or s == "game (":
            in_game = True
            game_name = None

        elif in_game and game_name is None and s.startswith('name "'):
            m = re.match(r'name\s+"([^"]+)"', s)
            if m:
                game_name = m.group(1)

        elif in_game and game_name and s.startswith("rom ("):
            crc_m  = re.search(r'\bcrc\s+([0-9a-fA-F]+)\b', s, re.IGNORECASE)
            md5_m  = re.search(r'\bmd5\s+([0-9a-fA-F]{32})\b', s, re.IGNORECASE)
            sha1_m = re.search(r'\bsha1\s+([0-9a-fA-F]{40})\b', s, re.IGNORECASE)
            size_m = re.search(r'\bsize\s+(\d+)\b', s)
            if crc_m:
                crc = crc_m.group(1).lower().zfill(8)
                db[crc] = {
                    "name": game_name,
                    "size": int(size_m.group(1)) if size_m else 0,
                    "md5":  md5_m.group(1).lower() if md5_m else "",
                    "sha1": sha1_m.group(1).lower() if sha1_m else "",
                }

        elif s == ")":
            in_game = False
            game_name = None

    return db


def _parse_xml_dat(text: str, console: str) -> dict:
    """Parse Logiqx XML format DAT files, using cloneofid for grouping."""
    db = {}
    try:
        root = ET.fromstring(text)
        games = (root.findall("game") or root.findall(".//game") or
                 root.findall("machine") or root.findall(".//machine"))

        # First pass: build id -> parent_id map
        # A game with no cloneofid is its own parent (use its own id).
        id_to_parent: dict = {}
        for game in games:
            gid       = game.get("id", "")
            cloneofid = game.get("cloneofid", "")
            if gid:
                id_to_parent[gid] = cloneofid if cloneofid else gid

        # Second pass: build CRC32 lookup with parent-based group key
        for game in games:
            name      = game.get("name", "")
            gid       = game.get("id", "")
            parent_id = id_to_parent.get(gid, gid)
            for rom in game.findall("rom"):
                crc      = (rom.get("crc") or "").lower().zfill(8)
                rom_name = (rom.get("name") or "")
                if crc and crc != "00000000":
                    db[crc] = {
                        "name":      name,
                        "rom_name":  rom_name,    # filename inside the game (e.g. "Game (Track 02).bin")
                        "size":      int(rom.get("size") or 0),
                        "md5":       (rom.get("md5") or "").lower(),
                        "sha1":      (rom.get("sha1") or "").lower(),
                        "parent_id": parent_id,   # DAT-defined group
                    }
    except ET.ParseError as e:
        print(f"XML parse error for {console}: {e}")
    return db


def get_dat(console: str) -> Dict[str, dict]:
    """Get (and cache) the DAT database for a console."""
    if console not in _dat_cache:
        _dat_cache[console] = parse_dat(console)
    return _dat_cache[console]


def verify_rom(crc32: str, console: str) -> Optional[dict]:
    """
    Check if a ROM's CRC32 matches a known-good entry.
    Returns the DAT entry if matched, None if not found.
    """
    if not crc32:
        return None
    db = get_dat(console)
    return db.get(crc32.lower())


def dat_status() -> dict:
    """Return status for all consoles — both auto-downloadable and manually imported."""
    result = {}
    # All .dat files present on disk (includes manually imported ones)
    if DAT_DIR.exists():
        for dat_file in sorted(DAT_DIR.glob("*.dat")):
            console = dat_file.stem
            result[console] = {
                "available":    True,
                "entries":      len(get_dat(console)),
                "downloadable": console in LIBRETRO_DATS,
            }
    # Also list downloadable consoles that haven't been downloaded yet
    for console in LIBRETRO_DATS:
        if console not in result:
            result[console] = {
                "available":    False,
                "entries":      0,
                "downloadable": True,
            }
    return result


def invalidate_cache(console: str = None):
    """Clear in-memory cache so updated DATs are re-parsed."""
    global _dat_cache
    if console:
        _dat_cache.pop(console, None)
    else:
        _dat_cache = {}


# Matches Track 02, 03, …, 10, 11, … — but NOT Track 01 or Track 1.
# Pattern: optional leading zeros, then a digit ≥ 2 (single) or any multi-digit ≥ 10.
_TRACK_SKIP_RE = re.compile(r'\(Track\s+0*([2-9]|[1-9]\d+)\)', re.IGNORECASE)


def dat_to_game_entries(console: str, dat: dict) -> list:
    """
    Convert a parsed DAT {crc32: info} to game catalog entries.

    For multi-track Redump DATs, each <game> element has multiple <rom>
    entries (one .cue + one per track).  We only add ONE catalog entry per
    game to keep the library clean:
      - Skip .cue ROM entries (they're indices, not game data)
      - Skip Track 02, Track 03, … entries
      - Keep Track 01 (or the only BIN for single-track games)
    All track CRC32s are still stored in the raw DAT cache so scan
    matching can find any track.
    """
    from .scanner import detect_region, detect_bad_tags, detect_revision, normalize_title, strip_release_number
    entries = []

    for crc32, info in dat.items():
        raw_name = info.get("name", "")
        if not raw_name:
            continue

        rom_name = info.get("rom_name", "")

        # Skip CUE sheet entries — they're disc indices, not game data
        if rom_name.lower().endswith(".cue"):
            continue

        # Skip non-primary tracks (Track 02, 03, …)
        # Track 01 and single-BIN games pass through unchanged
        if _TRACK_SKIP_RE.search(rom_name):
            continue

        name = strip_release_number(raw_name)

        # Use DAT-provided parent_id as group key when available (XML DATs with cloneofid).
        # Fall back to normalized title for ClrMamePro DATs that lack clone info.
        parent_id = info.get("parent_id", "")
        if parent_id:
            group_key = f"{console}::id:{parent_id}"
        else:
            group_key = f"{console}::{normalize_title(name)}"

        entries.append({
            "crc32":     crc32,
            "console":   console,
            "name":      name,
            "region":    detect_region(name),
            "size":      info.get("size", 0),
            "md5":       info.get("md5", ""),
            "bad_tags":  detect_bad_tags(name),
            "revision":  detect_revision(name),
            "group_key": group_key,
        })
    return entries


def load_all_dats() -> dict:
    """
    Build a flat lookup from all DAT files on disk.
    Keys are either CRC32 hex strings or 'sha1:<hex>' for SHA1-indexed entries.
    SHA1-keyed entries include 'real_crc32' so collection matching still uses the DAT CRC32.
    """
    lookup = {}
    if not DAT_DIR.exists():
        return lookup
    for dat_file in DAT_DIR.glob("*.dat"):
        console = dat_file.stem
        dat = get_dat(console)
        for crc32, info in dat.items():
            entry = {**info, "console": console}
            if crc32 not in lookup:
                lookup[crc32] = entry
            # Also index by SHA1 for CHD matching
            sha1 = info.get("sha1", "")
            if sha1:
                sha1_key = f"sha1:{sha1}"
                if sha1_key not in lookup:
                    lookup[sha1_key] = {**entry, "real_crc32": crc32}
    return lookup
