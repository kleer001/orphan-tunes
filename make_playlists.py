#!/usr/bin/env python3
"""
Write the iTunes playlists out as .m3u8 files pointing at the local audio.

    python make_playlists.py [output_dir]

Reads only. Every track is located three ways, in order: the Location recorded
by iTunes, then the same filename anywhere else in the library, then -- when a
name like '01 Track 1.mp3' matches several albums -- the file whose byte size
matches what iTunes recorded. Accented names match in either Unicode spelling.

Paths in the playlists are relative to the playlist file, so they keep working
when the drive is mounted somewhere other than where it is today.
"""

import os
import plistlib
import sys
import unicodedata
import urllib.parse
from collections import defaultdict

from config import LIBRARY, LOCAL_ROOT, PLAYLIST_DIR, RECORDED_ROOT

AUDIO = {".mp3", ".m4a", ".wav", ".mp4", ".aif", ".aiff",
         ".mpga", ".m4b", ".flac", ".ogg", ".mov", ".m4v"}


def nfc(text):
    """One spelling for accented text. The library XML spells é both as one
    character and as e plus a combining accent, and Linux compares names byte
    for byte."""
    return unicodedata.normalize("NFC", text)


def index_by_name(root):
    """filename (lowercased, NFC) -> [full paths], for tracks that moved album."""
    index = defaultdict(list)
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            if os.path.splitext(name)[1].lower() in AUDIO:
                index[nfc(name).lower()].append(os.path.join(dirpath, name))
    return index


def locate(track, index):
    """Full path to the audio, or None. Returns (path, how_it_was_found)."""
    recorded = urllib.parse.unquote(track["Location"][len("file://"):])
    direct = recorded.replace(RECORDED_ROOT, LOCAL_ROOT, 1)
    if os.path.isfile(direct):
        return direct, "direct"

    candidates = index.get(nfc(os.path.basename(direct)).lower(), [])
    same_place = [c for c in candidates if nfc(c) == nfc(direct)]
    if same_place:
        return same_place[0], "direct"
    if len(candidates) == 1:
        return candidates[0], "moved"
    if len(candidates) > 1:
        # Generic names like '01 Track 1.mp3' repeat across albums; the size
        # iTunes recorded picks the right one out.
        size = track.get("Size")
        exact = [c for c in candidates if os.path.getsize(c) == size]
        if len(exact) == 1:
            return exact[0], "by size"
        return None, "ambiguous"
    return None, "gone"


def safe_name(name, taken):
    """A playlist title turned into a filename that won't fight the filesystem."""
    cleaned = "".join("_" if c in '/\\:*?"<>|' else c for c in name).strip(" .")
    cleaned = cleaned or "untitled"
    candidate, n = cleaned, 2
    while candidate.lower() in taken:
        candidate = f"{cleaned} ({n})"
        n += 1
    taken.add(candidate.lower())
    return candidate


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else PLAYLIST_DIR
    os.makedirs(out_dir, exist_ok=True)

    with open(LIBRARY, "rb") as fh:
        lib = plistlib.load(fh)
    tracks = lib["Tracks"]

    print(f"indexing audio under {LOCAL_ROOT} ...")
    index = index_by_name(LOCAL_ROOT)
    print(f"  {sum(len(v) for v in index.values())} files, {len(index)} distinct names\n")

    playlists = [p for p in lib["Playlists"]
                 if "Smart Info" not in p and not p.get("Master")
                 and not p.get("Distinguished Kind") and p.get("Playlist Items")]

    taken, totals, written, skipped = set(), defaultdict(int), 0, []
    for playlist in playlists:
        lines, found = ["#EXTM3U"], 0
        for item in playlist["Playlist Items"]:
            track = tracks.get(str(item["Track ID"]))
            if not track or not track.get("Location"):
                totals["gone"] += 1
                continue

            path, how = locate(track, index)
            totals[how] += 1
            if not path:
                continue

            seconds = round(track.get("Total Time", 0) / 1000)
            artist = track.get("Artist") or track.get("Album Artist") or ""
            title = track.get("Name", "")
            label = f"{artist} - {title}" if artist else title
            lines.append(f"#EXTINF:{seconds},{label}")
            lines.append(os.path.relpath(path, out_dir))
            found += 1

        if not found:
            skipped.append(playlist["Name"])
            continue

        name = safe_name(playlist["Name"], taken)
        with open(os.path.join(out_dir, name + ".m3u8"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        written += 1

    resolved = totals["direct"] + totals["moved"] + totals["by size"]
    refs = sum(totals.values())
    print(f"wrote {written} playlists to {out_dir}")
    if skipped:
        print(f"skipped {len(skipped)} with nothing left on disk: {', '.join(skipped)}")
    print(f"\n{resolved} of {refs} track references resolved ({100 * resolved / refs:.1f}%)")
    for how in ("direct", "moved", "by size", "ambiguous", "gone"):
        if totals[how]:
            print(f"  {totals[how]:6d}  {how}")


if __name__ == "__main__":
    main()
