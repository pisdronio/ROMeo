"""Safe file operations for ROM curation."""

import os
import shutil
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional


APPDATA = Path.home() / "Library" / "Application Support" / "ROMeo"
TRASH_DIR = APPDATA / "Trash"
LOG_DIR   = APPDATA / "logs"


def ensure_dirs():
    APPDATA.mkdir(parents=True, exist_ok=True)
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def safe_trash(path: str) -> dict:
    ensure_dirs()
    src = Path(path)
    if not src.exists():
        return {"ok": False, "error": "File not found"}
    dest = TRASH_DIR / src.name
    counter = 1
    while dest.exists():
        dest = TRASH_DIR / f"{src.stem}__{counter}{src.suffix}"
        counter += 1
    try:
        shutil.move(str(src), str(dest))
        return {"ok": True, "dest": str(dest)}
    except OSError as e:
        return {"ok": False, "error": str(e)}


def restore_from_trash(trash_path: str, original_path: str) -> dict:
    src = Path(trash_path)
    dest = Path(original_path)
    if not src.exists():
        return {"ok": False, "error": "File not in trash"}
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(src), str(dest))
        return {"ok": True}
    except OSError as e:
        return {"ok": False, "error": str(e)}


def empty_trash() -> dict:
    ensure_dirs()
    count = 0
    errors = []
    for item in TRASH_DIR.iterdir():
        try:
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
            count += 1
        except OSError as e:
            errors.append(str(e))
    return {"ok": not errors, "deleted": count, "errors": errors}


def trash_contents() -> List[dict]:
    ensure_dirs()
    return [
        {"path": str(p), "name": p.name, "size": p.stat().st_size}
        for p in TRASH_DIR.iterdir() if p.is_file()
    ]


# ── Console folder maps per device ────────────────────────────────────────────

_MAPS = {
    "miyoo": {
        "NES": "FC", "SNES": "SFC", "GB": "GB", "GBC": "GBC", "GBA": "GBA",
        "N64": "N64", "NDS": "NDS", "PS1": "PS", "PSP": "PSP",
        "GameGear": "GG", "MasterSys": "SMS", "Genesis": "MD",
        "PCE": "PCE", "NeoGeo": "NEOGEO", "Lynx": "LYNX",
        "WonderSwan": "WS", "Atari2600": "ATARI", "FDS": "FDS",
        "PICO-8": "PICO8",
    },
    "miyoo_plus": {
        "NES": "FC", "SNES": "SFC", "GB": "GB", "GBC": "GBC", "GBA": "GBA",
        "N64": "N64", "NDS": "NDS", "PS1": "PS", "PSP": "PSP",
        "GameGear": "GG", "MasterSys": "SMS", "Genesis": "MD",
        "PCE": "PCE", "NeoGeo": "NEOGEO", "Lynx": "LYNX", "FDS": "FDS",
        "PICO-8": "PICO8",
    },
    "anbernic": {
        "NES": "FC", "SNES": "SFC", "GB": "GB", "GBC": "GBC", "GBA": "GBA",
        "N64": "N64", "NDS": "NDS", "PS1": "PS", "PS2": "PS2", "PSP": "PSP",
        "GameGear": "GG", "MasterSys": "SMS", "Genesis": "MD",
        "Dreamcast": "DC", "Saturn": "SATURN", "PCE": "PCE",
        "NeoGeo": "NEOGEO", "Lynx": "LYNX", "WonderSwan": "WS",
        "Atari2600": "ATARI2600", "FDS": "FDS", "PICO-8": "PICO8",
    },
    "retropie": {
        "NES": "nes", "SNES": "snes", "GB": "gb", "GBC": "gbc", "GBA": "gba",
        "N64": "n64", "NDS": "nds", "PS1": "psx", "PS2": "ps2", "PSP": "psp",
        "Genesis": "megadrive", "GameGear": "gamegear", "MasterSys": "mastersystem",
        "Dreamcast": "dreamcast", "Saturn": "saturn", "PCE": "pcengine",
        "NeoGeo": "neogeo", "MAME": "mame-libretro", "Lynx": "atarilynx",
        "WonderSwan": "wonderswan", "Atari2600": "atari2600", "FDS": "fds",
        "GameCube": "gamecube", "Wii": "wii", "PICO-8": "pico8",
    },
    "batocera": {
        "NES": "nes", "SNES": "snes", "GB": "gb", "GBC": "gbc", "GBA": "gba",
        "N64": "n64", "NDS": "nds", "PS1": "psx", "PS2": "ps2", "PSP": "psp",
        "Genesis": "megadrive", "GameGear": "gamegear", "MasterSys": "mastersystem",
        "Dreamcast": "dreamcast", "Saturn": "saturn", "PCE": "pcengine",
        "NeoGeo": "neogeo", "MAME": "mame", "Lynx": "lynx",
        "WonderSwan": "wonderswan", "Atari2600": "atari2600", "FDS": "fds",
        "GameCube": "gamecube", "Wii": "wii", "PICO-8": "pico8",
    },
}

_ROMS_ROOT = {
    "miyoo":      "Roms",
    "miyoo_plus": "Roms",
    "anbernic":   "Roms",
    "retropie":   "roms",
    "batocera":   "roms",
}


import re as _re

_UNSAFE_CHARS = str.maketrans({
    "/": "-", "\\": "-", ":": " -", "*": "",
    "?": "", '"': "'", "<": "(", ">": ")", "|": "-",
})

# Matches leading release numbers like "0001 - " or "004 - " but not game names
# like "1-2-Switch" (no space after the dash).
_LEADING_NUM = _re.compile(r'^\d+\s*-\s+')


def _clean_name(dat_name: str, suffix: str) -> str:
    """Turn a DAT game name into a safe filename, preserving the original extension."""
    name = _LEADING_NUM.sub("", dat_name).strip()
    name = name.translate(_UNSAFE_CHARS).strip()
    while "  " in name:
        name = name.replace("  ", " ")
    return name + suffix


def _dest_dir(out: Path, profile: str, console: str) -> Path:
    if profile == "flat":
        return out
    if profile == "by_console":
        return out / console
    mapping = _MAPS.get(profile, {})
    folder  = mapping.get(console, console)
    root    = _ROMS_ROOT.get(profile, "roms")
    return out / root / folder


def preview_export(roms: List[dict]) -> dict:
    """Calculate real disk size and missing-file count without copying anything."""
    total_size    = 0
    missing_files = 0
    for rom in roms:
        p = rom.get("path", "")
        if p and os.path.exists(p):
            total_size += os.path.getsize(p)
        else:
            missing_files += 1
    return {"count": len(roms), "total_size": total_size, "missing_files": missing_files}


def export_library(roms: List[dict], output_dir: str, profile: str = "by_console") -> dict:
    """
    Copy collected ROMs to output_dir organised by profile.
    roms: list of {path, console, name, ...}
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    copied  = 0
    skipped = 0
    errors  = []

    for rom in roms:
        src = Path(rom.get("path", ""))
        if not src.exists():
            skipped += 1
            continue

        console  = rom.get("console", "Unknown")
        dest_dir = _dest_dir(out, profile, console)
        dest_dir.mkdir(parents=True, exist_ok=True)

        dat_name  = rom.get("name", "").strip()
        file_name = _clean_name(dat_name, src.suffix) if dat_name else src.name
        dest = dest_dir / file_name

        try:
            shutil.copy2(str(src), str(dest))   # overwrites if already exists
            copied += 1
        except OSError as e:
            errors.append({"file": src.name, "error": str(e)})

    manifest = {
        "profile":     profile,
        "exported_at": datetime.now().isoformat(),
        "copied":      copied,
        "skipped":     skipped,
        "errors":      errors,
    }
    with open(out / "romeo_manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    return {"ok": True, "copied": copied, "skipped": skipped,
            "errors": errors, "output": str(out)}
