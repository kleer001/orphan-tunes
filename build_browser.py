#!/usr/bin/env python3
"""
Build a local browser for the exported playlists, in the iTunes 4 idiom.

    python build_browser.py [output_dir]

Emits data.js (a shared track pool plus one index list per playlist) and
index.html. Reads only. The page opens straight from disk; the VLC button
needs serve.py.
"""

import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple

from config import BROWSER_DIR, LIBRARY, LOCAL_ROOT
from make_playlists import index_by_name, locate  # the .m3u8 writer's own

# The page's script and layout stylesheet, copied next to index.html at build time.
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# Cover size on disk. The grid shows covers at about 170 px; a little over
# that keeps them sharp without making the art directory heavy.
ART_PX = 240

# iTunes records durations in milliseconds; the page wants whole seconds.
MILLISECONDS = 1000

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
    ("Rating",         "Rating",      "star", True),
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

def cell(track, key, kind):
    """One library value, in the shape the page expects for that column kind."""
    v = track.get(key)
    if v is None:
        return "" if kind in ("text", "date") else 0
    if kind == "time":
        return round(v / MILLISECONDS)
    if kind == "date":
        return v.strftime("%Y-%m-%d")          # plist datetime -> sortable string
    if kind == "bool":
        return 1 if v else 0
    if kind == "star" and track.get(key + " Computed"):
        return -v                              # derived by iTunes, not set by hand
    return v


class Library(NamedTuple):
    """What the page needs, separated from how it gets written out.

    `paths` is index-aligned with `tracks` and stays server-side: the page is
    only ever given row numbers. `music` lists the pool rows that make up the
    Library source; `albums` groups the whole pool, so a playlist's albums can
    be shown too.
    """

    tracks: list
    paths: list
    playlists: list
    missing: int
    music: list
    albums: list

    @property
    def refs(self):
        return sum(len(p["ids"]) for p in self.playlists)


# iTunes' Music library left these out; they had sources of their own.
NOT_MUSIC = ("Podcast", "Movie", "TV Show")
COMPILATIONS = "Compilations"


def is_music(track):
    """A local file that iTunes would have listed under Music."""
    return track.get("Location", "").startswith("file://") \
        and not any(track.get(k) for k in NOT_MUSIC)


def sort_text(track, key, sort_key):
    """iTunes' own sort key when it kept one, else the text without a leading "The"."""
    text = track.get(sort_key) or track.get(key) or ""
    return (text[4:] if text.lower().startswith("the ") else text).lower()


def album_of(track):
    """(artist, album) as iTunes grouped them: by Album Artist, else Artist, with
    compilations pooled so their guest artists do not each get an entry."""
    if track.get("Compilation"):
        artist, artist_sort = COMPILATIONS, ""     # sorts ahead of every name
    else:
        artist = track.get("Album Artist") or track.get("Artist") or "Unknown Artist"
        artist_sort = sort_text(track, "Album Artist", "Sort Album Artist") \
            if track.get("Album Artist") else sort_text(track, "Artist", "Sort Artist")
    album = track.get("Album") or "Unknown Album"
    return artist, album, artist_sort, sort_text(track, "Album", "Sort Album")


class Album(NamedTuple):
    title: str
    artist: str
    year: int
    ids: list          # pool rows in disc and track order
    art_from: str      # a file with embedded artwork, or "" when none has any


def group_albums(tracks, paths):
    """One Album per (artist, album) across the pool, sorted as iTunes 11 listed
    them. `tracks` is the raw library entry for each pool row."""
    groups = {}
    for row, track in enumerate(tracks):
        artist, album, artist_sort, album_sort = album_of(track)
        groups.setdefault((artist_sort, album_sort, artist, album), []).append(row)

    def order(row):
        t = tracks[row]
        return (t.get("Disc Number", 0), t.get("Track Number", 0), t.get("Name", ""))

    albums = []
    for (_, _, artist, album), ids in sorted(groups.items()):
        ids.sort(key=order)
        art = next((paths[i] for i in ids if paths[i] and tracks[i].get("Artwork Count")), "")
        albums.append(Album(album, artist, max(tracks[i].get("Year", 0) for i in ids), ids, art))
    return albums


def read_library():
    """Every music track plus every regular playlist, resolved against the files
    actually on disk."""
    with open(LIBRARY, "rb") as fh:
        lib = plistlib.load(fh)
    tracks = lib["Tracks"]
    index = index_by_name(LOCAL_ROOT)

    pool, paths, seen, raw = [], [], {}, []
    playlists, missing = [], 0

    def intern(track):
        """Add a track to the shared pool once; playlists store only offsets."""
        key = track["Track ID"]
        if key not in seen:
            path, how = locate(track, index)
            seen[key] = len(pool)
            pool.append([cell(track, k, kind) for k, _, kind, _ in FIELDS] + [how])
            paths.append(path)                 # None when the file was not found
            raw.append(track)
        return seen[key]

    music = [intern(t) for t in tracks.values() if is_music(t)]

    for playlist in lib["Playlists"]:
        if "Smart Info" in playlist or playlist.get("Master") \
                or playlist.get("Distinguished Kind") or not playlist.get("Playlist Items"):
            continue
        ids = []
        for item in playlist["Playlist Items"]:
            track = tracks.get(str(item["Track ID"]))
            if not track or not track.get("Location"):
                continue
            row = intern(track)
            if paths[row] is None:
                missing += 1
            ids.append(row)
        if ids:
            playlists.append({"name": playlist["Name"], "ids": ids})

    playlists.sort(key=lambda p: p["name"].lower())
    albums = group_albums(raw, paths)
    return Library(pool, paths, playlists, missing, music, albums)


def run_ffmpeg(*args):
    return subprocess.run(["ffmpeg", "-v", "error", "-nostdin", *args],
                          capture_output=True, check=False)


def extract_cover(src, dest):
    """Write the embedded cover of `src` to `dest`; return its average colour as
    "#rrggbb", or None when the file holds no picture ffmpeg can read."""
    made = run_ffmpeg("-y", "-i", src, "-map", "0:v:0", "-frames:v", "1",
                      "-vf", f"scale={ART_PX}:{ART_PX}:force_original_aspect_ratio=decrease",
                      "-q:v", "4", dest)
    if made.returncode or not os.path.isfile(dest):
        return None
    # Scaled to one pixel by area, which is the mean of the whole picture.
    pixel = run_ffmpeg("-i", dest, "-vf", "scale=1:1:flags=area",
                       "-f", "rawvideo", "-pix_fmt", "rgb24", "-").stdout
    return "#" + pixel[:3].hex()


def extract_art(albums, out_dir):
    """{album index: (url, colour)} for every album with a readable cover.

    Covers are cached in art/ under a hash of the file they came from, with
    art.json recording each result -- including "no picture" -- so a rebuild
    only runs ffmpeg for albums it has not seen.
    """
    art_dir = os.path.join(out_dir, "art")
    os.makedirs(art_dir, exist_ok=True)
    manifest_path = os.path.join(art_dir, "art.json")
    manifest = {}
    if os.path.isfile(manifest_path):
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)

    names = {a.art_from: hashlib.sha1(a.art_from.encode()).hexdigest()[:16]
             for a in albums if a.art_from}
    todo = [src for src, name in names.items() if name not in manifest]
    if todo:
        print(f"  extracting {len(todo)} covers with ffmpeg ...")
        with ThreadPoolExecutor() as pool:
            colours = pool.map(lambda src: extract_cover(
                src, os.path.join(art_dir, names[src] + ".jpg")), todo)
            for src, colour in zip(todo, colours, strict=True):
                manifest[names[src]] = colour
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=0, sort_keys=True)

    return {i: (f"art/{names[a.art_from]}.jpg", manifest[names[a.art_from]])
            for i, a in enumerate(albums)
            if a.art_from and manifest[names[a.art_from]]}


def write_data(library, out_dir, art):
    """Two files: what the page reads, and what only the server reads."""
    fields = [[label, kind, show] for _, label, kind, show in FIELDS]
    fields.append(["Found", "found", False])   # derived, not from the library

    # Opened from disk there is no /audio, so each track also gets a URL
    # relative to the page, as the .m3u8 files do. Quoted, or a "#" or "%" in
    # a filename would be read as a fragment or an escape.
    files = [urllib.parse.quote(os.path.relpath(p, out_dir)) if p else None
             for p in library.paths]
    albums = [[a.title, a.artist, a.year, *art.get(i, ("", "")), a.ids]
              for i, a in enumerate(library.albums)]
    data = {"fields": fields, "tracks": library.tracks, "playlists": library.playlists,
            "files": files, "music": library.music, "albums": albums}
    # A script, not JSON: Firefox refuses fetch() between file:// pages, but
    # still runs a <script src>, so the page also works opened from disk.
    path = os.path.join(out_dir, "data.js")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("const LIBRARY=")
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write(";\n")

    with open(os.path.join(out_dir, "paths.json"), "w", encoding="utf-8") as fh:
        json.dump(library.paths, fh, ensure_ascii=False, separators=(",", ":"))
    return os.path.getsize(path)


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
             "--pane-inset": "inset 1px 1px 0 #808080,inset -1px -1px 0 #fff",
             "--radius": "0",
             "--rowsel": "#000080",
             "--scroll-a": "#c0c0c0",
             "--scroll-b": "#c0c0c0",
             "--scroll-line": "#000",
             "--scroll-track": "#dfdfdf",
             "--sel": "#000080",
             "--shadow": "none",
             "--sorted-a": "#a0a0a0",
             "--sorted-b": "#a0a0a0",
             "--src-head-a": "#c0c0c0",
             "--src-head-b": "#c0c0c0",
             "--src-head-ink": "#000",
             "--src-line": "#808080",
             "--stripe": "#fff",
             "--title-bg": "linear-gradient(#000080,#000080)",
             "--title-h": "20px",
             "--title-ink": "#fff",
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
             "--pane-inset": "inset 1px 1px 0 #808080,inset -1px -1px 0 #fff",
             "--radius": "0",
             "--rowsel": "#000080",
             "--scroll-a": "#c0c0c0",
             "--scroll-b": "#c0c0c0",
             "--scroll-line": "#808080",
             "--scroll-track": "#dfdfdf",
             "--sel": "#000080",
             "--shadow": "none",
             "--sorted-a": "#dfdfdf",
             "--sorted-b": "#c0c0c0",
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
             "--pane-inset": "inset 0 1px 3px rgba(0,0,0,.22)",
             "--radius": "8px 8px 0 0",
             "--rowsel": "#c1d7f5",
             "--scroll-a": "#dfeaf8",
             "--scroll-b": "#9dbbe4",
             "--scroll-line": "#7f9ec9",
             "--scroll-track": "#f1efe4",
             "--sel": "#316ac5",
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


def read_static(name):
    with open(os.path.join(STATIC, name), encoding="utf-8") as fh:
        return fh.read()


def render_skins():
    """BASE_TOKENS becomes :root; each skin with overrides becomes a block."""
    out = [":root{" + "".join(f"{k}:{v};" for k, v in BASE_TOKENS.items()) + "}"]
    for skin in SKINS:
        if not skin.tokens:
            continue
        decls = "".join(f"{k}:{v};" for k, v in skin.tokens.items())
        out.append(f'[data-skin="{skin.id}"]{{{decls}}}')
    return "\n".join(out)


FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E"
           "%3Cpath fill='%233a6ea5' d='M5 1v9.2A2.6 2.6 0 1 0 6.6 12.6V4.6H12V1z'/%3E%3C/svg%3E")

NOTE_SVG = ("<svg width='9' height='11' viewBox='0 0 9 11' fill='%233a6ea5'>"
            "<path d='M3 0v7.1A2 2 0 1 0 4 9V3h4V0z'/></svg>")


def write_page(out_dir, n_playlists, n_refs):
    skins_json = json.dumps([[s.id, s.label, s.era] for s in SKINS])
    repeat_json = json.dumps(REPEAT_CYCLE)
    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Playlists</title>
<link rel="icon" href="{FAVICON}"><link rel="stylesheet" href="style.css"></head>
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
    <div class="lcd" id="lcd">
      <img id="lcdArt" alt="">
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
      <div class="viewbar">
        <div class="seg" id="views">
          <button data-v="songs">Songs</button><button data-v="albums">Albums</button><button
            data-v="artists">Artists</button>
        </div>
        <button class="sbtn browse" id="browse" title="Show Browser (Ctrl+B)">
          <svg width="11" height="11" viewBox="0 0 12 12"><path d="M0 1h12v10H0zm1 1v8h2.8V2zm3.8
            0v8h2.4V2zm3.4 0v8H11V2z"/></svg>
        </button>
      </div>
      <div class="view" id="vsongs">
        <div class="browser" id="browser">
          <div class="pane"><h5>Genre</h5><div class="plist" id="pgenre"></div></div>
          <div class="pane"><h5>Artist</h5><div class="plist" id="partist"></div></div>
          <div class="pane"><h5>Album</h5><div class="plist" id="palbum"></div></div>
        </div>
        <div class="scroll" id="scroll">
          <div class="thead" id="thead"></div>
          <div id="rows"></div>
        </div>
      </div>
      <div class="view" id="valbums"><div class="grid" id="grid"></div></div>
      <div class="view" id="vartists">
        <div class="artists">
          <div class="alist" id="alist"></div>
          <div class="adetail" id="adetail"></div>
        </div>
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
      <button class="sbtn" id="upnextBtn" title="Up Next">
        <svg width="11" height="11" viewBox="0 0 12 12"><path d="M0 1h2v2H0zm3 0h9v2H3zM0
          5h2v2H0zm3 0h9v2H3zM0 9h2v2H0zm3 0h9v2H3z"/></svg>
        <b id="upnextBadge"></b>
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
<div class="panel menu" id="ctx"></div>
<div class="panel" id="upnext"></div>
<script>
const NOTE="{NOTE_SVG}";
const SKINS={skins_json};
const REPEAT={repeat_json};
</script>
<script src="data.js"></script>
<script src="app.js"></script>
</body></html>"""
    path = os.path.join(out_dir, "index.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    # The skins are generated from Python data; the layout is a plain file.
    with open(os.path.join(out_dir, "style.css"), "w", encoding="utf-8") as fh:
        fh.write(render_skins() + "\n" + read_static("layout.css"))
    shutil.copyfile(os.path.join(STATIC, "app.js"), os.path.join(out_dir, "app.js"))
    print(f"  index.html {os.path.getsize(path) / 1024:.0f} KB "
          f"({n_playlists} playlists, {n_refs} refs)")


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else BROWSER_DIR
    os.makedirs(out_dir, exist_ok=True)
    print(f"building into {out_dir}")
    library = read_library()
    art = extract_art(library.albums, out_dir)
    size = write_data(library, out_dir, art)
    print(f"  {len(library.music)} library tracks, {len(library.albums)} albums, "
          f"{len(art)} with covers")
    print(f"  {len(library.playlists)} playlists, {library.refs} track refs, "
          f"{len(library.tracks)} unique tracks, {library.missing} shown as missing")
    print(f"  data.js {size / 1e6:.1f} MB")
    write_page(out_dir, len(library.playlists), library.refs)


if __name__ == "__main__":
    main()
