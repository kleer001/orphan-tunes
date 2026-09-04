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


CSS = r"""
/* ---- Skins ------------------------------------------------------------
   Each era is a swap of these tokens. Only the eras that kept the same
   two-pane layout are offered: iTunes 11 hid the sidebar and 12 moved to a
   tab bar, so painting those colours on this layout would be a costume, not
   a skin. Named for small towns in British Columbia.
   Greenwood is the default and matches iTunes 1-4.                        */
:root{
  /* shape and type, so a skin can stop being Mac-shaped */
  --font:"Lucida Grande","Segoe UI",Helvetica,Arial,sans-serif;
  --ink:#000;
  --radius:7px; --lcd-radius:9px; --btn-radius:50%; --field-radius:10px;
  --bevel:inset 0 1px 0 #fff,0 1px 2px rgba(0,0,0,.28);
  --bevel-in:inset 0 2px 4px rgba(0,0,0,.3);
  --pane-inset:inset 0 1px 3px rgba(0,0,0,.3);
  --lights:flex;
  --gear-radius:4px;
  --vlc-a:#6f6f6f; --vlc-b:#3a3a3a; --vlc-line:#2f2f2f; --vlc-ink:#f4f4f4;
  --vlc-shadow:inset 0 1px 0 rgba(255,255,255,.28),0 1px 3px rgba(0,0,0,.4);
  --title-bg:var(--grain),linear-gradient(var(--chrome-a),var(--chrome-b));
  --title-ink:#3a3a3a; --title-just:center; --title-pad:0;
  --title-h:22px; --title-weight:600;
  --shadow:0 12px 34px rgba(0,0,0,.45);

  --desk:#6b6b6b;
  --grain:repeating-linear-gradient(0deg,rgba(255,255,255,.55) 0 1px,rgba(0,0,0,.035) 1px 2px);
  --chrome-a:#e8e8e8; --chrome-b:#d0d0d0; --chrome-line:#a4a4a4; --chrome-ink:#3a3a3a;
  --win-line:#6f6f6f;
  --lcd-a:#d7dbcd; --lcd-b:#c9cebe; --lcd-line:#8e9384; --lcd-ink:#20241c; --lcd-dim:#4a5044;
  --bar-track:#b9bfae; --bar-line:#949a8a; --bar-a:#8f9c82; --bar-b:#6f7c63;
  --btn-a:#fdfdfd; --btn-b:#d7d7d7; --btn-line:#8d8d8d; --btn-ink:#3c3c3c;
  --pane:#fff;
  --src-bg:#fff; --src-line:#9a9a9a;
  --src-head-a:#ededed; --src-head-b:#dcdcdc; --src-head-ink:#555;
  --sel:#3a6ea5; --sel-ink:#fff;
  --head-a:#f0f0f0; --head-b:#dadada; --head-line:#9a9a9a; --head-ink:#333; --head-div:#c4c4c4;
  --sorted-a:#dfe7f2; --sorted-b:#c9d6e8;
  --stripe:#edf3fb; --rowsel:#b6c8de;
  --scroll-track:#f0f0f0; --scroll-a:#c8d4e4; --scroll-b:#9db2cc; --scroll-line:#7f92aa;
}

/* Tofino -- iTunes 5-6. The metal grain dropped for flat grey; coastal fog. */
[data-skin="tofino"]{
  --desk:#7a7a7a;
  --grain:none;
  --chrome-a:#f4f4f4; --chrome-b:#dedede; --chrome-line:#b0b0b0; --chrome-ink:#404040;
  --win-line:#8a8a8a;
  --lcd-a:#e4e6e4; --lcd-b:#d4d7d4; --lcd-line:#a6a9a6; --lcd-ink:#2a2c2a; --lcd-dim:#5b5f5b;
  --bar-track:#c6c9c6; --bar-line:#a2a5a2; --bar-a:#9aa09a; --bar-b:#7d827d;
  --btn-a:#fff; --btn-b:#e2e2e2; --btn-line:#a6a6a6;
  --src-head-a:#f4f4f4; --src-head-b:#e6e6e6;
  --head-a:#f7f7f7; --head-b:#e6e6e6; --head-line:#b4b4b4; --head-div:#d6d6d6;
  --sorted-a:#e8eef6; --sorted-b:#d8e2ee;
  --stripe:#f1f4f8; --rowsel:#c3d1e0;
  --scroll-track:#f6f6f6; --scroll-a:#d8d8d8; --scroll-b:#b4b4b4; --scroll-line:#a0a0a0;
}

/* Kaslo -- iTunes 7-10. The blue sidebar era; lake water off the Kootenays. */
[data-skin="kaslo"]{
  --desk:#5f6672;
  --grain:none;
  --chrome-a:#e2e6ea; --chrome-b:#c8cfd6; --chrome-line:#9aa3ad; --chrome-ink:#333b44;
  --win-line:#69737e;
  --lcd-a:#dfe4e8; --lcd-b:#ccd3da; --lcd-line:#8f9aa4; --lcd-ink:#1e262e; --lcd-dim:#4d5761;
  --bar-track:#bcc5cd; --bar-line:#93a0aa; --bar-a:#8497a8; --bar-b:#63788b;
  --btn-a:#fff; --btn-b:#dbe1e7; --btn-line:#98a2ac;
  --src-bg:#dfe6ee; --src-line:#a6b0bb;
  --src-head-a:#e9eef4; --src-head-b:#d6dee7; --src-head-ink:#4a5560;
  --sel:#4a7fc1; --sel-ink:#fff;
  --head-a:#eef2f6; --head-b:#d9e0e8; --head-line:#a2acb6; --head-ink:#2f3841; --head-div:#c2ccd6;
  --sorted-a:#dde8f6; --sorted-b:#c4d6ec;
  --stripe:#eaf0f8; --rowsel:#b3c7de;
  --scroll-track:#e8edf2; --scroll-a:#c2d0e0; --scroll-b:#96a9be; --scroll-line:#7d90a5;
}


/* --- Redmond's turn. Named for small towns in Washington and Oregon. ------
   These change shape as well as colour: square corners, chunky bevels, a real
   title bar. Still tokens only, so the layout underneath is untouched.       */

/* Concrete, WA -- Windows 3.1. Teal desktop, solid navy title, centred, and
   the raised grey bevel on everything. There is a real town called Concrete. */
[data-skin="concrete"]{
  --gear-radius:0;
  --vlc-a:#c0c0c0; --vlc-b:#c0c0c0; --vlc-line:#000; --vlc-ink:#000;
  --vlc-shadow:inset -1px -1px 0 #000,inset 1px 1px 0 #fff,
               inset -2px -2px 0 #808080,inset 2px 2px 0 #dfdfdf;
  --font:"MS Sans Serif",Tahoma,Geneva,Verdana,sans-serif;
  --desk:#008080; --grain:none;
  --radius:0; --lcd-radius:0; --btn-radius:0; --field-radius:0;
  --bevel:inset -1px -1px 0 #000,inset 1px 1px 0 #fff,
          inset -2px -2px 0 #808080,inset 2px 2px 0 #dfdfdf;
  --bevel-in:inset 1px 1px 0 #000,inset -1px -1px 0 #fff,
             inset 2px 2px 0 #808080,inset -2px -2px 0 #dfdfdf;
  --pane-inset:inset 1px 1px 0 #808080,inset -1px -1px 0 #fff;
  --shadow:none; --lights:none;
  --title-bg:linear-gradient(#000080,#000080); --title-ink:#fff;
  --title-just:center; --title-h:20px; --title-weight:700;
  --chrome-a:#c0c0c0; --chrome-b:#c0c0c0; --chrome-line:#000; --chrome-ink:#000;
  --win-line:#000;
  --lcd-a:#c0c0c0; --lcd-b:#c0c0c0; --lcd-line:#808080; --lcd-ink:#000; --lcd-dim:#000;
  --bar-track:#fff; --bar-line:#808080; --bar-a:#000080; --bar-b:#000080;
  --btn-a:#c0c0c0; --btn-b:#c0c0c0; --btn-line:#000; --btn-ink:#000;
  --pane:#fff; --src-bg:#fff; --src-line:#808080;
  --src-head-a:#c0c0c0; --src-head-b:#c0c0c0; --src-head-ink:#000;
  --sel:#000080; --sel-ink:#fff;
  --head-a:#c0c0c0; --head-b:#c0c0c0; --head-line:#808080; --head-ink:#000; --head-div:#808080;
  --sorted-a:#a0a0a0; --sorted-b:#a0a0a0;
  --stripe:#fff; --rowsel:#000080;
  --scroll-track:#dfdfdf; --scroll-a:#c0c0c0; --scroll-b:#c0c0c0; --scroll-line:#000;
}

/* Startup, WA -- Windows 95. The gradient title bar, left-aligned. A real town,
   and the only sensible name for the release that introduced the Start button. */
[data-skin="startup"]{
  --gear-radius:0;
  --vlc-a:#c0c0c0; --vlc-b:#c0c0c0; --vlc-line:#000; --vlc-ink:#000;
  --vlc-shadow:inset -1px -1px 0 #000,inset 1px 1px 0 #fff,
               inset -2px -2px 0 #808080,inset 2px 2px 0 #dfdfdf;
  --font:"MS Sans Serif",Tahoma,Geneva,Verdana,sans-serif;
  --desk:#008080; --grain:none;
  --radius:0; --lcd-radius:0; --btn-radius:0; --field-radius:0;
  --bevel:inset -1px -1px 0 #000,inset 1px 1px 0 #fff,
          inset -2px -2px 0 #808080,inset 2px 2px 0 #dfdfdf;
  --bevel-in:inset 1px 1px 0 #000,inset -1px -1px 0 #fff,
             inset 2px 2px 0 #808080,inset -2px -2px 0 #dfdfdf;
  --pane-inset:inset 1px 1px 0 #808080,inset -1px -1px 0 #fff;
  --shadow:none; --lights:none;
  --title-bg:linear-gradient(90deg,#000080,#1084d0); --title-ink:#fff;
  --title-just:flex-start; --title-pad:0 6px; --title-h:20px; --title-weight:700;
  --chrome-a:#c0c0c0; --chrome-b:#c0c0c0; --chrome-line:#808080; --chrome-ink:#000;
  --win-line:#000;
  --lcd-a:#c0c0c0; --lcd-b:#c0c0c0; --lcd-line:#808080; --lcd-ink:#000; --lcd-dim:#404040;
  --bar-track:#fff; --bar-line:#808080; --bar-a:#000080; --bar-b:#1084d0;
  --btn-a:#c0c0c0; --btn-b:#c0c0c0; --btn-line:#000; --btn-ink:#000;
  --pane:#fff; --src-bg:#fff; --src-line:#808080;
  --src-head-a:#c0c0c0; --src-head-b:#c0c0c0; --src-head-ink:#000;
  --sel:#000080; --sel-ink:#fff;
  --head-a:#c0c0c0; --head-b:#c0c0c0; --head-line:#808080; --head-ink:#000; --head-div:#dfdfdf;
  --sorted-a:#dfdfdf; --sorted-b:#c0c0c0;
  --stripe:#fff; --rowsel:#000080;
  --scroll-track:#dfdfdf; --scroll-a:#c0c0c0; --scroll-b:#c0c0c0; --scroll-line:#808080;
}

/* Chelan, WA -- Windows XP Luna. Deep lake blue, and the beige workspace that
   came with it. Rounded again, but only at the top.                          */
[data-skin="chelan"]{
  --gear-radius:3px;
  --vlc-a:#5b9bd5; --vlc-b:#2a6db5; --vlc-line:#1c4f8a; --vlc-ink:#fff;
  --vlc-shadow:inset 0 1px 0 rgba(255,255,255,.5),0 1px 2px rgba(0,0,0,.3);
  --font:Tahoma,"Segoe UI",Verdana,sans-serif;
  --desk:linear-gradient(#4a7ec4,#7aa8dc) fixed; --grain:none;
  --radius:8px 8px 0 0; --lcd-radius:3px; --btn-radius:4px; --field-radius:3px;
  --bevel:inset 0 1px 0 rgba(255,255,255,.9),0 1px 2px rgba(0,0,0,.25);
  --bevel-in:inset 0 2px 4px rgba(0,0,0,.28);
  --pane-inset:inset 0 1px 3px rgba(0,0,0,.22);
  --shadow:0 10px 30px rgba(0,0,0,.4); --lights:none;
  --title-bg:linear-gradient(#0a55d4,#3a86e8 8%,#2c76dc 40%,#1a5fd0); --title-ink:#fff;
  --title-just:flex-start; --title-pad:0 10px; --title-h:26px; --title-weight:700;
  --chrome-a:#f6f4ec; --chrome-b:#ece9d8; --chrome-line:#aca899; --chrome-ink:#22314a;
  --win-line:#0a3f9c;
  --lcd-a:#fbfaf6; --lcd-b:#ece9d8; --lcd-line:#aca899; --lcd-ink:#1b2740; --lcd-dim:#5a6478;
  --bar-track:#e6e3d4; --bar-line:#aca899; --bar-a:#4f9d3a; --bar-b:#2f7a20;
  --btn-a:#fdfdfb; --btn-b:#e8e5d6; --btn-line:#a9a596; --btn-ink:#22314a;
  --pane:#fff; --src-bg:#eef3fb; --src-line:#a7b6cc;
  --src-head-a:#f6f4ec; --src-head-b:#e4e0cf; --src-head-ink:#3b4a63;
  --sel:#316ac5; --sel-ink:#fff;
  --head-a:#fbfaf6; --head-b:#e8e5d6; --head-line:#aca899; --head-ink:#22314a; --head-div:#d4d0c0;
  --sorted-a:#dbe6f8; --sorted-b:#bed3f2;
  --stripe:#f3f6fc; --rowsel:#c1d7f5;
  --scroll-track:#f1efe4; --scroll-a:#dfeaf8; --scroll-b:#9dbbe4; --scroll-line:#7f9ec9;
}

/* Boring, OR -- Hot Dog Stand. The Windows 3.1 scheme nobody chose on purpose:
   red, yellow, black, and no mercy. The town is real and the name is the joke. */
[data-skin="boring"]{
  --gear-radius:0;
  --vlc-a:#ffff00; --vlc-b:#ffff00; --vlc-line:#000; --vlc-ink:#000;
  --vlc-shadow:inset -1px -1px 0 #000,inset 1px 1px 0 #ffff00;
  --font:"MS Sans Serif",Tahoma,Geneva,Verdana,sans-serif;
  --desk:#ff0000; --grain:none; --ink:#000;
  --radius:0; --lcd-radius:0; --btn-radius:0; --field-radius:0;
  --bevel:inset -1px -1px 0 #000,inset 1px 1px 0 #ffff00;
  --bevel-in:inset 1px 1px 0 #000,inset -1px -1px 0 #ffff00;
  --pane-inset:inset 1px 1px 0 #000;
  --shadow:none; --lights:none;
  --title-bg:linear-gradient(#ffff00,#ffff00); --title-ink:#000;
  --title-just:center; --title-h:20px; --title-weight:700;
  --chrome-a:#ff0000; --chrome-b:#ff0000; --chrome-line:#000; --chrome-ink:#ffff00;
  --win-line:#000;
  --lcd-a:#ffff00; --lcd-b:#ffff00; --lcd-line:#000; --lcd-ink:#000; --lcd-dim:#800000;
  --bar-track:#ffff00; --bar-line:#000; --bar-a:#ff0000; --bar-b:#ff0000;
  --btn-a:#ffff00; --btn-b:#ffff00; --btn-line:#000; --btn-ink:#000;
  --pane:#ffff00; --src-bg:#ffff00; --src-line:#000;
  --src-head-a:#ff0000; --src-head-b:#ff0000; --src-head-ink:#ffff00;
  --sel:#ff0000; --sel-ink:#ffff00;
  --head-a:#ff0000; --head-b:#ff0000; --head-line:#000; --head-ink:#ffff00; --head-div:#000;
  --sorted-a:#ffff00; --sorted-b:#ffff00;
  --stripe:#ffe000; --rowsel:#ff0000;
  --scroll-track:#ffff00; --scroll-a:#ff0000; --scroll-b:#ff0000; --scroll-line:#000;
}

/* ---- Layout ---------------------------------------------------------- */
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{background:var(--desk);font:11px/1.35 var(--font);
     color:var(--ink);display:flex;align-items:center;justify-content:center;padding:14px;
     -webkit-font-smoothing:antialiased}

.metal{background-image:var(--grain),linear-gradient(var(--chrome-a),var(--chrome-b))}

.win{width:100%;max-width:1180px;height:100%;max-height:820px;display:flex;flex-direction:column;
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
     border-bottom:1px solid var(--chrome-line)}
.lcd{flex:1;height:66px;border-radius:var(--lcd-radius);
     background:linear-gradient(var(--lcd-a),var(--lcd-b));
     border:1px solid var(--lcd-line);box-shadow:var(--pane-inset);
     display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;
     text-shadow:0 1px 0 rgba(255,255,255,.4);overflow:hidden;padding:0 12px}
#lcdName{font-weight:600;font-size:12px;color:var(--lcd-ink);white-space:nowrap;
         overflow:hidden;text-overflow:ellipsis;max-width:100%}
#lcdSub{font-size:10px;color:var(--lcd-dim);font-variant-numeric:tabular-nums}
.searchwrap{flex:none;display:flex;flex-direction:column;align-items:flex-end;gap:5px}
#search{width:190px;height:20px;border-radius:var(--field-radius);
        border:1px solid var(--lcd-line);color:var(--ink);padding:0 22px 0 22px;
        font:11px "Lucida Grande",sans-serif;background:#fff url("data:image/svg+xml;charset=utf8,\
%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Cg fill='none' stroke='%23888' \
stroke-width='1.6'%3E%3Ccircle cx='7' cy='7' r='4'/%3E\
%3Cpath d='M10 10l3.5 3.5'/%3E%3C/g%3E%3C/svg%3E") \
6px 50%/11px no-repeat;box-shadow:inset 0 1px 2px rgba(0,0,0,.18)}
#search:focus{outline:2px solid #7ba7e0;outline-offset:-1px}
#count{font-size:10px;color:var(--chrome-ink);font-variant-numeric:tabular-nums}

.body{flex:1;display:flex;min-height:0;border-top:1px solid #fff}

.source{width:172px;flex:none;background:var(--src-bg);border-right:1px solid var(--src-line);
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
.gear{position:absolute;right:6px;top:50%;transform:translateY(-50%);
      width:17px;height:17px;border-radius:var(--gear-radius);
      border:1px solid var(--btn-line);
      background:linear-gradient(var(--btn-a),var(--btn-b));cursor:pointer;
      display:flex;align-items:center;justify-content:center;padding:0}
.gear:hover{filter:brightness(1.06)}
.gear svg{fill:var(--btn-ink);pointer-events:none}

::-webkit-scrollbar{width:13px}
::-webkit-scrollbar-track{background:var(--scroll-track);border-left:1px solid var(--head-div)}
::-webkit-scrollbar-thumb{background:linear-gradient(90deg,var(--scroll-a),var(--scroll-b));
  border:1px solid var(--scroll-line);border-radius:6px}
"""

FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E"
           "%3Cpath fill='%233a6ea5' d='M5 1v9.2A2.6 2.6 0 1 0 6.6 12.6V4.6H12V1z'/%3E%3C/svg%3E")

NOTE_SVG = ("<svg width='9' height='11' viewBox='0 0 9 11' fill='%233a6ea5'>"
            "<path d='M3 0v7.1A2 2 0 1 0 4 9V3h4V0z'/></svg>")

JS = r"""
const $=s=>document.querySelector(s);
let DATA=null,FIELDS=[],FOUND=-1,vis=[],cur=0,sortCol=-1,asc=true,rows=[],sel=-1;
// what is playing, as a pool index, plus the queue it came from
let nowIdx=-1,queue=[],qpos=-1;
const KEY="playlists.columns", SKINKEY="playlists.skin";
// Only eras that kept this layout. iTunes 11 hid the sidebar and 12 moved to a
// tab bar, so they are deliberately absent rather than faked.
const SKINS=[["greenwood","Greenwood","iTunes 1-4"],
             ["tofino","Tofino","iTunes 5-6"],
             ["kaslo","Kaslo","iTunes 7-10"],
             ["concrete","Concrete","Windows 3.1"],
             ["startup","Startup","Windows 95"],
             ["chelan","Chelan","Windows XP"],
             ["boring","Boring","Hot Dog Stand"]];

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

function play(poolIndex){
  const t=DATA.tracks[poolIndex];
  if(missing(t))return;
  nowIdx=poolIndex;
  queue=rows.filter(i=>!missing(DATA.tracks[i]));
  qpos=queue.indexOf(poolIndex);
  audio.src="audio?i="+poolIndex;
  audio.play().catch(()=>{ lcd(`Cannot play ${t[0]}`); });
  draw();
}

function step(by){
  if(!queue.length)return;
  const at=qpos+by;
  if(at<0||at>=queue.length){stop();return;}
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
  applySkin(skinName()); buildPrefs();
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
    <span id="status"></span>
    <button class="gear" id="gear" title="Preferences">
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
<script>const NOTE="{NOTE_SVG}";</script>
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
