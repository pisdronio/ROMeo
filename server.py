#!/usr/bin/env python3
"""ROMeo - DAT-first ROM library organizer."""

VERSION = "0.3"

import os
import sys
import uuid
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory

sys.path.insert(0, str(Path(__file__).parent))

from core.scanner import scan_for_crcs, detect_console, compute_crc32_candidates
from core.dats import (dat_status, download_dat, LIBRETRO_DATS,
                        invalidate_cache, dat_to_game_entries, load_all_dats, get_dat)
from core.db import (upsert_games, bulk_add_collection,
                     get_catalog_groups, get_catalog_stats, get_collection_for_export,
                     clear_catalog, save_scan, get_recent_scans)
from core.fileops import (safe_trash, restore_from_trash, empty_trash,
                           trash_contents, export_library, preview_export)
from core.converter import convert_file, ALL_CONVERTIBLE, MANUAL_CONVERTIBLE

app = Flask(__name__, static_folder="static")

# ── In-memory progress state ──────────────────────────────────────────────────

# Master list of every console ROMeo knows about
KNOWN_CONSOLES = {
    # Nintendo
    "NES":          "Nintendo Entertainment System",
    "SNES":         "Super Nintendo",
    "N64":          "Nintendo 64",
    "GameCube":     "GameCube",
    "Wii":          "Wii",
    "WiiU":         "Wii U",
    "FDS":          "Famicom Disk System",
    "Satellaview":  "Satellaview",
    "SufamiTurbo":  "Sufami Turbo",
    "GB":           "Game Boy",
    "GBC":          "Game Boy Color",
    "GBA":          "Game Boy Advance",
    "NDS":          "Nintendo DS",
    "VirtualBoy":   "Virtual Boy",
    "GameWatch":    "Game & Watch",
    "PokeMini":     "Pokémon Mini",
    # Sony
    "PS1":          "PlayStation",
    "PS2":          "PlayStation 2",
    "PS3":          "PlayStation 3",
    "PSP":          "PlayStation Portable",
    "PSMinis":      "PlayStation Minis",
    # Sega
    "Genesis":      "Genesis / Mega Drive",
    "Sega32X":      "Sega 32X",
    "SegaCD":       "Sega CD",
    "Saturn":       "Saturn",
    "Dreamcast":    "Dreamcast",
    "MasterSys":    "Master System",
    "SG1000":       "SG-1000",
    "GameGear":     "Game Gear",
    # SNK
    "NeoGeo":       "Neo Geo",
    "NeoGeoCD":     "Neo Geo CD",
    "NGP":          "Neo Geo Pocket",
    # NEC
    "PCE":          "PC Engine",
    "PCECD":        "PC Engine CD",
    "SuperGrafx":   "SuperGrafx",
    "PC98":         "PC-98",
    # Atari
    "Atari2600":    "Atari 2600",
    "Atari5200":    "Atari 5200",
    "Atari7800":    "Atari 7800",
    "Lynx":         "Atari Lynx",
    "AtariST":      "Atari ST",
    # Bandai
    "WonderSwan":   "WonderSwan",
    # Capcom arcade
    "CPS1":         "CPS1",
    "CPS2":         "CPS2",
    "CPS3":         "CPS3",
    # Arcade
    "MAME":         "MAME / Arcade",
    "Atomiswave":   "Atomiswave",
    "HBMAME":       "HBMAME",
    # Home computers
    "Amiga":        "Amiga",
    "CD32":         "Amiga CD32",
    "C64":          "Commodore 64",
    "AmstradCPC":   "Amstrad CPC",
    "MSX":          "MSX",
    "ZXSpectrum":   "ZX Spectrum",
    "ZX81":         "ZX Spectrum 81",
    "DOS":          "DOS",
    # Other hardware
    "Vectrex":      "Vectrex",
    "ColecoVision": "ColecoVision",
    "Intellivision":"Intellivision",
    "Odyssey2":     "Odyssey 2",
    "FairchildF":   "Fairchild Channel F",
    "MegaDuck":     "Mega Duck",
    "Supervision":  "Supervision",
    # Fantasy / indie consoles
    "PICO-8":       "PICO-8",
    "TIC80":        "TIC-80",
    "LowResNX":     "LowRes NX",
    "Arduboy":      "Arduboy",
    "CHIP8":        "CHIP-8",
    "Uzebox":       "Uzebox",
    "Vircon32":     "Vircon32",
    "WASM4":        "WASM-4",
    "MicroW8":      "MicroW8",
    # Game engines / ports
    "ScummVM":      "ScummVM",
    "DOOM":         "DOOM",
    "Quake":        "Quake",
    "QuakeII":      "Quake II",
    "QuakeIII":     "Quake III",
    "Wolfenstein3D":"Wolfenstein 3D",
    "TombRaider":   "Tomb Raider",
    "Flashback":    "Flashback",
    "CaveStory":    "Cave Story",
    "RPGMaker":     "RPG Maker",
    "ChaiLove":     "ChaiLove",
    "Lutro":        "Lutro",
    "PuzzleScript": "PuzzleScript",
    "ZMachine":     "Z-Machine",
}

scan_progress = {"status": "idle", "current": 0, "total": 0,
                 "file": "", "scan_id": None, "matched": 0,
                 "unmatched_by_console": {}, "convertible": []}
scan_lock = threading.Lock()

convert_progress = {"status": "idle", "current": 0, "total": 0,
                    "file": "", "results": [], "converted_paths": []}
convert_lock = threading.Lock()

dat_progress = {"status": "idle", "message": "", "done": [], "failed": []}
dat_lock = threading.Lock()


# ── Version ───────────────────────────────────────────────────────────────────

@app.route("/api/version")
def get_version():
    from core.scanner import _find_chdman
    return jsonify({"version": VERSION, "chdman": bool(_find_chdman())})


@app.route("/api/tools")
def tools_status():
    from core.scanner import _find_chdman
    return jsonify({"chdman": _find_chdman() or None})


# ── Static ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/static/<path:path>")
def static_files(path):
    return send_from_directory("static", path)


# ── Scan ──────────────────────────────────────────────────────────────────────

@app.route("/api/scan", methods=["POST"])
def start_scan():
    data = request.json or {}
    root      = data.get("path", "").strip()
    files_in  = data.get("files", [])    # explicit individual files
    folders_in = data.get("folders", []) # multiple folders

    # Normalize: single path → folders list
    if root:
        folders_in = [root] + [f for f in folders_in if f != root]

    if not folders_in and not files_in:
        return jsonify({"ok": False, "error": "Provide a folder path or file list"}), 400
    for folder in folders_in:
        if not os.path.isdir(folder):
            return jsonify({"ok": False, "error": f"Not a directory: {folder}"}), 400

    with scan_lock:
        if scan_progress["status"] == "scanning":
            return jsonify({"ok": False, "error": "Scan already in progress"}), 409

    scan_id = str(uuid.uuid4())[:8]

    def run():
        started = datetime.now().isoformat()
        with scan_lock:
            scan_progress.update({
                "status": "scanning", "current": 0, "total": 0,
                "file": "", "scan_id": scan_id, "matched": 0
            })

        def progress_cb(current, total, path):
            with scan_lock:
                scan_progress["current"] = current
                scan_progress["total"] = total
                scan_progress["file"] = os.path.basename(path)

        try:
            # Load all available DATs into one flat CRC32 lookup
            global_dat = load_all_dats()

            from core.scanner import KNOWN_EXTENSIONS, scan_for_crcs

            if folders_in and not files_in:
                # Pure folder scan (original fast path)
                if len(folders_in) == 1:
                    files = scan_for_crcs(folders_in[0], progress_cb=progress_cb)
                else:
                    files = []
                    for folder in folders_in:
                        files += scan_for_crcs(folder, progress_cb=progress_cb)
            else:
                # Individual files (+ optional folder expansion)
                all_paths = list(files_in)
                for folder in folders_in:
                    folder_files = scan_for_crcs(folder)
                    all_paths += [f["path"] for f in folder_files]

                valid = [p for p in dict.fromkeys(all_paths)  # deduplicate, preserve order
                         if Path(p).suffix.lower() in KNOWN_EXTENSIONS]
                total = len(valid)
                scanned = []
                for i, p in enumerate(valid):
                    progress_cb(i + 1, total, p)
                    fp = Path(p)
                    size = fp.stat().st_size if fp.exists() else 0
                    if size < 2 * 1024 * 1024 * 1024:
                        crcs = compute_crc32_candidates(fp)
                    else:
                        crcs = []
                    primary = crcs[0] if crcs else ""
                    scanned.append({"path": p, "crc32": primary, "crcs": crcs, "size": size})
                files = scanned

            now = datetime.now().isoformat()
            matches = []
            for f in files:
                candidates = f.get("crcs") or ([f["crc32"]] if f.get("crc32") else [])
                for key in candidates:
                    if key and key in global_dat:
                        entry = global_dat[key]
                        # For SHA1-keyed entries (CHD), use the original DAT CRC32
                        real_crc = entry.get("real_crc32", key)
                        matches.append({"crc32": real_crc, "rom_path": f["path"], "scanned_at": now})
                        break  # one match per file is enough

            # Track unmatched files grouped by detected console + extensions
            unmatched_by_console: dict = {}
            convertible: list = []
            matched_paths = {m["rom_path"] for m in matches}
            for f in files:
                if f["path"] not in matched_paths:
                    p   = Path(f["path"])
                    ext = p.suffix.lower()
                    con = detect_console(p)
                    if con and con != "Unknown":
                        entry = unmatched_by_console.setdefault(con, {"count": 0, "exts": {}})
                        entry["count"] += 1
                        entry["exts"][ext] = entry["exts"].get(ext, 0) + 1
                    if ext in ALL_CONVERTIBLE:
                        convertible.append({
                            "path": f["path"],
                            "ext":  ext,
                            "manual": ext in MANUAL_CONVERTIBLE,
                            "note":  MANUAL_CONVERTIBLE.get(ext, ""),
                        })

            bulk_add_collection(matches)
            finished = datetime.now().isoformat()
            scan_label = folders_in[0] if len(folders_in) == 1 and not files_in else f"{len(files)} files scanned"
            save_scan(scan_id, scan_label, started, finished, len(files), len(matches), "done")

            with scan_lock:
                scan_progress["status"] = "done"
                scan_progress["total"] = len(files)
                scan_progress["matched"] = len(matches)
                scan_progress["unmatched_by_console"] = unmatched_by_console
                scan_progress["convertible"] = convertible

        except Exception as e:
            with scan_lock:
                scan_progress["status"] = "error"
                scan_progress["file"] = str(e)

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True, "scan_id": scan_id})


@app.route("/api/scan/progress")
def scan_progress_endpoint():
    with scan_lock:
        return jsonify(dict(scan_progress))


# ── Convert ───────────────────────────────────────────────────────────────────

@app.route("/api/convert", methods=["POST"])
def start_convert():
    data  = request.json or {}
    paths = data.get("paths", [])
    if not paths:
        return jsonify({"ok": False, "error": "No files provided"}), 400

    with convert_lock:
        if convert_progress["status"] == "converting":
            return jsonify({"ok": False, "error": "Conversion already running"}), 409

    def run():
        with convert_lock:
            convert_progress.update({
                "status": "converting", "current": 0,
                "total": len(paths), "file": "",
                "results": [], "converted_paths": [],
            })

        results = []
        converted = []
        for i, p in enumerate(paths):
            src = Path(p)
            with convert_lock:
                convert_progress["current"] = i + 1
                convert_progress["file"]    = src.name

            def _prog(cur, tot):
                pass  # block-level progress not surfaced to UI (file-level is enough)

            ok, msg, out = convert_file(src, _prog)
            results.append({"path": p, "ok": ok, "msg": msg,
                             "output": str(out) if out else None})
            if ok and out:
                converted.append(str(out))

        with convert_lock:
            convert_progress["status"]          = "done"
            convert_progress["results"]         = results
            convert_progress["converted_paths"] = converted

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/convert/progress")
def convert_progress_endpoint():
    with convert_lock:
        return jsonify(dict(convert_progress))


# ── Catalog ───────────────────────────────────────────────────────────────────

@app.route("/api/catalog/stats")
def catalog_stats():
    return jsonify(get_catalog_stats())


@app.route("/api/catalog/groups")
def catalog_groups():
    console = request.args.get("console")
    search  = request.args.get("q", "")
    show    = request.args.get("show", "all")
    letter  = request.args.get("letter", "")
    groups  = get_catalog_groups(console=console, show=show, search=search, letter=letter)
    return jsonify({"groups": groups, "total": len(groups)})


@app.route("/api/catalog/clear", methods=["POST"])
def catalog_clear():
    data = request.json or {}
    console = data.get("console") or None
    clear_catalog(console=console)
    return jsonify({"ok": True})


# ── Folder / file picker ──────────────────────────────────────────────────────

_REFOCUS_SCRIPT = """
tell application "System Events"
    set browsers to {"Google Chrome", "Safari", "Firefox", "Arc", "Brave Browser", "Microsoft Edge", "Opera"}
    repeat with b in browsers
        if exists (processes where name is b) then
            set frontmost of first process whose name is b to true
            exit repeat
        end if
    end repeat
end tell
"""

def _refocus_browser():
    import subprocess
    subprocess.run(["osascript", "-e", _REFOCUS_SCRIPT], capture_output=True)


@app.route("/api/browse")
def browse_folder():
    import subprocess
    script = 'tell application "Finder" to set f to choose folder\nreturn POSIX path of f'
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    _refocus_browser()
    if result.returncode != 0:
        return jsonify({"ok": False, "path": None})
    return jsonify({"ok": True, "path": result.stdout.strip().rstrip("/")})


@app.route("/api/browse/file")
def browse_file():
    import subprocess
    script = 'set f to choose file with prompt "Select a DAT file"\nreturn POSIX path of f'
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    _refocus_browser()
    if result.returncode != 0:
        return jsonify({"ok": False, "path": None})
    return jsonify({"ok": True, "path": result.stdout.strip()})


@app.route("/api/browse/files")
def browse_files():
    """Open a multi-file picker for ROM files."""
    import subprocess
    script = (
        'set chosen to choose file with prompt "Select ROM files" '
        'with multiple selections allowed\n'
        'set posixPaths to {}\n'
        'repeat with f in chosen\n'
        '  set end of posixPaths to POSIX path of f\n'
        'end repeat\n'
        'set AppleScript\'s text item delimiters to "\\n"\n'
        'return posixPaths as text'
    )
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    _refocus_browser()
    if result.returncode != 0:
        return jsonify({"ok": False, "paths": []})
    paths = [p.strip() for p in result.stdout.strip().splitlines() if p.strip()]
    return jsonify({"ok": True, "paths": paths})


# ── Trash / File ops ──────────────────────────────────────────────────────────

@app.route("/api/trash/send", methods=["POST"])
def trash_send():
    data = request.json or {}
    paths = data.get("paths", [])
    results = [{"path": p, **safe_trash(p)} for p in paths]
    return jsonify({"results": results})


@app.route("/api/trash/list")
def trash_list():
    return jsonify(trash_contents())


@app.route("/api/trash/restore", methods=["POST"])
def trash_restore():
    data = request.json or {}
    return jsonify(restore_from_trash(data.get("trash_path"), data.get("original_path")))


@app.route("/api/trash/empty", methods=["POST"])
def trash_empty():
    return jsonify(empty_trash())


# ── Export ────────────────────────────────────────────────────────────────────

def _export_opts(data: dict) -> dict:
    return {
        "one_per_game":  data.get("one_per_game", False),
        "skip_bad_tags": data.get("skip_bad_tags", False),
        "consoles":      data.get("consoles") or None,
    }


@app.route("/api/export/preview", methods=["POST"])
def export_preview():
    data        = request.json or {}
    capacity_gb = int(data.get("capacity_gb") or 0)
    roms        = get_collection_for_export(**_export_opts(data))

    # Measure real on-disk sizes
    cap_bytes = capacity_gb * 1024 ** 3
    per_console: dict = {}
    total_size  = 0
    missing     = 0

    for rom in roms:
        p    = rom.get("path", "")
        size = os.path.getsize(p) if p and os.path.exists(p) else 0
        if not size:
            missing += 1
        con = rom["console"]
        if con not in per_console:
            per_console[con] = {"count": 0, "size": 0, "fits": True}
        per_console[con]["count"] += 1
        per_console[con]["size"]  += size
        total_size += size

    # Mark per-console fit status against capacity
    if cap_bytes:
        running = 0
        for con, info in per_console.items():
            if running + info["size"] <= cap_bytes:
                info["fits"] = True
                running += info["size"]
            else:
                info["fits"] = False

    fits      = (total_size <= cap_bytes) if cap_bytes else True
    remaining = (cap_bytes - total_size)  if cap_bytes else None

    logs = []
    if cap_bytes and not fits:
        over_mb = abs(remaining) // (1024 ** 2)
        logs.append({"level": "warn", "msg": f"Exceeds capacity by {over_mb:,} MB — deselect some consoles or switch to 1-game/1-ROM mode."})
    if missing:
        logs.append({"level": "info", "msg": f"{missing} ROM files not found on disk — they will be skipped."})

    return jsonify({
        "ok": True, "count": len(roms), "total_size": total_size,
        "missing_files": missing, "per_console": per_console,
        "fits": fits, "remaining": remaining, "logs": logs,
    })


@app.route("/api/export/autofit", methods=["POST"])
def export_autofit():
    """Return the set of consoles that fit within the given capacity, keeping most games."""
    data        = request.json or {}
    capacity_gb = int(data.get("capacity_gb") or 0)
    if not capacity_gb:
        return jsonify({"ok": False, "error": "No capacity specified"}), 400

    roms = get_collection_for_export(**_export_opts(data))

    # Group roms by console and measure sizes
    per_console: dict = {}
    for rom in roms:
        p    = rom.get("path", "")
        size = os.path.getsize(p) if p and os.path.exists(p) else 0
        con  = rom["console"]
        per_console.setdefault(con, {"count": 0, "size": 0})
        per_console[con]["count"] += 1
        per_console[con]["size"]  += size

    cap_bytes = capacity_gb * 1024 ** 3
    # Sort: most games first (keep the richest consoles)
    sorted_consoles = sorted(per_console.items(), key=lambda x: -x[1]["count"])

    included = []
    used = 0
    for con, info in sorted_consoles:
        if used + info["size"] <= cap_bytes:
            included.append(con)
            used += info["size"]

    return jsonify({"ok": True, "consoles": included, "used": used, "remaining": cap_bytes - used})


@app.route("/api/export", methods=["POST"])
def do_export():
    data       = request.json or {}
    output_dir = data.get("output_dir", "").strip()
    profile    = data.get("profile", "by_console")

    if not output_dir:
        return jsonify({"ok": False, "error": "No output directory specified"}), 400

    roms   = get_collection_for_export(**_export_opts(data))
    result = export_library(roms, output_dir, profile)
    return jsonify(result)


# ── DAT management ────────────────────────────────────────────────────────────

@app.route("/api/dats/status")
def dats_status():
    loaded = dat_status()   # consoles that have a .dat file on disk
    # Merge with full known console list so the bookshelf is always complete
    result = {}
    for con, friendly in KNOWN_CONSOLES.items():
        if con in loaded:
            result[con] = {**loaded[con], "friendly": friendly, "known": True}
        else:
            result[con] = {
                "available":    False,
                "entries":      0,
                "downloadable": con in LIBRETRO_DATS,
                "friendly":     friendly,
                "known":        True,
            }
    # Also include any manually imported consoles not in KNOWN_CONSOLES
    for con, info in loaded.items():
        if con not in result:
            result[con] = {**info, "friendly": con, "known": False}
    return jsonify(result)


@app.route("/api/scan/unmatched")
def scan_unmatched():
    with scan_lock:
        return jsonify(scan_progress.get("unmatched_by_console", {}))


@app.route("/api/dats/download", methods=["POST"])
def dats_download():
    data = request.json or {}
    consoles = data.get("consoles", list(LIBRETRO_DATS.keys()))

    with dat_lock:
        if dat_progress["status"] == "downloading":
            return jsonify({"ok": False, "error": "Download already in progress"}), 409

    def run():
        with dat_lock:
            dat_progress.update({"status": "downloading", "message": "", "done": [], "failed": []})

        def cb(msg):
            with dat_lock:
                dat_progress["message"] = msg

        for console in consoles:
            ok = download_dat(console, progress_cb=cb)
            if ok:
                invalidate_cache(console)
                dat = get_dat(console)
                upsert_games(dat_to_game_entries(console, dat))
                with dat_lock:
                    dat_progress["done"].append(console)
            else:
                with dat_lock:
                    dat_progress["failed"].append(console)

        with dat_lock:
            dat_progress["status"] = "done"

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/dats/progress")
def dats_download_progress():
    with dat_lock:
        return jsonify(dict(dat_progress))


def _detect_console_from_dat(src: str) -> str:
    """
    Read the DAT header and map the system name to our internal console key.
    Supports both XML (Logiqx) and ClrMamePro formats.
    Returns '' if unrecognised.
    """
    import zipfile, re as _re

    # Mapping from substrings in the DAT name field → internal console key.
    # Checked case-insensitively in order; first match wins.
    _NAME_MAP = [
        ("super nintendo",          "SNES"),
        ("super famicom",           "SNES"),
        ("nintendo entertainment",  "NES"),
        ("famicom disk",            "FDS"),
        ("game boy advance",        "GBA"),
        ("game boy color",          "GBC"),
        ("game boy",                "GB"),
        ("nintendo - wii ",         "Wii"),       # trailing space avoids matching "Wii U"
        ("wii u",                   "WiiU"),
        ("gamecube",                "GameCube"),
        ("nintendo 64",             "N64"),
        ("nintendo ds",             "NDS"),
        ("nintendo - pico-8",       "PICO-8"),
        ("pico-8",                  "PICO-8"),
        ("playstation - psp",       "PSP"),
        ("playstation 2",           "PS2"),
        ("playstation",             "PS1"),
        ("sega - saturn",           "Saturn"),
        ("sega - dreamcast",        "Dreamcast"),
        ("sega - mega drive",       "Genesis"),
        ("sega - genesis",          "Genesis"),
        ("sega - master system",    "MasterSys"),
        ("sega - game gear",        "GameGear"),
        ("snk - neo geo",           "NeoGeo"),
        ("neo geo",                 "NeoGeo"),
        ("turbografx",              "PCE"),
        ("pc engine",               "PCE"),
        ("atari - lynx",            "Lynx"),
        ("atari - 2600",            "Atari2600"),
        ("atari - 7800",            "Atari7800"),
        ("wonderswan",              "WonderSwan"),
        ("mame",                    "MAME"),
    ]

    def _read_header_text(path):
        """Return first ~4 KB of the DAT (decompressing zip if needed)."""
        if path.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(path, "r") as zf:
                    dat_entries = [e for e in zf.namelist() if e.lower().endswith(".dat")]
                    if not dat_entries:
                        return ""
                    with zf.open(dat_entries[0]) as f:
                        return f.read(4096).decode("utf-8", errors="replace")
            except Exception:
                return ""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read(4096)
        except Exception:
            return ""

    text = _read_header_text(src)
    if not text:
        return ""

    # Extract the name value — try XML then ClrMamePro
    name_val = ""
    xml_m = _re.search(r"<name>([^<]+)</name>", text, _re.IGNORECASE)
    if xml_m:
        name_val = xml_m.group(1).strip()
    else:
        cm_m = _re.search(r'\bname\s+"([^"]+)"', text, _re.IGNORECASE)
        if cm_m:
            name_val = cm_m.group(1).strip()

    if not name_val:
        return ""

    lower = name_val.lower()
    for needle, key in _NAME_MAP:
        if needle in lower:
            return key
    return ""


@app.route("/api/dats/detect", methods=["POST"])
def dats_detect():
    """Return the detected console key for a given DAT/zip file path."""
    data = request.json or {}
    src  = data.get("path", "").strip()
    if not src or not os.path.isfile(src):
        return jsonify({"ok": False, "error": "File not found"}), 400
    console = _detect_console_from_dat(src)
    return jsonify({"ok": True, "console": console})


@app.route("/api/dats/import", methods=["POST"])
def dats_import():
    import shutil
    import zipfile
    from core.dats import DAT_DIR
    data = request.json or {}
    console = data.get("console", "").strip()
    src = data.get("path", "").strip()

    # Auto-detect console if not provided
    if not console:
        console = _detect_console_from_dat(src)
    if not console:
        return jsonify({"ok": False, "error": "Could not detect console — please specify one"}), 400
    if not src or not os.path.isfile(src):
        return jsonify({"ok": False, "error": "File not found"}), 400

    DAT_DIR.mkdir(parents=True, exist_ok=True)
    dest = DAT_DIR / f"{console}.dat"

    if src.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(src, "r") as zf:
                dat_entries = [e for e in zf.namelist() if e.lower().endswith(".dat")]
                if not dat_entries:
                    return jsonify({"ok": False, "error": "No .dat file found inside zip"}), 400
                with zf.open(dat_entries[0]) as f_in, open(dest, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
        except zipfile.BadZipFile:
            return jsonify({"ok": False, "error": "Invalid zip file"}), 400
    else:
        shutil.copy2(src, dest)

    invalidate_cache(console)
    dat = get_dat(console)
    entries = dat_to_game_entries(console, dat)
    upsert_games(entries)

    return jsonify({"ok": True, "console": console, "entries": len(dat)})


@app.route("/api/dats/delete", methods=["POST"])
def dats_delete():
    import shutil
    from core.dats import DAT_DIR
    data    = request.json or {}
    console = data.get("console", "").strip()
    if not console:
        return jsonify({"ok": False, "error": "No console specified"}), 400
    dest = DAT_DIR / f"{console}.dat"
    if not dest.exists():
        return jsonify({"ok": False, "error": "DAT not found"}), 404
    dest.unlink()
    invalidate_cache(console)
    clear_catalog(console=console)
    return jsonify({"ok": True})


# ── History ───────────────────────────────────────────────────────────────────

@app.route("/api/scans")
def recent_scans():
    return jsonify(get_recent_scans())


# ── Catalog rebuild ───────────────────────────────────────────────────────────

@app.route("/api/catalog/rebuild", methods=["POST"])
def catalog_rebuild():
    """Re-import all DAT files on disk, cleaning names and group keys."""
    invalidate_cache()        # flush in-memory DAT cache so files are re-parsed fresh
    bootstrap_catalog()
    return jsonify({"ok": True})


# ── Launch ────────────────────────────────────────────────────────────────────

def open_browser():
    import time
    time.sleep(1.2)
    webbrowser.open("http://localhost:7777")


def bootstrap_catalog():
    """Load any DAT files already on disk into the games catalog (idempotent)."""
    from core.dats import DAT_DIR, get_dat, dat_to_game_entries
    if not DAT_DIR.exists():
        return
    for dat_file in DAT_DIR.glob("*.dat"):
        console = dat_file.stem
        dat = get_dat(console)
        if dat:
            entries = dat_to_game_entries(console, dat)
            upsert_games(entries)
            print(f"  Catalog: loaded {len(entries)} {console} games")


if __name__ == "__main__":
    print("╔══════════════════════════════════╗")
    print(f"║          ROMeo  v{VERSION:<16} ║")
    print("║    http://localhost:7777         ║")
    print("╚══════════════════════════════════╝")
    from core.db import init_db
    init_db()
    bootstrap_catalog()
    threading.Thread(target=open_browser, daemon=True).start()
    app.run(host="127.0.0.1", port=7777, debug=False)
