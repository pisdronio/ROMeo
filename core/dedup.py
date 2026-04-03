"""Deduplication engine - groups ROMs and scores each copy."""

from collections import defaultdict
from typing import List, Dict, Tuple
from .scanner import RomFile, region_score, REGION_PRIORITY


def score_rom(rom: RomFile) -> Tuple:
    """
    Returns a tuple. Python sorts tuples lexicographically,
    so we negate where higher is better.
    Higher tuple = better ROM.
    """
    return (
        0 if rom.bad_tags else 1,        # good tags preferred
        1 if rom.verified else 0,        # DAT-verified preferred
        -region_score(rom.region),       # lower index = better region
        rom.revision,                    # higher revision preferred
        rom.size,                        # larger file preferred (usually more complete)
    )


def score_label(rom: RomFile) -> str:
    """Human-readable score breakdown."""
    parts = []
    if rom.verified:
        parts.append("Verified")
    if not rom.bad_tags:
        parts.append("Clean")
    else:
        parts.append("Has bad tags")
    if rom.region != "Unknown":
        parts.append(rom.region)
    if rom.revision > 0:
        parts.append(f"Rev {rom.revision}")
    return " · ".join(parts) if parts else "Unknown"


def group_roms(roms: List[RomFile]) -> Dict[str, List[RomFile]]:
    """Group ROMs by console + normalized title."""
    groups = defaultdict(list)
    for rom in roms:
        groups[rom.group_key].append(rom)
    return dict(groups)


def find_exact_duplicates(roms: List[RomFile]) -> Dict[str, List[RomFile]]:
    """Find ROMs with identical CRC32 (byte-for-byte same file)."""
    by_crc = defaultdict(list)
    for rom in roms:
        if rom.crc32:
            by_crc[rom.crc32].append(rom)
    return {k: v for k, v in by_crc.items() if len(v) > 1}


def pick_best(group: List[RomFile]) -> RomFile:
    """Pick the best ROM from a group."""
    return max(group, key=score_rom)


def apply_decisions(groups: Dict[str, List[RomFile]]) -> Dict[str, List[RomFile]]:
    """
    For each group, mark which ROM to keep and which to discard.
    Returns groups with .keep flags set.
    """
    for key, group in groups.items():
        if len(group) == 1:
            group[0].keep = True
            continue

        # Exact duplicates (same CRC) — keep only one
        crc_seen = {}
        for rom in group:
            if rom.crc32 and rom.crc32 in crc_seen:
                rom.duplicate_of = crc_seen[rom.crc32].path
                rom.keep = False
            elif rom.crc32:
                crc_seen[rom.crc32] = rom

        # Among non-exact-dupes, pick the best
        candidates = [r for r in group if r.keep or not r.duplicate_of]
        if not candidates:
            candidates = group

        best = pick_best(candidates)
        for rom in candidates:
            rom.keep = (rom.path == best.path)
            if not rom.keep and not rom.duplicate_of:
                rom.duplicate_of = best.path

    return groups


def build_summary(groups: Dict[str, List[RomFile]]) -> dict:
    total_roms = sum(len(g) for g in groups.values())
    total_groups = len(groups)
    duplicates = sum(
        sum(1 for r in g if not r.keep)
        for g in groups.values()
    )
    verified = sum(
        sum(1 for r in g if r.verified)
        for g in groups.values()
    )
    bad_tags = sum(
        sum(1 for r in g if r.bad_tags)
        for g in groups.values()
    )

    consoles = defaultdict(int)
    for key in groups:
        console = key.split("::")[0]
        consoles[console] += 1

    return {
        "total_roms": total_roms,
        "unique_games": total_groups,
        "duplicates": duplicates,
        "verified": verified,
        "bad_tags": bad_tags,
        "consoles": dict(sorted(consoles.items(), key=lambda x: -x[1])),
        "space_recoverable": sum(
            r.size
            for g in groups.values()
            for r in g
            if not r.keep
        ),
    }
