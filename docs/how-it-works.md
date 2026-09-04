# How it works

Everything the [README](../README.md) leaves out.

## Finding your tracks

An iTunes library XML stores an absolute path per track, under whatever its
`Music Folder` key says. Three attempts, in order:

1. Rewrite that recorded prefix onto `local_root` and test the result.
2. Look the bare filename up across the library; accept a single unambiguous hit.
3. When several files share a name like `01 Track 1.mp3`, take the one whose byte
   size matches what the library recorded.

Anything left is counted and shown in the page with its reason, never guessed at.

On the one library this has run against — 174 playlists, 13,418 entries:

| | |
| --- | --- |
| 12,868 | found by prefix swap alone |
| 325 | found elsewhere by filename |
| 16 | disambiguated by byte size |
| 209 | genuinely not on the drive |

Step 1 is what other exporters do. Steps 2 and 3 found 341 more.

## Configuration

`config.toml` holds paths, and only paths. Everything else has one correct value
and is a named constant beside the code that uses it.

```toml
[music]
recorded_root = "/Users/you/Music/iTunes/iTunes Media/Music"   # what your XML says
local_root    = "/mnt/archive/Music"                           # where it is now
```

The port is not configurable. `serve.py` probes upward from 8000, so what it
lands on is decided by whatever is already listening.

## Playback

`GET /audio?i=<n>` streams a track with byte-range support, which is what makes
seeking work — Python's stock handler has none.

No decoder is involved. Browsers decode MP3 and AAC/M4A natively, which covers
most of a typical library. WAV, FLAC and the AAC variants get the right content
type but none has been tested here. AIFF is the usual holdout. Anything the
browser refuses shows `Cannot play` on that track, and the VLC button is the
fallback.

Both endpoints take **row numbers only, never paths**. The server maps them
through its own `paths.json`, which the page never receives, so neither can be
asked for a file outside your library. It binds to `127.0.0.1`.

## In the page

- Double-click a row to play. Prev/next, clickable scrubber, volume.
- Shuffle and repeat bottom-left, where iTunes kept them. Repeat cycles
  off → all → one.
- Sort by any column; search filters song, artist and album.
- **Play in VLC** hands over what is on screen, in the order shown.
- Missing tracks are greyed, with a `Found` column saying how each was located.
- Right-click the column headers for View Options — 29 library fields plus the
  derived `Found`.

## Skins

`BASE_TOKENS` holds every colour, shape and type value. Each skin is a set of
overrides; the stylesheet is generated from them, so the menu and the CSS cannot
disagree. Adding one means adding a `Skin(...)` entry.

Only eras that kept this layout are offered. iTunes 11 hid the sidebar and 12
moved to a tab bar; their colours on this layout would be a costume, not a skin.

Boring's palette was sampled from a Program Manager screenshot rather than
memory, which corrected this project's own first attempt — title bars are red
with yellow text, not the reverse. It parts company with the original on the
grey: every control here is red or yellow, with gradients the 16-colour palette
could not have produced.

## `tools/demangle.py`

Some archive copies arrive with every filename mangled — the real file saved
with `-2` appended, and an empty directory holding the name it wanted. A library
XML cannot resolve against a tree in that state.

```bash
python tools/demangle.py /path/to/music            # plan only, changes nothing
python tools/demangle.py /path/to/music --apply    # execute, journalling each rename
python tools/demangle.py --undo <journal>          # reverse it
```

It only acts on a pair whose target name is held by an **empty directory**, so a
file genuinely named `Track-2.mp3` is reported and skipped. `rmdir` clears the
placeholder and physically cannot remove a directory with anything in it. If the
plan holds any conflict, nothing runs at all. 14 tests cover those properties.

## Limits

- Regular playlists only. Smart playlists, the master library list and empty
  playlists are skipped.
- Tracks whose files are genuinely gone stay gone. Counted and shown, not
  invented.
- `data/` is gitignored. A library export is personal listening history.
