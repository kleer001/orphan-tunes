#!/usr/bin/env python3
"""
Build a local browser for the exported playlists, in the iTunes 4 idiom.

    python build_browser.py [output_dir]

Emits data.json (a shared track pool plus one index list per playlist) and
index.html. Reads only. Serve the output directory over localhost.
"""

import json
import os
import plistlib
import sys
from collections import defaultdict
from typing import NamedTuple

from config import BROWSER_DIR, LIBRARY, LOCAL_ROOT
from make_playlists import locate  # the .m3u8 writer's own file lookup

# Every field worth showing, in iTunes' own column order. "plumbing" fields
# (Track ID, Location, Persistent ID, the Sort* sort keys, the *Computed flags)
# are the only ones left behind. type drives both formatting and alignment;
# `show` is the default column set, the rest are available from View Options.
FIELDS = [
    ("Name",           "Song Name",   "text", True),
    ("Total Time",     "Time",        "time", True),
    ("Artist",         "Artist",      "text", True),
    ("Album",          "Album",       "text", True),
    ("Genre",          "Genre",       "text", True),
    ("Year",           "Year",        "int",  True),
    ("Size",           "Size",        "size", True),
    ("Play Count",     "Plays",       "int",  True),
    ("Album Artist",   "Album Artist", "text", False),
    ("Composer",       "Composer",    "text", False),
    ("Grouping",       "Grouping",    "text", False),
    ("Work",           "Work",        "text", False),
    ("Kind",           "Kind",        "text", False),
    ("Track Number",   "#",           "int",  False),
    ("Track Count",    "of",          "int",  False),
    ("Disc Number",    "Disc",        "int",  False),
    ("Disc Count",     "Discs",       "int",  False),
    ("Rating",         "Rating",      "star", False),
    ("Album Rating",   "Album Rating", "star", False),
    ("BPM",            "BPM",         "int",  False),
    ("Bit Rate",       "Bit Rate",    "kbps", False),
    ("Sample Rate",    "Sample Rate", "khz",  False),
    ("Comments",       "Comments",    "text", False),
    ("Compilation",    "Compilation", "bool", False),
    ("Date Added",     "Date Added",  "date", False),
    ("Date Modified",  "Date Modified", "date", False),
    ("Play Date UTC",  "Last Played", "date", False),
    ("Skip Count",     "Skips",       "int",  False),
    ("Skip Date",      "Last Skipped", "date", False),
]

AUDIO = {".mp3", ".m4a", ".wav", ".mp4", ".aif", ".aiff",
         ".mpga", ".m4b", ".flac", ".ogg", ".mov", ".m4v"}


def index_by_name(root):
    index = defaultdict(list)
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            if os.path.splitext(name)[1].lower() in AUDIO:
                index[name.lower()].append(os.path.join(dirpath, name))
    return index


def build_data(out_dir):
    with open(LIBRARY, "rb") as fh:
        lib = plistlib.load(fh)
    tracks = lib["Tracks"]
    index = index_by_name(LOCAL_ROOT)

    pool, paths, seen = [], [], {}
    playlists, missing = [], 0

    def cell(track, key, kind):
        v = track.get(key)
        if v is None:
            return "" if kind in ("text", "date") else 0
        if kind == "time":
            return round(v / 1000)
        if kind == "date":
            return v.strftime("%Y-%m-%d")      # plist datetime -> sortable string
        if kind == "bool":
            return 1 if v else 0
        return v

    def track_index(track, path, how):
        """Intern a track into the shared pool; playlists store only offsets."""
        key = track["Track ID"]
        if key not in seen:
            seen[key] = len(pool)
            pool.append([cell(track, k, kind) for k, _, kind, _ in FIELDS] + [how])
            paths.append(path)          # None when the file could not be found
        return seen[key]

    for playlist in lib["Playlists"]:
        if "Smart Info" in playlist or playlist.get("Master") \
                or playlist.get("Distinguished Kind") or not playlist.get("Playlist Items"):
            continue
        ids = []
        for item in playlist["Playlist Items"]:
            track = tracks.get(str(item["Track ID"]))
            if not track or not track.get("Location"):
                continue
            path, how = locate(track, index)
            if not path:
                missing += 1
            ids.append(track_index(track, path, how))
        if ids:
            playlists.append({"name": playlist["Name"], "ids": ids})

    playlists.sort(key=lambda p: p["name"].lower())

    fields = [[label, kind, show] for _, label, kind, show in FIELDS]
    fields.append(["Found", "found", False])   # derived, not from the library
    data = {"fields": fields, "tracks": pool, "playlists": playlists}
    path = os.path.join(out_dir, "data.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))

    # Index-aligned with the track pool. Read by the server, never by the page,
    # so the browser can only ever ask for a row number, not a filesystem path.
    with open(os.path.join(out_dir, "paths.json"), "w", encoding="utf-8") as fh:
        json.dump(paths, fh, ensure_ascii=False, separators=(",", ":"))

    refs = sum(len(p["ids"]) for p in playlists)
    print(f"  {len(playlists)} playlists, {refs} track refs, "
          f"{len(pool)} unique tracks, {missing} shown as missing")
    print(f"  data.json {os.path.getsize(path) / 1e6:.1f} MB")
    return len(playlists), refs


# Every colour, shape and type value the page uses. The stylesheet is generated
# from these, so a skin cannot reference a token that does not exist, and cannot
# be offered without being defined.
BASE_TOKENS = {
    "--bar-a": "#8f9c82",
    "--bar-b": "#6f7c63",
    "--bar-line": "#949a8a",
    "--bar-track": "#b9bfae",
    "--bevel": "inset 0 1px 0 #fff,0 1px 2px rgba(0,0,0,.28)",
    "--bevel-in": "inset 0 2px 4px rgba(0,0,0,.3)",
    "--btn-a": "#fdfdfd",
    "--btn-b": "#d7d7d7",
    "--btn-ink": "#3c3c3c",
    "--btn-line": "#8d8d8d",
    "--btn-radius": "50%",
    "--chrome-a": "#e8e8e8",
    "--chrome-b": "#d0d0d0",
    "--chrome-ink": "#3a3a3a",
    "--chrome-line": "#a4a4a4",
    "--desk": "#6b6b6b",
    "--field-radius": "10px",
    "--font": "\"Lucida Grande\",\"Segoe UI\",Helvetica,Arial,sans-serif",
    "--gear-radius": "4px",
    "--grain": "repeating-linear-gradient(0deg,rgba(255,255,255,.55) 0 1px,rgba(0,0,0,.035) 1px 2px)",  # noqa: E501
    "--head-a": "#f0f0f0",
    "--head-b": "#dadada",
    "--head-div": "#c4c4c4",
    "--head-ink": "#333",
    "--head-line": "#9a9a9a",
    "--ink": "#000",
    "--lcd-a": "#d7dbcd",
    "--lcd-b": "#c9cebe",
    "--lcd-dim": "#4a5044",
    "--lcd-ink": "#20241c",
    "--lcd-line": "#8e9384",
    "--lcd-radius": "9px",
    "--lights": "flex",
    "--pane": "#fff",
    "--pane-inset": "inset 0 1px 3px rgba(0,0,0,.3)",
    "--radius": "7px",
    "--rowsel": "#b6c8de",
    "--scroll-a": "#c8d4e4",
    "--scroll-b": "#9db2cc",
    "--scroll-line": "#7f92aa",
    "--scroll-track": "#f0f0f0",
    "--sel": "#3a6ea5",
    "--sel-ink": "#fff",
    "--shadow": "0 12px 34px rgba(0,0,0,.45)",
    "--sorted-a": "#dfe7f2",
    "--sorted-b": "#c9d6e8",
    "--src-bg": "#fff",
    "--src-head-a": "#ededed",
    "--src-head-b": "#dcdcdc",
    "--src-head-ink": "#555",
    "--src-line": "#9a9a9a",
    "--stripe": "#edf3fb",
    "--title-bg": "var(--grain),linear-gradient(var(--chrome-a),var(--chrome-b))",
    "--title-h": "22px",
    "--title-ink": "#3a3a3a",
    "--title-just": "center",
    "--title-pad": "0",
    "--title-weight": "600",
    "--vlc-a": "#6f6f6f",
    "--vlc-b": "#3a3a3a",
    "--vlc-ink": "#f4f4f4",
    "--vlc-line": "#2f2f2f",
    "--vlc-shadow": "inset 0 1px 0 rgba(255,255,255,.28),0 1px 3px rgba(0,0,0,.4)",
    "--win-line": "#6f6f6f",
}


class Skin(NamedTuple):
    """One era. `tokens` overrides BASE_TOKENS; empty means it *is* the base."""

    id: str
    label: str
    era: str
    tokens: dict


SKINS = [
    # iTunes 1-4. Brushed metal over a soft grey. The default, and the only
    # skin that lives on :root -- it needs no attribute to be correct.
    Skin("greenwood", "Greenwood", "iTunes 1-4",
         {}),
    # iTunes 5-6. The metal grain dropped for flat grey; coastal fog.
    Skin("tofino", "Tofino", "iTunes 5-6",
         {
             "--bar-a": "#9aa09a",
             "--bar-b": "#7d827d",
             "--bar-line": "#a2a5a2",
             "--bar-track": "#c6c9c6",
             "--btn-a": "#fff",
             "--btn-b": "#e2e2e2",
             "--btn-line": "#a6a6a6",
             "--chrome-a": "#f4f4f4",
             "--chrome-b": "#dedede",
             "--chrome-ink": "#404040",
             "--chrome-line": "#b0b0b0",
             "--desk": "#7a7a7a",
             "--grain": "none",
             "--head-a": "#f7f7f7",
             "--head-b": "#e6e6e6",
             "--head-div": "#d6d6d6",
             "--head-line": "#b4b4b4",
             "--lcd-a": "#e4e6e4",
             "--lcd-b": "#d4d7d4",
             "--lcd-dim": "#5b5f5b",
             "--lcd-ink": "#2a2c2a",
             "--lcd-line": "#a6a9a6",
             "--rowsel": "#c3d1e0",
             "--scroll-a": "#d8d8d8",
             "--scroll-b": "#b4b4b4",
             "--scroll-line": "#a0a0a0",
             "--scroll-track": "#f6f6f6",
             "--sorted-a": "#e8eef6",
             "--sorted-b": "#d8e2ee",
             "--src-head-a": "#f4f4f4",
             "--src-head-b": "#e6e6e6",
             "--stripe": "#f1f4f8",
             "--win-line": "#8a8a8a",
         }),
    # iTunes 7-10. The blue sidebar era; lake water off the Kootenays.
    Skin("kaslo", "Kaslo", "iTunes 7-10",
         {
             "--bar-a": "#8497a8",
             "--bar-b": "#63788b",
             "--bar-line": "#93a0aa",
             "--bar-track": "#bcc5cd",
             "--btn-a": "#fff",
             "--btn-b": "#dbe1e7",
             "--btn-line": "#98a2ac",
             "--chrome-a": "#e2e6ea",
             "--chrome-b": "#c8cfd6",
             "--chrome-ink": "#333b44",
             "--chrome-line": "#9aa3ad",
             "--desk": "#5f6672",
             "--grain": "none",
             "--head-a": "#eef2f6",
             "--head-b": "#d9e0e8",
             "--head-div": "#c2ccd6",
             "--head-ink": "#2f3841",
             "--head-line": "#a2acb6",
             "--lcd-a": "#dfe4e8",
             "--lcd-b": "#ccd3da",
             "--lcd-dim": "#4d5761",
             "--lcd-ink": "#1e262e",
             "--lcd-line": "#8f9aa4",
             "--rowsel": "#b3c7de",
             "--scroll-a": "#c2d0e0",
             "--scroll-b": "#96a9be",
             "--scroll-line": "#7d90a5",
             "--scroll-track": "#e8edf2",
             "--sel": "#4a7fc1",
             "--sel-ink": "#fff",
             "--sorted-a": "#dde8f6",
             "--sorted-b": "#c4d6ec",
             "--src-bg": "#dfe6ee",
             "--src-head-a": "#e9eef4",
             "--src-head-b": "#d6dee7",
             "--src-head-ink": "#4a5560",
             "--src-line": "#a6b0bb",
             "--stripe": "#eaf0f8",
             "--win-line": "#69737e",
         }),
    # Windows 3.1. Teal desktop, solid navy title, centred, and the raised
    # grey bevel on everything. There is a real town called Concrete.
    Skin("concrete", "Concrete", "Windows 3.1",
         {
             "--bar-a": "#000080",
             "--bar-b": "#000080",
             "--bar-line": "#808080",
             "--bar-track": "#fff",
             "--bevel": "inset -1px -1px 0 #000,inset 1px 1px 0 #fff, inset -2px -2px 0 #808080,inset 2px 2px 0 #dfdfdf",  # noqa: E501
             "--bevel-in": "inset 1px 1px 0 #000,inset -1px -1px 0 #fff, inset 2px 2px 0 #808080,inset -2px -2px 0 #dfdfdf",  # noqa: E501
             "--btn-a": "#c0c0c0",
             "--btn-b": "#c0c0c0",
             "--btn-ink": "#000",
             "--btn-line": "#000",
             "--btn-radius": "0",
             "--chrome-a": "#c0c0c0",
             "--chrome-b": "#c0c0c0",
             "--chrome-ink": "#000",
             "--chrome-line": "#000",
             "--desk": "#008080",
             "--field-radius": "0",
             "--font": "\"MS Sans Serif\",Tahoma,Verdana,\"Liberation Sans\",\"DejaVu Sans\",sans-serif",  # noqa: E501
             "--gear-radius": "0",
             "--grain": "none",
             "--head-a": "#c0c0c0",
             "--head-b": "#c0c0c0",
             "--head-div": "#808080",
             "--head-ink": "#000",
             "--head-line": "#808080",
             "--lcd-a": "#c0c0c0",
             "--lcd-b": "#c0c0c0",
             "--lcd-dim": "#000",
             "--lcd-ink": "#000",
             "--lcd-line": "#808080",
             "--lcd-radius": "0",
             "--lights": "none",
             "--pane": "#fff",
             "--pane-inset": "inset 1px 1px 0 #808080,inset -1px -1px 0 #fff",
             "--radius": "0",
             "--rowsel": "#000080",
             "--scroll-a": "#c0c0c0",
             "--scroll-b": "#c0c0c0",
             "--scroll-line": "#000",
             "--scroll-track": "#dfdfdf",
             "--sel": "#000080",
             "--sel-ink": "#fff",
             "--shadow": "none",
             "--sorted-a": "#a0a0a0",
             "--sorted-b": "#a0a0a0",
             "--src-bg": "#fff",
             "--src-head-a": "#c0c0c0",
             "--src-head-b": "#c0c0c0",
             "--src-head-ink": "#000",
             "--src-line": "#808080",
             "--stripe": "#fff",
             "--title-bg": "linear-gradient(#000080,#000080)",
             "--title-h": "20px",
             "--title-ink": "#fff",
             "--title-just": "center",
             "--title-weight": "700",
             "--vlc-a": "#c0c0c0",
             "--vlc-b": "#c0c0c0",
             "--vlc-ink": "#000",
             "--vlc-line": "#000",
             "--vlc-shadow": "inset -1px -1px 0 #000,inset 1px 1px 0 #fff, inset -2px -2px 0 #808080,inset 2px 2px 0 #dfdfdf",  # noqa: E501
             "--win-line": "#000",
         }),
    # Windows 95. The gradient title bar, left-aligned. A real town, and the
    # only sensible name for the release that introduced the Start button.
    Skin("startup", "Startup", "Windows 95",
         {
             "--bar-a": "#000080",
             "--bar-b": "#1084d0",
             "--bar-line": "#808080",
             "--bar-track": "#fff",
             "--bevel": "inset -1px -1px 0 #000,inset 1px 1px 0 #fff, inset -2px -2px 0 #808080,inset 2px 2px 0 #dfdfdf",  # noqa: E501
             "--bevel-in": "inset 1px 1px 0 #000,inset -1px -1px 0 #fff, inset 2px 2px 0 #808080,inset -2px -2px 0 #dfdfdf",  # noqa: E501
             "--btn-a": "#c0c0c0",
             "--btn-b": "#c0c0c0",
             "--btn-ink": "#000",
             "--btn-line": "#000",
             "--btn-radius": "0",
             "--chrome-a": "#c0c0c0",
             "--chrome-b": "#c0c0c0",
             "--chrome-ink": "#000",
             "--chrome-line": "#808080",
             "--desk": "#008080",
             "--field-radius": "0",
             "--font": "\"MS Sans Serif\",Tahoma,Verdana,\"Liberation Sans\",\"DejaVu Sans\",sans-serif",  # noqa: E501
             "--gear-radius": "0",
             "--grain": "none",
             "--head-a": "#c0c0c0",
             "--head-b": "#c0c0c0",
             "--head-div": "#dfdfdf",
             "--head-ink": "#000",
             "--head-line": "#808080",
             "--lcd-a": "#c0c0c0",
             "--lcd-b": "#c0c0c0",
             "--lcd-dim": "#404040",
             "--lcd-ink": "#000",
             "--lcd-line": "#808080",
             "--lcd-radius": "0",
             "--lights": "none",
             "--pane": "#fff",
             "--pane-inset": "inset 1px 1px 0 #808080,inset -1px -1px 0 #fff",
             "--radius": "0",
             "--rowsel": "#000080",
             "--scroll-a": "#c0c0c0",
             "--scroll-b": "#c0c0c0",
             "--scroll-line": "#808080",
             "--scroll-track": "#dfdfdf",
             "--sel": "#000080",
             "--sel-ink": "#fff",
             "--shadow": "none",
             "--sorted-a": "#dfdfdf",
             "--sorted-b": "#c0c0c0",
             "--src-bg": "#fff",
             "--src-head-a": "#c0c0c0",
             "--src-head-b": "#c0c0c0",
             "--src-head-ink": "#000",
             "--src-line": "#808080",
             "--stripe": "#fff",
             "--title-bg": "linear-gradient(90deg,#000080,#1084d0)",
             "--title-h": "20px",
             "--title-ink": "#fff",
             "--title-just": "flex-start",
             "--title-pad": "0 6px",
             "--title-weight": "700",
             "--vlc-a": "#c0c0c0",
             "--vlc-b": "#c0c0c0",
             "--vlc-ink": "#000",
             "--vlc-line": "#000",
             "--vlc-shadow": "inset -1px -1px 0 #000,inset 1px 1px 0 #fff, inset -2px -2px 0 #808080,inset 2px 2px 0 #dfdfdf",  # noqa: E501
             "--win-line": "#000",
         }),
    # Windows XP Luna. Deep lake blue and the beige workspace that came with
    # it. Rounded again, but only at the top.
    Skin("chelan", "Chelan", "Windows XP",
         {
             "--bar-a": "#4f9d3a",
             "--bar-b": "#2f7a20",
             "--bar-line": "#aca899",
             "--bar-track": "#e6e3d4",
             "--bevel": "inset 0 1px 0 rgba(255,255,255,.9),0 1px 2px rgba(0,0,0,.25)",
             "--bevel-in": "inset 0 2px 4px rgba(0,0,0,.28)",
             "--btn-a": "#fdfdfb",
             "--btn-b": "#e8e5d6",
             "--btn-ink": "#22314a",
             "--btn-line": "#a9a596",
             "--btn-radius": "4px",
             "--chrome-a": "#f6f4ec",
             "--chrome-b": "#ece9d8",
             "--chrome-ink": "#22314a",
             "--chrome-line": "#aca899",
             "--desk": "linear-gradient(#4a7ec4,#7aa8dc) fixed",
             "--field-radius": "3px",
             "--font": "Tahoma,\"Segoe UI\",Verdana,\"Liberation Sans\",\"DejaVu Sans\",sans-serif",
             "--gear-radius": "3px",
             "--grain": "none",
             "--head-a": "#fbfaf6",
             "--head-b": "#e8e5d6",
             "--head-div": "#d4d0c0",
             "--head-ink": "#22314a",
             "--head-line": "#aca899",
             "--lcd-a": "#fbfaf6",
             "--lcd-b": "#ece9d8",
             "--lcd-dim": "#5a6478",
             "--lcd-ink": "#1b2740",
             "--lcd-line": "#aca899",
             "--lcd-radius": "3px",
             "--lights": "none",
             "--pane": "#fff",
             "--pane-inset": "inset 0 1px 3px rgba(0,0,0,.22)",
             "--radius": "8px 8px 0 0",
             "--rowsel": "#c1d7f5",
             "--scroll-a": "#dfeaf8",
             "--scroll-b": "#9dbbe4",
             "--scroll-line": "#7f9ec9",
             "--scroll-track": "#f1efe4",
             "--sel": "#316ac5",
             "--sel-ink": "#fff",
             "--shadow": "0 10px 30px rgba(0,0,0,.4)",
             "--sorted-a": "#dbe6f8",
             "--sorted-b": "#bed3f2",
             "--src-bg": "#eef3fb",
             "--src-head-a": "#f6f4ec",
             "--src-head-b": "#e4e0cf",
             "--src-head-ink": "#3b4a63",
             "--src-line": "#a7b6cc",
             "--stripe": "#f3f6fc",
             "--title-bg": "linear-gradient(#0a55d4,#3a86e8 8%,#2c76dc 40%,#1a5fd0)",
             "--title-h": "26px",
             "--title-ink": "#fff",
             "--title-just": "flex-start",
             "--title-pad": "0 10px",
             "--title-weight": "700",
             "--vlc-a": "#5b9bd5",
             "--vlc-b": "#2a6db5",
             "--vlc-ink": "#fff",
             "--vlc-line": "#1c4f8a",
             "--vlc-shadow": "inset 0 1px 0 rgba(255,255,255,.5),0 1px 2px rgba(0,0,0,.3)",
             "--win-line": "#0a3f9c",
         }),
    # The Windows 3.1 Hot Dog Stand scheme nobody chose on purpose. Structure
    # taken from a real Program Manager screenshot; the colour goes further
    # than the 16-colour palette could, which is the trade.
    Skin("boring", "Boring", "Hot Dog Stand",
         {
             "--bar-a": "#ffee00",
             "--bar-b": "#ffa000",
             "--bar-line": "#4d0000",
             "--bar-track": "#8b0000",
             "--bevel": "inset -1px -1px 0 #800000,inset 1px 1px 0 #ffff99, inset -2px -2px 0 #b30000,inset 2px 2px 0 #ffee55",  # noqa: E501
             "--bevel-in": "inset 1px 1px 0 #800000,inset -1px -1px 0 #ffff99",
             "--btn-a": "#ffee44",
             "--btn-b": "#ffab00",
             "--btn-ink": "#8b0000",
             "--btn-line": "#800000",
             "--btn-radius": "0",
             "--chrome-a": "#ff2a12",
             "--chrome-b": "#d40000",
             "--chrome-ink": "#ffee00",
             "--chrome-line": "#800000",
             "--desk": "linear-gradient(#ff2a00,#cc0000)",
             "--field-radius": "0",
             "--font": "\"MS Sans Serif\",Tahoma,Verdana,\"Liberation Sans\",\"DejaVu Sans\",sans-serif",  # noqa: E501
             "--gear-radius": "0",
             "--grain": "none",
             "--head-a": "#ff3a18",
             "--head-b": "#c40000",
             "--head-div": "#ff7a55",
             "--head-ink": "#ffee00",
             "--head-line": "#800000",
             "--ink": "#1a0000",
             "--lcd-a": "#ffff44",
             "--lcd-b": "#ffcc00",
             "--lcd-dim": "#b32400",
             "--lcd-ink": "#8b0000",
             "--lcd-line": "#800000",
             "--lcd-radius": "0",
             "--lights": "none",
             "--pane": "linear-gradient(#ffff33,#ffe97a)",
             "--pane-inset": "inset 0 1px 3px rgba(128,0,0,.55)",
             "--radius": "0",
             "--rowsel": "#c00000",
             "--scroll-a": "#ff3a18",
             "--scroll-b": "#aa0000",
             "--scroll-line": "#800000",
             "--scroll-track": "#ffd700",
             "--sel": "#c00000",
             "--sel-ink": "#ffff00",
             "--shadow": "0 6px 20px rgba(90,0,0,.55)",
             "--sorted-a": "#ffcc00",
             "--sorted-b": "#ff8c00",
             "--src-bg": "linear-gradient(#ffd700,#ffb300)",
             "--src-head-a": "#ff4422",
             "--src-head-b": "#c40000",
             "--src-head-ink": "#ffff00",
             "--src-line": "#800000",
             "--stripe": "#fff08a",
             "--title-bg": "linear-gradient(#ff4422,#e00000 45%,#c00000)",
             "--title-h": "20px",
             "--title-ink": "#ffff00",
             "--title-just": "center",
             "--title-weight": "700",
             "--vlc-a": "#ff5522",
             "--vlc-b": "#c00000",
             "--vlc-ink": "#ffff00",
             "--vlc-line": "#5a0000",
             "--vlc-shadow": "inset 0 1px 0 #ffbb88,0 1px 3px rgba(90,0,0,.6)",
             "--win-line": "#5a0000",
         }),
    # Not an operating system at all, but a 2006 band profile: MySpace blue
    # buried under whatever the layout generator produced.
    Skin("azalea", "Azalea", "MySpace 2006",
         {
             "--bar-a": "#00ff66",
             "--bar-b": "#ffee00",
             "--bar-line": "#ff00cc",
             "--bar-track": "#12001f",
             "--bevel": "inset 0 0 0 1px #00e5ff,0 0 8px #ff00cc",
             "--bevel-in": "inset 0 0 10px #ff00cc",
             "--btn-a": "#ff00cc",
             "--btn-b": "#7a00ff",
             "--btn-ink": "#ffee00",
             "--btn-line": "#00e5ff",
             "--btn-radius": "0",
             "--chrome-a": "#1a0033",
             "--chrome-b": "#4b0082",
             "--chrome-ink": "#00ff66",
             "--chrome-line": "#ff00cc",
             "--desk": "linear-gradient(135deg,#ff00cc 0%,#7a00ff 25%,#00e5ff 50%,#7a00ff 75%,#ff00cc 100%) fixed",  # noqa: E501
             "--field-radius": "0",
             "--font": "\"Comic Sans MS\",\"Chalkboard SE\",\"Comic Neue\",cursive,sans-serif",
             "--gear-radius": "0",
             "--grain": "none",
             "--head-a": "#ffee00",
             "--head-b": "#ff8800",
             "--head-div": "#ff00cc",
             "--head-ink": "#4b0082",
             "--head-line": "#ff00cc",
             "--ink": "#ffffff",
             "--lcd-a": "#2a003f",
             "--lcd-b": "#00223f",
             "--lcd-dim": "#00ff66",
             "--lcd-ink": "#ffee00",
             "--lcd-line": "#00e5ff",
             "--lcd-radius": "0",
             "--lights": "none",
             "--pane": "linear-gradient(180deg,#12001f,#2a003f 40%,#12001f)",
             "--pane-inset": "inset 0 0 14px rgba(255,0,204,.75)",
             "--radius": "0",
             "--rowsel": "#00ff66",
             "--scroll-a": "#ff00cc",
             "--scroll-b": "#00e5ff",
             "--scroll-line": "#ffee00",
             "--scroll-track": "#1a0033",
             "--sel": "#00ff66",
             "--sel-ink": "#1a0033",
             "--shadow": "0 0 40px #ff00cc,0 0 90px #7a00ff",
             "--sorted-a": "#00e5ff",
             "--sorted-b": "#00ff66",
             "--src-bg": "linear-gradient(180deg,#4b0082,#ff00cc 50%,#4b0082)",
             "--src-head-a": "#ffee00",
             "--src-head-b": "#ff8800",
             "--src-head-ink": "#4b0082",
             "--src-line": "#00e5ff",
             "--stripe": "rgba(255,0,204,.22)",
             "--title-bg": "linear-gradient(90deg,#ff00cc,#ffee00 20%,#00ff66 40%,#00e5ff 60%,#7a00ff 80%,#ff00cc)",  # noqa: E501
             "--title-h": "24px",
             "--title-ink": "#000",
             "--title-just": "center",
             "--title-weight": "700",
             "--vlc-a": "#00ff66",
             "--vlc-b": "#00a3ff",
             "--vlc-ink": "#1a0033",
             "--vlc-line": "#ff00cc",
             "--vlc-shadow": "0 0 10px #00ff66",
             "--win-line": "#00e5ff",
         }),
]


# One button, three states, in iTunes' order.
REPEAT_CYCLE = {"off": "all", "all": "one", "one": "off"}


def render_skins():
    """BASE_TOKENS becomes :root; each skin with overrides becomes a block."""
    out = [":root{" + "".join(f"{k}:{v};" for k, v in BASE_TOKENS.items()) + "}"]
    for skin in SKINS:
        if not skin.tokens:
            continue
        decls = "".join(f"{k}:{v};" for k, v in skin.tokens.items())
        out.append(f'[data-skin="{skin.id}"]{{{decls}}}')
    return "\n".join(out)


LAYOUT_CSS = r"""
/* ---- Layout ---------------------------------------------------------- */
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{background:var(--desk);font:11px/1.35 var(--font);
     color:var(--ink);display:flex;align-items:center;justify-content:center;padding:14px;
     -webkit-font-smoothing:antialiased}

.metal{background-image:var(--grain),linear-gradient(var(--chrome-a),var(--chrome-b))}

.win{width:100%;height:100%;min-width:0;min-height:0;display:flex;flex-direction:column;
     border:1px solid var(--win-line);border-radius:var(--radius);overflow:hidden;
     box-shadow:var(--shadow)}

.title{height:var(--title-h);flex:none;display:flex;align-items:center;
       justify-content:var(--title-just);padding:var(--title-pad);
       background-image:var(--title-bg);
       border-bottom:1px solid var(--chrome-line);font-weight:var(--title-weight);
       color:var(--title-ink);font-size:12px;position:relative}
.lights{position:absolute;left:8px;display:var(--lights);gap:6px}
.lights i{width:11px;height:11px;border-radius:50%;display:block;border:1px solid rgba(0,0,0,.35)}
.lights i:nth-child(1){background:radial-gradient(circle at 35% 30%,#ff9a90,#e04f43)}
.lights i:nth-child(2){background:radial-gradient(circle at 35% 30%,#ffd479,#e0a234)}
.lights i:nth-child(3){background:radial-gradient(circle at 35% 30%,#a8e57f,#4fa42f)}

.transport{flex:none;display:flex;align-items:center;gap:7px}
.tbtn{width:29px;height:29px;border-radius:var(--btn-radius);
  border:1px solid var(--btn-line);cursor:pointer;
  display:flex;align-items:center;justify-content:center;padding:0;
  background:linear-gradient(var(--btn-a),var(--btn-b));box-shadow:var(--bevel)}
.tbtn.big{width:39px;height:39px}
.tbtn:hover{filter:brightness(1.06)}
.tbtn:active{filter:brightness(.9);box-shadow:var(--bevel-in)}
.tbtn:disabled{opacity:.4;cursor:default}
.tbtn svg{fill:var(--btn-ink);pointer-events:none}
.vol{width:74px;margin-left:4px;accent-color:var(--btn-ink)}

.bar{width:88%;height:7px;border-radius:4px;background:var(--bar-track);cursor:pointer;
  border:1px solid var(--bar-line);box-shadow:inset 0 1px 2px rgba(0,0,0,.25);position:relative}
.bar span{display:block;height:100%;border-radius:3px 0 0 3px;
  background:linear-gradient(var(--bar-a),var(--bar-b))}
.times{display:flex;justify-content:space-between;width:88%;font-size:9.5px;
  color:var(--lcd-dim);font-variant-numeric:tabular-nums}
.row.playing{font-weight:600}
.row.playing .c-name::before{content:"\25B6";font-size:8px;margin-right:5px;color:var(--sel)}

.playbtn{flex:none;display:flex;align-items:center;gap:8px;height:30px;
  padding:0 14px 0 11px;border-radius:var(--field-radius);cursor:pointer;font-size:11px;
  border:1px solid var(--vlc-line);color:var(--vlc-ink);font:600 12px var(--font);
  background:linear-gradient(var(--vlc-a),var(--vlc-b));
  text-shadow:0 -1px 0 rgba(0,0,0,.25);box-shadow:var(--vlc-shadow)}
.playbtn:hover{filter:brightness(1.1)}
.playbtn:active{filter:brightness(.85);box-shadow:var(--bevel-in)}
.playbtn:disabled{opacity:.45;cursor:default}
.playbtn svg{flex:none;fill:var(--vlc-ink)}

.top{flex:none;display:flex;align-items:center;gap:14px;padding:9px 12px;
     flex-wrap:wrap;
     border-bottom:1px solid var(--chrome-line)}
.lcd{flex:1 1 220px;min-width:0;height:66px;border-radius:var(--lcd-radius);
     background:linear-gradient(var(--lcd-a),var(--lcd-b));
     border:1px solid var(--lcd-line);box-shadow:var(--pane-inset);
     display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;
     text-shadow:0 1px 0 rgba(255,255,255,.4);overflow:hidden;padding:0 12px}
#lcdName{font-weight:600;font-size:12px;color:var(--lcd-ink);white-space:nowrap;
         overflow:hidden;text-overflow:ellipsis;max-width:100%}
#lcdSub{font-size:10px;color:var(--lcd-dim);font-variant-numeric:tabular-nums}
.searchwrap{flex:none;display:flex;flex-direction:column;align-items:flex-end;gap:5px}
#search{width:min(190px,38vw);height:20px;border-radius:var(--field-radius);
        border:1px solid var(--lcd-line);color:var(--ink);padding:0 22px 0 22px;
        font:11px "Lucida Grande",sans-serif;background:#fff url("data:image/svg+xml;charset=utf8,\
%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Cg fill='none' stroke='%23888' \
stroke-width='1.6'%3E%3Ccircle cx='7' cy='7' r='4'/%3E\
%3Cpath d='M10 10l3.5 3.5'/%3E%3C/g%3E%3C/svg%3E") \
6px 50%/11px no-repeat;box-shadow:inset 0 1px 2px rgba(0,0,0,.18)}
#search:focus{outline:2px solid #7ba7e0;outline-offset:-1px}
#count{font-size:10px;color:var(--chrome-ink);font-variant-numeric:tabular-nums}

.body{flex:1;display:flex;min-height:0;border-top:1px solid #fff}

.source{width:clamp(120px,16vw,220px);flex:none;background:var(--src-bg);
        border-right:1px solid var(--src-line);
        display:flex;flex-direction:column;min-height:0}
.srchead{flex:none;height:18px;display:flex;align-items:center;justify-content:center;
         font-size:10px;color:var(--src-head-ink);border-bottom:1px solid var(--head-div);
         background:linear-gradient(var(--src-head-a),var(--src-head-b))}
.srclist{flex:1;overflow-y:auto;padding:3px 0}
.src{display:flex;align-items:center;gap:5px;padding:2px 8px;cursor:default;
     white-space:nowrap;overflow:hidden}
.src span{overflow:hidden;text-overflow:ellipsis}
.src svg{flex:none}
.src.on{background:var(--sel);color:var(--sel-ink)}
.src.on svg{fill:var(--sel-ink)}

.tracks{flex:1;display:flex;flex-direction:column;min-height:0;min-width:0;
        background:var(--pane)}
.thead{position:sticky;top:0;z-index:2;display:flex;width:max-content;min-width:100%;
       background:linear-gradient(var(--head-a),var(--head-b));
       border-bottom:1px solid var(--head-line);font-size:10px;color:var(--head-ink)}
.thead div{padding:3px 6px;border-right:1px solid var(--head-div);cursor:default;
           white-space:nowrap;overflow:hidden;position:relative;user-select:none}
.thead div:hover{background:rgba(0,0,0,.05)}
.thead div.sorted{background:linear-gradient(var(--sorted-a),var(--sorted-b))}
.thead div.sorted::after{content:"";position:absolute;right:4px;top:50%;margin-top:-2px;
  border-left:3.5px solid transparent;border-right:3.5px solid transparent;
  border-top:4px solid #4a4a4a}
.thead div.sorted.asc::after{border-top:none;border-bottom:4px solid #4a4a4a}
.scroll{flex:1;overflow:auto}
.row{display:flex;height:17px;align-items:center;width:max-content;min-width:100%}
.row:nth-child(even){background:var(--stripe)}
.row.sel{background:var(--rowsel)}
.row.ghost{opacity:.55;font-style:italic}
.row.ghost.sel{opacity:.8}
.found-gone,.found-ambiguous{color:#b23b3b;font-style:normal}
.found-moved,.found-by-size{color:#8a6d1f;font-style:normal}
.row div{padding:0 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.num{text-align:right;font-variant-numeric:tabular-nums}

.col-text{width:148px;flex:none}
.col-time,.col-int,.col-kbps{width:56px;flex:none}
.col-size,.col-khz{width:76px;flex:none}
.col-date{width:88px;flex:none}
.col-star{width:64px;flex:none}
.col-bool{width:54px;flex:none}
.grow{flex:1 1 auto;width:300px;min-width:90px}
.last{padding-right:10px}
.star{color:#5a5a5a;letter-spacing:1px}

/* Floating panels: View Options on the headers, Preferences on the gear. */
.panel{position:fixed;z-index:20;background:#f2f2f2;border:1px solid #7a7a7a;border-radius:5px;
    box-shadow:0 6px 20px rgba(0,0,0,.35);padding:6px 0;max-height:70vh;overflow-y:auto;
    min-width:186px;display:none;color:#000}
.panel.open{display:block}
.panel h4{font-size:10px;color:#666;font-weight:400;padding:2px 12px 5px;
       border-bottom:1px solid #d6d6d6;margin-bottom:4px}
.panel h4:not(:first-child){margin-top:6px}
.panel label{display:flex;align-items:center;gap:7px;padding:2px 12px;cursor:default}
.panel label:hover{background:#3a6ea5;color:#fff}
.panel input{margin:0}
.panel .era{margin-left:auto;opacity:.6;font-size:9.5px;padding-left:14px}

.empty{padding:26px;color:#888;text-align:center}
.status{flex:none;height:22px;display:flex;align-items:center;justify-content:center;
        border-top:1px solid #fff;font-size:10px;color:var(--chrome-ink);
        text-shadow:0 1px 0 rgba(255,255,255,.5);position:relative}
.sbtn{width:17px;height:17px;border-radius:var(--gear-radius);
      border:1px solid var(--btn-line);
      background:linear-gradient(var(--btn-a),var(--btn-b));cursor:pointer;
      display:flex;align-items:center;justify-content:center;padding:0;position:relative}
.sbtn:hover{filter:brightness(1.06)}
.sbtn svg{fill:var(--btn-ink);pointer-events:none}
.sbtn.on{background:linear-gradient(var(--sel),var(--sel))}
.sbtn.on svg{fill:var(--sel-ink)}
.sbtn b{position:absolute;right:1px;bottom:0;font-size:7px;line-height:1;
        font-weight:700;color:var(--sel-ink);pointer-events:none}
.modes{position:absolute;left:6px;top:50%;transform:translateY(-50%);display:flex;gap:4px}
.gear{position:absolute;right:6px;top:50%;transform:translateY(-50%)}

::-webkit-scrollbar{width:13px}
::-webkit-scrollbar-track{background:var(--scroll-track);border-left:1px solid var(--head-div)}
::-webkit-scrollbar-thumb{background:linear-gradient(90deg,var(--scroll-a),var(--scroll-b));
  border:1px solid var(--scroll-line);border-radius:6px}
"""

FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E"
           "%3Cpath fill='%233a6ea5' d='M5 1v9.2A2.6 2.6 0 1 0 6.6 12.6V4.6H12V1z'/%3E%3C/svg%3E")

CSS = render_skins() + "\n" + LAYOUT_CSS

NOTE_SVG = ("<svg width='9' height='11' viewBox='0 0 9 11' fill='%233a6ea5'>"
            "<path d='M3 0v7.1A2 2 0 1 0 4 9V3h4V0z'/></svg>")

JS = r"""
const $=s=>document.querySelector(s);
let DATA=null,FIELDS=[],FOUND=-1,vis=[],cur=0,sortCol=-1,asc=true,rows=[],sel=-1;
// what is playing, as a pool index, plus the queue it came from
let nowIdx=-1,queue=[],qpos=-1,queueKey="";
let shuffleOn=false,repeatMode="off";      // off | all | one
const MODEKEY="playlists.modes";
const KEY="playlists.columns", SKINKEY="playlists.skin";

const mmss=s=>`${Math.floor(s/60)}:${String(s%60).padStart(2,"0")}`;
const songs=n=>`${n} ${n===1?"song":"songs"}`;
const mb=b=>b>=1073741824?(b/1073741824).toFixed(2)+" GB":(b/1048576).toFixed(1)+" MB";

// iTunes stored ratings 0-100; five stars is 100.
const stars=v=>v?"\u2605".repeat(Math.round(v/20)):"";
function fmt(v,kind,gone){
  if(gone&&(kind==="time"||kind==="size"))return "";
  if(v===""||v===0||v===null)return kind==="bool"?"":"";
  switch(kind){
    case "time":return mmss(v);
    case "size":return mb(v);
    case "star":return `<span class="star">${stars(v)}</span>`;
    case "kbps":return v+" kbps";
    case "khz":return (v/1000).toFixed(1)+" kHz";
    case "bool":return v?"Yes":"";
    case "found":return v==="direct"?""
      :`<span class="found-${v.replace(/ /g,"-")}">${esc(v)}</span>`;
    default:return esc(String(v));
  }
}
const RIGHT=new Set(["time","size","int","kbps","khz"]);
// locate() distinguishes why a track is unresolved; neither can be played
const GONE=new Set(["gone","ambiguous"]);
const missing=t=>GONE.has(t[FOUND]);
function span(sec){
  const h=sec/3600;
  if(h>=1)return h.toFixed(1)+" hours";
  return Math.round(sec/60)+" minutes";
}

function drawSources(){
  $("#srclist").innerHTML=DATA.playlists.map((p,i)=>
    `<div class="src${i===cur?" on":""}" data-i="${i}">${NOTE}<span>${esc(p.name)}</span></div>`
  ).join("");
}
const esc=s=>s.replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

function current(){
  const q=$("#search").value.trim().toLowerCase();
  let list=DATA.playlists[cur].ids.slice();
  if(q)list=list.filter(i=>{const t=DATA.tracks[i];
    return (t[0]+" "+t[2]+" "+t[3]).toLowerCase().includes(q);});
  if(sortCol>=0){
    list.sort((ia,ib)=>{
      const x=DATA.tracks[ia][sortCol],y=DATA.tracks[ib][sortCol];
      const r=typeof x==="number"&&typeof y==="number"?x-y
        :String(x).localeCompare(String(y),undefined,{sensitivity:"base",numeric:true});
      return asc?r:-r;
    });
  }
  return list;
}

function colClass(i,nth){
  const kind=FIELDS[i][1];
  return `col-${kind}`+(i===0?" grow c-name":"")+(nth===vis.length-1?" last":"")
        +(RIGHT.has(kind)?" num":"");
}

function draw(){
  rows=current();
  syncQueue();
  const total=DATA.playlists[cur].ids.length;
  $("#thead").innerHTML=vis.map((f,n)=>
    `<div class="${colClass(f,n)}${f===sortCol?" sorted"+(asc?" asc":""):""}" `+
    `data-c="${f}">${esc(FIELDS[f][0])}</div>`).join("");
  $("#rows").innerHTML=rows.length?rows.map((idx,i)=>{
    const t=DATA.tracks[idx], gone=missing(t);
    return `<div class="row${i===sel?" sel":""}${gone?" ghost":""}`+
      `${idx===nowIdx?" playing":""}" data-i="${i}">`+
      vis.map((f,n)=>
        `<div class="${colClass(f,n)}">${fmt(t[f],FIELDS[f][1],gone)}</div>`).join("")+
      `</div>`;}).join("")
    : `<div class="empty">Nothing matches.</div>`;

  const T=FIELDS.findIndex(f=>f[1]==="time"), S=FIELDS.findIndex(f=>f[1]==="size");
  const here=rows.filter(i=>!missing(DATA.tracks[i]));
  const gone=rows.length-here.length;
  const secs=here.reduce((a,i)=>a+DATA.tracks[i][T],0),
        bytes=here.reduce((a,i)=>a+DATA.tracks[i][S],0);
  $("#status").textContent=rows.length
    ? songs(here.length)+`, ${span(secs)}, ${mb(bytes)}`
      +(gone?`   \u00b7   ${gone} missing`:"")
    : "no songs";
  $("#count").textContent=rows.length===total?songs(total):`${rows.length} of ${total}`;
  $("#lcdName").textContent=nowIdx>=0
    ? label(DATA.tracks[nowIdx]) : DATA.playlists[cur].name;
  $("#play").disabled=!here.length;   // nothing playable, even if rows show
  // the LCD covers the whole playlist, so it counts what is actually there
  const all=DATA.playlists[cur].ids, playable=all.filter(i=>!missing(DATA.tracks[i]));
  const absent=all.length-playable.length;
  $("#lcdSub").textContent=songs(playable.length)
    +` — ${span(playable.reduce((a,i)=>a+DATA.tracks[i][T],0))}`
    +(absent?`   \u00b7   ${absent} missing`:"");
}

function saveCols(){try{localStorage.setItem(KEY,JSON.stringify(vis));}catch(e){}}
function loadCols(){
  try{
    const v=JSON.parse(localStorage.getItem(KEY));
    if(Array.isArray(v)&&v.length&&v.every(i=>Number.isInteger(i)&&FIELDS[i]))return v;
  }catch(e){}
  return FIELDS.map((f,i)=>f[2]?i:-1).filter(i=>i>=0);
}

function loadModes(){
  try{
    const m=JSON.parse(localStorage.getItem(MODEKEY));
    if(m&&typeof m==="object"){
      shuffleOn=!!m.shuffle;
      if(["off","all","one"].includes(m.repeat))repeatMode=m.repeat;
    }
  }catch(e){}
}

function saveModes(){
  try{localStorage.setItem(MODEKEY,JSON.stringify(
    {shuffle:shuffleOn,repeat:repeatMode}));}catch(e){}
}

function paintModes(){
  $("#shuffle").classList.toggle("on",shuffleOn);
  $("#shuffle").title=shuffleOn?"Shuffle on":"Shuffle";
  $("#repeat").classList.toggle("on",repeatMode!=="off");
  $("#repeatBadge").textContent=repeatMode==="one"?"1":"";
  $("#repeat").title="Repeat "+repeatMode;
  audio.loop=(repeatMode==="one");
}

function skinName(){
  try{
    const v=localStorage.getItem(SKINKEY);
    if(SKINS.some(k=>k[0]===v))return v;
  }catch(e){}
  return SKINS[0][0];
}

function applySkin(name){
  // Greenwood is the base stylesheet, so it carries no attribute at all
  if(name===SKINS[0][0])document.documentElement.removeAttribute("data-skin");
  else document.documentElement.setAttribute("data-skin",name);
  try{localStorage.setItem(SKINKEY,name);}catch(e){}
}

function buildPrefs(){
  const now=skinName();
  $("#prefs").innerHTML="<h4>Appearance</h4>"+SKINS.map(([id,label,era])=>
    `<label><input type="radio" name="skin" value="${id}"${id===now?" checked":""}>`+
    `${esc(label)}<span class="era">${esc(era)}</span></label>`).join("");
}

function buildOptions(){
  $("#vo").innerHTML="<h4>View Options</h4>"+FIELDS.map((f,i)=>
    `<label><input type="checkbox" data-f="${i}"${vis.includes(i)?" checked":""}`+
    `${i===0?" disabled":""}> ${esc(f[0])}</label>`).join("");
}

const audio=$("#audio");
const clock=s=>isFinite(s)?`${Math.floor(s/60)}:${String(Math.floor(s%60)).padStart(2,"0")}`:"";

function label(t){
  const artist=t[2]||t[8];
  return artist?`${t[0]} — ${artist}`:t[0];
}

function shuffled(list,first){
  const out=list.slice();
  for(let i=out.length-1;i>0;i--){            // Fisher-Yates
    const j=Math.floor(Math.random()*(i+1));
    [out[i],out[j]]=[out[j],out[i]];
  }
  // whatever is playing stays put; only what comes after is reordered
  if(first!==undefined){
    const at=out.indexOf(first);
    if(at>0)[out[0],out[at]]=[out[at],out[0]];
  }
  return out;
}

/* The queue is the visible rows. Rebuild it only when that *set* changes --
   selecting a row or retyping the same search must not reshuffle underfoot. */
function syncQueue(force){
  const playable=rows.filter(i=>!missing(DATA.tracks[i]));
  const key=playable.join(",");
  if(!force&&key===queueKey)return;
  queueKey=key;
  queue=shuffleOn?shuffled(playable,nowIdx>=0?nowIdx:undefined):playable;
  qpos=queue.indexOf(nowIdx);
}

function play(poolIndex){
  const t=DATA.tracks[poolIndex];
  if(missing(t))return;
  nowIdx=poolIndex;
  syncQueue(true);
  qpos=queue.indexOf(poolIndex);
  audio.loop=(repeatMode==="one");
  audio.src="audio?i="+poolIndex;
  audio.play().catch(()=>{ lcd(`Cannot play ${t[0]}`); });
  draw();
}

function step(by){
  if(!queue.length)return;
  let at=qpos+by;
  if(at>=queue.length){
    if(repeatMode!=="all"){stop();return;}
    at=0;
  }else if(at<0){
    if(repeatMode!=="all"){stop();return;}
    at=queue.length-1;
  }
  play(queue[at]);
}

function stop(){
  audio.pause(); audio.removeAttribute("src"); audio.load();
  nowIdx=-1; qpos=-1; paint(); draw();
}

function lcd(msg){ $("#lcdName").textContent=msg; }

function paint(){
  const on=nowIdx>=0&&!audio.paused;
  $("#toggleIcon").innerHTML=on
    ? '<path d="M2 1h3.5v12H2zM7.5 1H11v12H7.5z"/>'
    : '<path d="M2 1v12l9.5-6z"/>';
  $("#toggle").title=on?"Pause":"Play";
  const d=audio.duration||0, c=audio.currentTime||0;
  $("#barFill").style.width=d?`${100*c/d}%`:"0";
  $("#elapsed").textContent=nowIdx>=0?clock(c):"";
  $("#left").textContent=nowIdx>=0&&d?"-"+clock(d-c):"";
  $("#prev").disabled=$("#next").disabled=nowIdx<0;
}

function boot(){
  FIELDS=DATA.fields; FOUND=FIELDS.length-1; vis=loadCols();
  applySkin(skinName()); buildPrefs(); loadModes(); paintModes();
  drawSources();buildOptions();draw();paint();

  $("#srclist").onclick=e=>{const el=e.target.closest(".src");if(!el)return;
    cur=+el.dataset.i;sel=-1;$("#search").value="";
    drawSources();draw();$("#scroll").scrollTop=0;};
  $("#thead").onclick=e=>{const el=e.target.closest("div[data-c]");if(!el)return;
    const c=+el.dataset.c; asc=(c===sortCol)?!asc:true; sortCol=c; sel=-1; draw();};
  $("#rows").onclick=e=>{const el=e.target.closest(".row");if(!el)return;
    sel=+el.dataset.i;draw();};
  $("#rows").ondblclick=e=>{const el=e.target.closest(".row");if(!el)return;
    play(rows[+el.dataset.i]);};

  $("#toggle").onclick=()=>{
    if(nowIdx<0){                       // nothing cued: start at the selection
      const start=sel>=0?rows[sel]:rows.find(i=>!missing(DATA.tracks[i]));
      if(start!==undefined)play(start);
      return;
    }
    audio.paused?audio.play():audio.pause();
  };
  $("#prev").onclick=()=>step(-1);
  $("#next").onclick=()=>step(1);
  $("#vol").oninput=e=>{audio.volume=+e.target.value;};

  $("#shuffle").onclick=()=>{
    shuffleOn=!shuffleOn;
    syncQueue(true);                     // reshuffle, as iTunes did on each toggle
    saveModes(); paintModes(); draw();
  };
  $("#repeat").onclick=()=>{
    repeatMode=REPEAT[repeatMode];
    saveModes(); paintModes();
  };

  $("#bar").onclick=e=>{
    if(!audio.duration)return;
    const r=$("#bar").getBoundingClientRect();
    audio.currentTime=audio.duration*Math.min(1,Math.max(0,(e.clientX-r.left)/r.width));
  };

  audio.addEventListener("timeupdate",paint);
  audio.addEventListener("play",paint);
  audio.addEventListener("pause",paint);
  audio.addEventListener("loadedmetadata",paint);
  audio.addEventListener("ended",()=>step(1));
  audio.addEventListener("error",()=>{
    const t=DATA.tracks[nowIdx];
    lcd(t?`Cannot play ${t[0]}`:"Playback failed");
  });
  $("#search").oninput=()=>{sel=-1;draw();};

  $("#play").onclick=async()=>{
    const pl=DATA.playlists[cur], btn=$("#play"), label=$("#playLabel");
    if(!rows.length)return;
    btn.disabled=true; label.textContent="Opening\u2026";
    let msg="Play in VLC";
    try{
      const r=await fetch("play",{method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({name:pl.name,
          indices:rows.filter(i=>!missing(DATA.tracks[i]))})});
      if(!r.ok)msg=(await r.json()).error||"Failed";
    }catch(e){ msg="Server not running"; }
    label.textContent=msg==="Play in VLC"?"Playing\u2026":msg;
    setTimeout(()=>{label.textContent="Play in VLC";btn.disabled=false;},1800);
  };

  // right-click the headers for the column picker, as iTunes did
  const openPanel=(el,x,y)=>{
    document.querySelectorAll(".panel").forEach(p=>p.classList.remove("open"));
    el.style.left=Math.min(x,innerWidth-210)+"px";
    el.style.top=Math.min(y,innerHeight-el.scrollHeight-12)+"px";
    el.classList.add("open");
  };
  $("#thead").oncontextmenu=e=>{e.preventDefault();openPanel($("#vo"),e.clientX,e.clientY);};
  $("#gear").onclick=e=>{
    e.stopPropagation();
    const r=$("#gear").getBoundingClientRect();
    openPanel($("#prefs"),r.right-200,r.top-$("#prefs").scrollHeight-8);
  };
  $("#prefs").onchange=e=>{ applySkin(e.target.value); };
  $("#vo").onchange=e=>{
    const i=+e.target.dataset.f;
    vis = e.target.checked ? FIELDS.map((_,n)=>n).filter(n=>n===i||vis.includes(n))
                           : vis.filter(n=>n!==i);
    if(!vis.includes(sortCol))sortCol=-1;
    saveCols();draw();
  };
  document.addEventListener("mousedown",e=>{
    if(e.target.closest(".panel")||e.target.closest("#thead")||e.target.closest("#gear"))return;
    document.querySelectorAll(".panel").forEach(p=>p.classList.remove("open"));
  });
}

fetch("data.json").then(r=>r.json()).then(d=>{DATA=d;boot();});
"""


def write_page(out_dir, n_playlists, n_refs):
    skins_json = json.dumps([[s.id, s.label, s.era] for s in SKINS])
    repeat_json = json.dumps(REPEAT_CYCLE)
    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Playlists</title>
<link rel="icon" href="{FAVICON}"><style>{CSS}</style></head>
<body>
<div class="win metal">
  <div class="title metal"><div class="lights"><i></i><i></i><i></i></div>Playlists</div>
  <div class="top metal">
    <div class="transport">
      <button class="tbtn" id="prev" title="Previous">
        <svg width="11" height="11" viewBox="0 0 11 11">
          <path d="M2 1h1.6v9H2zM10 1v9L4 5.5z"/></svg>
      </button>
      <button class="tbtn big" id="toggle" title="Play">
        <svg id="toggleIcon" width="13" height="14" viewBox="0 0 13 14">
          <path d="M2 1v12l9.5-6z"/></svg>
      </button>
      <button class="tbtn" id="next" title="Next">
        <svg width="11" height="11" viewBox="0 0 11 11">
          <path d="M7.4 1H9v9H7.4zM1 1l6 4.5L1 10z"/></svg>
      </button>
      <input class="vol" id="vol" type="range" min="0" max="1" step="0.01" value="1"
             title="Volume">
    </div>
    <div class="lcd">
      <div id="lcdName">&nbsp;</div>
      <div id="lcdSub">&nbsp;</div>
      <div class="bar" id="bar"><span id="barFill" style="width:0"></span></div>
      <div class="times"><span id="elapsed"></span><span id="left"></span></div>
    </div>
    <div class="searchwrap">
      <button class="playbtn" id="play" title="Open this view in VLC instead">
        <svg width="11" height="12" viewBox="0 0 15 16" aria-hidden="true">
          <path d="M2 1.4v13.2L13.2 8z"/></svg>
        <span id="playLabel">Play in VLC</span>
      </button>
      <input id="search" type="search" placeholder="Search" autocomplete="off">
      <div id="count"></div>
    </div>
  </div>
  <audio id="audio" preload="none"></audio>
  <div class="body">
    <div class="source">
      <div class="srchead">Source</div>
      <div class="srclist" id="srclist"></div>
    </div>
    <div class="tracks">
      <div class="scroll" id="scroll">
        <div class="thead" id="thead"></div>
        <div id="rows"></div>
      </div>
    </div>
  </div>
  <div class="status metal">
    <div class="modes">
      <button class="sbtn" id="shuffle" title="Shuffle">
        <svg width="11" height="11" viewBox="0 0 12 12"><path d="M0 2h2.2l1.6 2.1-1 1.4L1.6
          3.6H0zM8.4 2 7 .8 7 2H5.6L0 9.3v.7h2.2L7 4.1v1.2l1.4-1.2 1.4-1.1zM8.4 6.7 7 5.5v1.2
          L5.6 8.5 4.5 7l-.9 1.2 1.4 1.8H7v1.2l1.4-1.2 1.4-1.1z"/></svg>
      </button>
      <button class="sbtn" id="repeat" title="Repeat off">
        <svg width="11" height="11" viewBox="0 0 12 12"><path d="M2.6 3.4h6V5l2.4-2.1L8.6.8v1.4
          H1.4v3.3h1.2zM9.4 8.6h-6V7L1 9.1l2.4 2.1V9.8h7.2V6.5H9.4z"/></svg>
        <b id="repeatBadge"></b>
      </button>
    </div>
    <span id="status"></span>
    <button class="sbtn gear" id="gear" title="Preferences">
      <svg width="11" height="11" viewBox="0 0 16 16"><path d="M8 5.2A2.8 2.8 0 1 0 8
        10.8 2.8 2.8 0 0 0 8 5.2zm0 4.3a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zM14 8.9v-1.8l-1.6-.3a4.6
        4.6 0 0 0-.5-1.2l.9-1.3-1.3-1.3-1.3.9a4.6 4.6 0 0 0-1.2-.5L8.9 2H7.1l-.3 1.6a4.6 4.6 0 0
        0-1.2.5l-1.3-.9-1.3 1.3.9 1.3a4.6 4.6 0 0 0-.5 1.2L2 7.1v1.8l1.6.3c.1.4.3.8.5 1.2l-.9
        1.3 1.3 1.3 1.3-.9c.4.2.8.4 1.2.5l.3 1.6h1.8l.3-1.6c.4-.1.8-.3
        1.2-.5l1.3.9 1.3-1.3-.9-1.3c.2-.4.4-.8.5-1.2L14 8.9z"/></svg>
    </button>
  </div>
</div>
<div class="panel" id="vo"></div>
<div class="panel" id="prefs"></div>
<script>
const NOTE="{NOTE_SVG}";
const SKINS={skins_json};
const REPEAT={repeat_json};
</script>
<script>{JS}</script>
</body></html>"""
    path = os.path.join(out_dir, "index.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    print(f"  index.html {os.path.getsize(path) / 1024:.0f} KB "
          f"({n_playlists} playlists, {n_refs} refs)")


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else BROWSER_DIR
    os.makedirs(out_dir, exist_ok=True)
    print(f"building into {out_dir}")
    n_playlists, n_refs = build_data(out_dir)
    write_page(out_dir, n_playlists, n_refs)


if __name__ == "__main__":
    main()
