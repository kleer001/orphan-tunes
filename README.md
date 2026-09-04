# you_tunes_browser

Brings an old iTunes library back to life against your own files. Reads the
exported `iTunes Music Library.xml`, finds each track on disk, and gives you two
things: a folder of `.m3u8` playlists any player can open, and a local web page
that browses them in the iTunes 4 idiom — source list on the left, sortable
track table on the right, and a Play button that hands the current view to VLC.

No network, no accounts, no streaming service. Everything reads local files.

## Why it exists

An iTunes library XML records an absolute path for every track. Move the music
to another machine and every one of those paths is wrong, so the playlists —
often the only surviving record of how a collection was organised — become
unreadable while the audio sits right there.

This rewrites the recorded path prefix onto wherever the music lives now, then
falls back to a filename search, then to an exact byte-size match when a generic
name like `01 Track 1.mp3` appears in several albums. Anything still unresolved
is reported rather than quietly dropped.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Put your library export at `data/iTunes Music Library.xml`, then edit
`config.toml`:

```toml
[music]
recorded_root = "/Users/you/Music/iTunes/iTunes Media/Music"   # what the XML says
local_root    = "/mnt/archive/Music"                           # where it is now
```

`recorded_root` is the `Music Folder` value inside the XML. Relative paths in
`config.toml` resolve against the repo; absolute ones are used as given.

## Use

```bash
python make_playlists.py        # write one .m3u8 per playlist
python build_browser.py         # build the browsable page
python serve.py <browser_dir> 8100
```

Then open the printed `http://127.0.0.1:<port>/`. The port is probed upward from
the one you asked for, so a leftover process doesn't stop the launch.

### In the page

- **Source list** — every playlist, alphabetical; click to switch.
- **Track table** — click a header to sort, click again to reverse.
- **Search** — filters the current playlist by song, artist, and album.
- **View Options** — right-click the column headers. Every non-plumbing field
  from the library is available: ratings as stars, bit rate, sample rate, dates
  added / played / skipped, composer, BPM, comments, disc and track numbers.
  The choice is remembered per browser.
- **Play in VLC** — hands VLC exactly what is on screen, in the order shown.
  Sort by length, filter to one artist, then play that.

## How the Play button works

A web page cannot launch an application, so the page posts to the local server,
which writes `_now_playing.m3u8` into the browser directory and opens it in VLC.

The page sends **row numbers only**, never paths. The server maps them through
its own `paths.json`, so a request cannot name a file that isn't in the library;
indices outside the pool are refused. The server binds to `127.0.0.1`.

## Files

| | |
| --- | --- |
| `config.py`, `config.toml` | the only place machine-specific paths live |
| `make_playlists.py` | library XML → `.m3u8` files |
| `build_browser.py` | library XML → `index.html`, `data.json`, `paths.json` |
| `serve.py` | static server plus the `/play` endpoint |

`build_browser.py` imports `locate()` and `safe_name()` from `make_playlists.py`
so both agree on where a track lives and what its playlist file is called.

## Limits

- Regular playlists only. Smart playlists, the master library list, and empty
  playlists are skipped.
- Tracks whose files are genuinely missing are counted and reported, not faked.
- `data/` is gitignored: a library export is personal listening history.
