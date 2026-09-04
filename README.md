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
python serve.py                 # directory and port come from config.toml
```

`serve.py` takes an optional directory and port; a bare number is read as a
port, so `python serve.py 9000` works without restating the directory.

Then open the printed `http://127.0.0.1:<port>/`. The port is probed upward from
the one you asked for, so a leftover process doesn't stop the launch.

The window fills the browser, at any size. Wide, the track table gets the room;
narrow, the source list tightens and the table scrolls sideways inside its own
pane rather than pushing the page around.

### In the page

- **Source list** — every playlist, alphabetical; click to switch.
- **Track table** — click a header to sort, click again to reverse.
- **Search** — filters the current playlist by song, artist, and album.
- **View Options** — right-click the column headers. Every non-plumbing field
  from the library is available: ratings as stars, bit rate, sample rate, dates
  added / played / skipped, composer, BPM, comments, disc and track numbers.
  The choice is remembered per browser.
- **Playback** — double-click a row to play it, or press play to start from the
  selection. Skip, seek by clicking the progress bar, and it advances through the
  rows in the order shown, skipping ones that aren't on disk.
- **Play in VLC** — the fallback. Hands VLC exactly what is on screen, in the
  order shown. Better for a long listen: gapless, ReplayGain, and every codec
  the browser won't touch.
- **Skins** — the gear in the bottom-right corner. Remembered per browser.

  | | | |
  | --- | --- | --- |
  | **Greenwood** | iTunes 1–4 | brushed metal, the default |
  | **Tofino** | iTunes 5–6 | flat grey |
  | **Kaslo** | iTunes 7–10 | blue sidebar |
  | **Concrete** | Windows 3.1 | teal desktop, centred navy title |
  | **Startup** | Windows 95 | the gradient title bar |
  | **Chelan** | Windows XP | Luna blue and beige |
  | **Boring** | Hot Dog Stand | red, yellow, black, no mercy |
  | **Azalea** | MySpace 2006 | not an OS at all: gradients until it hurts |

  Mac eras are named for small towns in British Columbia, the rest for small
  towns in Washington and Oregon. All eight towns are real.

  Boring's structure comes from a real Program Manager screenshot rather than
  memory: red covers about half the screen, yellow a quarter, and title bars are
  red with yellow text — the inverse of what most tributes assume. It parts
  company with the original on the grey: every control is red or yellow here,
  with tonal variation and gentle gradients the 16-colour palette could not have
  produced. Faithful in shape, committed in colour.
- **Missing tracks** — shown greyed, with a Found column saying how each was
  located: `direct`, `moved`, `by size`, or `gone`. They're excluded from totals
  and never queued.

## How playback works

`GET /audio?i=<n>` streams a track with byte-range support, which is what makes
seeking work — Python's stock handler has none, so it is implemented here. The
server is threaded, or streaming one track would block the page that asked for
it.

No decoder is involved. Browsers already decode MP3, AAC/M4A, WAV and FLAC; the
server's job is only to hand over the right bytes with the right content type.
That covers about 99% of a typical library. AIFF is the usual holdout — those
tracks fail visibly rather than silently, and the VLC button plays them.

The VLC fallback posts to `/play`, which writes `_now_playing.m3u8` and opens it.

Both endpoints take **row numbers only**, never paths. The server maps them
through its own `paths.json`, which the page never receives, so neither can be
asked for a file outside the library. It binds to `127.0.0.1`.

## Files

| | |
| --- | --- |
| `config.py`, `config.toml` | the only place machine-specific paths live |
| `make_playlists.py` | library XML → `.m3u8` files |
| `build_browser.py` | library XML → `index.html`, `data.json`, `paths.json` |
| `serve.py` | static server plus the `/play` endpoint |
| `tools/demangle.py` | repairs an archive copy whose filenames were mangled |

`build_browser.py` imports `locate()` and `safe_name()` from `make_playlists.py`
so both agree on where a track lives and what its playlist file is called.

## `tools/demangle.py`

Some archive copies arrive with every filename mangled: the real file saved with
`-2` appended to its stem, and an empty directory left holding the name it
wanted. A library XML can't resolve against a tree in that state.

```bash
python tools/demangle.py /path/to/music            # plan only, changes nothing
python tools/demangle.py /path/to/music --apply    # execute, journalling each rename
python tools/demangle.py --undo <journal>          # reverse it
```

It only ever acts on a pair whose target name is held by an **empty directory**,
so a file genuinely named `Track-2.mp3` is reported and skipped. `rmdir` clears
the placeholder — it physically cannot remove a directory with anything in it —
and `os.rename` then moves the file onto the freed name. If the plan contains any
conflict at all, nothing runs: a half-finished pass over tens of thousands of
files is worse than one that declines to start.

Every rename is journalled, and `--undo` reverses the whole run.

## Why only three skins

iTunes 11 hid the sidebar and led with an album grid; 12 moved to a tab bar
across the top. Those are different layouts, not different paint, so putting
their colours on this one would be a costume rather than a skin. The three
offered are the eras that genuinely shared this arrangement.

Each skin is a set of CSS custom-property overrides — no skin sets a real
property, which is enforced by a test, so none of them can drift the layout. The
tokens cover shape as well as colour (corner radius, bevels, title bar, type),
which is what lets a Windows skin stop being Mac-shaped without touching a rule.

## Limits

- Regular playlists only. Smart playlists, the master library list, and empty
  playlists are skipped.
- Tracks whose files are genuinely missing are counted and reported, not faked.
- `data/` is gitignored: a library export is personal listening history.
