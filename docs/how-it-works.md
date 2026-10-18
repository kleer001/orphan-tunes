# How it works

How orphan-tunes finds your files, writes the playlists, builds the page and
serves the music.

## Configuration

`config.toml` holds the paths that differ from one machine to the next. Other
settings are constants in the code. ffmpeg and VLC are found on your `PATH`.

```toml
library = "data/iTunes Music Library.xml"   # the file iTunes exported

[music]
recorded_root = "/Users/you/Music/iTunes/iTunes Media"   # where the XML says it was
local_root    = "/mnt/archive/iTunes Media"              # where it is now

[output]
playlists = "/mnt/archive/playlists"   # one .m3u8 per playlist
browser   = "/mnt/archive/browser"     # the page and its data
```

For `recorded_root`, open the library XML and take its `Music Folder` value.
Drop the `file://` at the front and the `/` at the end, and decode the
%-escapes, so `%20` becomes a space. A relative path is read against the folder
`config.toml` is in, wherever you run from.

`data/` is in `.gitignore`, because a library export is personal listening
history.

## Finding your tracks

The XML records each track's file as a `file://` URL. Decoded, that path normally
starts with `recorded_root`. Three attempts, in order:

1. Swap `recorded_root` at the start of the path for `local_root`, and test it.
2. Look the bare filename up across `local_root`, ignoring case. Take it if
   exactly one file has that name.
3. When several files share a name like `01 Track 1.mp3`, take the one whose
   byte size matches what the library recorded.

An accented letter like é can be one character, or an e followed by a separate
accent mark. The XML holds both spellings, and Linux compares names byte for
byte. So every name comparison here treats the two spellings as the same.

Step 2 trusts a lone match without checking its size. A track that fails all
three isn't found. So is one where several same-named files match the size, or
none do, and one with no file recorded at all.

On the one library this has run against, 174 playlists and 13,418 entries:

| Entries | How they were found |
| --- | --- |
| 12,986 | path swap alone |
| 283 | elsewhere, by filename |
| 2 | by filename, then byte size |
| 147 | not found |

An entry is one track in one playlist. Steps 2 and 3 found 285 entries that the
swap alone would have lost.

## Playlists

`python make_playlists.py` writes one `.m3u8` file per playlist into
`playlists`.

- Each entry is a path relative to the playlists folder.
- Tracks that weren't found are left out. A playlist with none found isn't
  written, and the run prints its name.
- Smart playlists (the ones iTunes fills from rules), built-in lists like
  Podcasts, and empty playlists are skipped.
- Characters a filesystem refuses, like `/` and `:`, become `_` in the filename.
  Two playlists with one name get ` (2)`, ` (3)` and so on.

## The page

`python build_browser.py` writes the page into `browser`: `index.html`, the
library in `data.js`, and the full file paths in `paths.json`, which only the
server reads.

Covers come from the artwork embedded in each file: ffmpeg pulls them out into
`art/`, and `art/art.json` records every result, "no picture" included. Each
cover is filed under its source file's path, so a rebuild skips files it has
already read. To pick up changed artwork, delete `art/`.

The page has three views.

**Songs** is the track table. Sort by any column, or search by song, artist or
album. Right-click the column headers for View Options: 29 library fields, plus
the `Found` column this tool adds. Ctrl+B (⌘B on a Mac) puts a column browser on
top, with Genre, Artist and Album panes.

**Albums** is a grid of covers, sorted by album artist and then album. iTunes'
Sort Album Artist and Sort Album fields win where the library has them, and a
leading "The" is ignored where it doesn't. Click a cover and its tracks open
under its row, on the cover's average colour. Double-click one to play the whole
album.

**Artists** lists every album artist. Compilations share one entry at the top.
Pick an artist to see their albums and tracks.

Ratings show as stars, from iTunes' 0 to 100 at 20 a star. Rate an album and not
its tracks, and iTunes gives each track the album's rating, flagged
`Rating Computed` in the XML. The page draws those stars hollow. Solid ones are
yours. They sort just below hand-set ratings of the same count.

- Right-click a track, album or artist for Play, Play Next and Add to Up Next.
  Up Next plays ahead of the list you started from.
- **Play in VLC** writes what's on screen, in the order shown, to
  `_now_playing.m3u8` in the page folder, and opens it in VLC.
- Missing tracks are greyed out. Switch on the `Found` column to see how each
  track was found, or why it wasn't.
- Your web browser saves your columns, skin, view, shuffle and repeat, for each
  address separately.
- `serve.py` takes the first free port from 8000 up. On a different port, the
  page opens with the defaults.

| Key | Does |
| --- | --- |
| Ctrl+F | search |
| Ctrl+B | column browser |
| Esc | close a menu, or the open album |
| letters | jump ahead: by song name or the sorted column in Songs, artist in Artists, album title in Albums |

## Playback

Opened straight from disk, `index.html` plays each track from a relative link in
`data.js`, and served by `serve.py` it asks the server for `/audio?i=<n>`
instead. The VLC button needs the server either way.

`/audio` answers byte-range requests with only the part of the file the player
asks for. That's what makes seeking work. Python's stock handler doesn't do it.
The server is threaded, so one long stream doesn't hold up the page.

`/audio` and `/play` take **row numbers, never paths**. The server looks them up
in its own `paths.json`, so no request from the page can name a file outside
your library. It listens on `127.0.0.1` only.

There's no decoder. Decoding is left to your web browser, and every major
browser plays MP3. Most play AAC. MDN (Mozilla's web docs) notes that Firefox
leans on the operating system for AAC, and plain Chromium builds leave it out.
By iTunes' own Kind field, MP3 is 89% of the tested library and AAC another
10%. The rest:

- An `.m4a` can hold Apple Lossless instead of AAC. MDN lists Apple Lossless as
  Safari-only. The tested library has none.
- Protected AAC (`.m4p`) carries Apple's copy protection, and nothing here
  removes it.
- WAV and FLAC are sent with the right audio type, but haven't been tested.
- AIFF gets no browser support in MDN's tables.

Anything your web browser refuses shows `Cannot play` on that track. Try the VLC
button for those.

## Skins

`BASE_TOKENS` in `build_browser.py` holds every colour, shape and type value.
Each skin in `SKINS` overrides some of them. The page's styles and the skin menu
are both built from `SKINS`, so they can't disagree.

Adding a skin means adding one `Skin(...)` entry. `tests/test_skins.py` fails a
skin that overrides a value the base doesn't define, or leaves its selected row
hard to read. It also fails one named for an iTunes era that changed this
layout: iTunes 11 hid the sidebar by default, and 12 dropped it.

## `tools/demangle.py`

One archive copy came out with every file renamed: `Track.mp3` saved as
`Track-2.mp3`, beside an empty directory called `Track.mp3`. A library XML can't
find anything in a tree like that. `demangle.py` puts the names back.

```bash
python tools/demangle.py /path/to/music            # plan only, changes nothing
python tools/demangle.py /path/to/music --apply    # rename, journalling each one
python tools/demangle.py --undo <journal>          # reverse it
```

It only renames a file when its real name is held by an empty directory. A file
really called `Track-2.mp3`, with no such twin, is left alone. `rmdir` removes
the placeholder, and it fails on a directory with anything in it.

If the plan finds one problem, nothing runs. A problem is a twin directory that
isn't empty (a `.DS_Store` is enough), a file already holding the real name, or
two files claiming one name. `tests/test_demangle.py` checks the first two
refusals, and that one problem stops the whole run.

## Limits

- It has run against one library, exported on a Mac and moved to Linux.
- A Windows export writes paths like `file://localhost/C:/...`. The path swap
  has never been tried on one.
- Tracks whose files are gone stay gone: counted and shown, never invented.
