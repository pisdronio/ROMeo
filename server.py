#!/usr/bin/env python3
"""ROMeo - DAT-first ROM library organizer."""

import os
import sys
import uuid
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory

sys.path.insert(0, str(Path(__file__).parent))

from core.scanner import scan_for_crcs
from core.dats import (dat_status, download_dat, LIBRETRO_DATS,
                        invalidate_cache, dat_to_game_entries, load_all_dats, get_dat)
from core.db import (upsert_games, bulk_add_collection,
                     get_catalog_groups, get_catalog_stats, get_collection_for_export,
                     clear_catalog, save_scan, get_recent_scans)
from core.fileops import (safe_trash, restore_from_trash, empty_trash,
                           trash_contents, export_library, preview_export)

app = Flask(__name__, static_folder="static")

# ── In-memory progress state ──────────────────────────────────────────────────

scan_progress = {"status": "idle", "current": 0, "total": 0,
                 "file": "", "scan_id": None, "matched": 0}
scan_lock = threading.Lock()

dat_progress = {"status": "idle", "message": "", "done": [], "failed": []}
dat_lock = threading.Lock()


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
    root = data.get("path", "").strip()

    if not root or not os.path.isdir(root):
        return jsonify({"ok": False, "error": "Invalid directory path"}), 400

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

            files = scan_for_crcs(root, progress_cb=progress_cb)

            now = datetime.now().isoformat()
            matches = [
                {"crc32": f["crc32"], "rom_path": f["path"], "scanned_at": now}
                for f in files
                if f["crc32"] and f["crc32"] in global_dat
            ]

            bulk_add_collection(matches)
            finished = datetime.now().isoformat()
            save_scan(scan_id, root, started, finished, len(files), len(matches), "done")

            with scan_lock:
                scan_progress["status"] = "done"
                scan_progress["total"] = len(files)
                scan_progress["matched"] = len(matches)

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

@app.route("/api/browse")
def browse_folder():
    import subprocess
    script = 'tell application "Finder" to set f to choose folder\nreturn POSIX path of f'
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        return jsonify({"ok": False, "path": None})
    return jsonify({"ok": True, "path": result.stdout.strip().rstrip("/")})


@app.route("/api/browse/file")
def browse_file():
    import subprocess
    script = 'set f to choose file with prompt "Select a DAT file"\nreturn POSIX path of f'
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        return jsonify({"ok": False, "path": None})
    return jsonify({"ok": True, "path": result.stdout.strip()})


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
    return jsonify(dat_status())


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
    print("║          ROMeo  v0.2             ║")
    print("║    http://localhost:7777         ║")
    print("╚══════════════════════════════════╝")
    from core.db import init_db
    init_db()
    bootstrap_catalog()
    threading.Thread(target=open_browser, daemon=True).start()
    app.run(host="127.0.0.1", port=7777, debug=False)
