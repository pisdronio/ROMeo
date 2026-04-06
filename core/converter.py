"""ROM format conversion utilities — writes converted file next to source."""

import zlib
import struct
from pathlib import Path
from typing import Optional, Tuple, Callable

# Formats we can convert automatically
AUTO_CONVERTIBLE = {".cso"}

# Formats that need a manual external tool
MANUAL_CONVERTIBLE = {
    ".pbp": "Use Retroarch › Tools › Convert Content, or PSX2PSP (Windows only)"
}

# All formats that show up in the conversion panel
ALL_CONVERTIBLE = AUTO_CONVERTIBLE | set(MANUAL_CONVERTIBLE)


def convert_cso(src: Path,
                progress_cb: Optional[Callable[[int, int], None]] = None,
                ) -> Tuple[bool, str, Optional[Path]]:
    """
    Decompress a CSO (Compressed ISO) to a plain ISO file written next to src.
    Returns (success, message, output_path).
    """
    dst = src.with_suffix(".iso")
    if dst.exists():
        return True, "Already converted", dst

    try:
        with open(src, "rb") as f:
            magic = f.read(4)
            if magic != b"CISO":
                return False, "Not a valid CSO file", None

            f.read(4)                                         # header size (unused)
            total_bytes = struct.unpack("<Q", f.read(8))[0]
            block_size  = struct.unpack("<I", f.read(4))[0]
            f.read(1)                                         # version
            f.read(1)                                         # align
            f.read(2)                                         # reserved

            if block_size == 0:
                return False, "Invalid CSO block size", None

            num_blocks = (total_bytes + block_size - 1) // block_size
            index_raw  = f.read((num_blocks + 1) * 4)
            index      = struct.unpack_from(f"<{num_blocks + 1}I", index_raw)

            with open(dst, "wb") as out:
                for i in range(num_blocks):
                    if progress_cb:
                        progress_cb(i + 1, num_blocks)

                    raw_off    = index[i]
                    compressed = not bool(raw_off & 0x80000000)
                    offset     = raw_off & 0x7FFFFFFF
                    next_off   = index[i + 1] & 0x7FFFFFFF

                    f.seek(offset)
                    data = f.read(next_off - offset)
                    if compressed:
                        data = zlib.decompress(data, -15)   # raw deflate
                    out.write(data)

        return True, f"→ {dst.name}", dst

    except Exception as e:
        if dst.exists():
            dst.unlink()
        return False, str(e), None


def convert_file(src: Path,
                 progress_cb: Optional[Callable[[int, int], None]] = None,
                 ) -> Tuple[bool, str, Optional[Path]]:
    """Dispatch to the right converter based on extension."""
    ext = src.suffix.lower()
    if ext == ".cso":
        return convert_cso(src, progress_cb)
    if ext in MANUAL_CONVERTIBLE:
        return False, MANUAL_CONVERTIBLE[ext], None
    return False, f"No converter for {ext}", None
