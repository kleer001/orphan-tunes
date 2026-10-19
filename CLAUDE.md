# orphan-tunes

Rebuilds playable playlists and a browsable iTunes-4-style page from an exported
`iTunes Music Library.xml` plus the local audio files. Local only — no network.

## Quick commands

- Activate env: `source .venv/bin/activate`
- Install deps: `pip install -e ".[dev]"`
- Write playlists: `python make_playlists.py`
- Build the page: `python build_browser.py`
- Serve it: `python serve.py` (directory and port from `config.toml`)
- Lint/format: `ruff check . && ruff format .`

## Project structure

- `config.py` / `config.toml` — every machine-specific path. Nothing else should
  hardcode one.
- `make_playlists.py` — library XML → `.m3u8` files. Owns `locate()` (find a
  track on disk) and `safe_name()` (playlist title → filename).
- `build_browser.py` — library XML → `index.html`, `data.js`, `paths.json`,
  plus `style.css` (skins + `static/layout.css`) and `app.js` (from `static/`).
  Album covers are pulled from embedded artwork with `ffmpeg` into `art/` in the
  output directory; `art/art.json` caches every result so rebuilds are quick.
  Imports `locate` and `safe_name` rather than reimplementing them; if track
  resolution changes, it changes in one place.
- `serve.py` — static server plus `POST /play`, and `GET`/`POST /state`: the
  plays, ratings and page-made smart playlists, kept in the `state` file that
  `config.toml` names and keyed by track Persistent ID.
- `smart_rules.py` — iTunes smart playlist rules (decoded by `itunessmart`) →
  the flat all/any rule format the page evaluates and edits.
- `tools/demangle.py` — standalone archive repair, unrelated to the browser. It
  takes its root as a required argument and never reads `config.toml`: this
  renames files, and a destructive tool that runs with no arguments is one
  keystroke from being pointed at the wrong tree.

## What belongs in config.toml

Paths. That is the whole list, and it is allowed to stay that short.

Paths earn their place because they genuinely differ per machine and the tool
cannot run without knowing them. Nothing else has qualified. The port looked
like a candidate and is not: the server probes upward from a starting point, so
what it ends up on is decided by whatever is already listening, and a stored
preference would not change the outcome. Values like the streaming chunk size,
the rating-to-stars divisor or the progress interval each have one correct
value; naming them beside the code that uses them says more than a config entry
would, and does not invite tuning what should not be tuned.

## Track resolution

Three steps, in order, in `locate()`:

1. Rewrite the XML's recorded path prefix to `local_root` and test it. A file
   at that path in the other Unicode spelling (NFC or NFD) also counts: the XML
   holds both, and Linux compares names byte for byte.
2. Failing that, look the bare filename up across the library, ignoring case and
   Unicode spelling; accept a single unambiguous hit.
3. Failing that, when several files share the name, take the one whose byte size
   matches the `Size` the library recorded.

Anything still unresolved is counted and reported. Never guess a track.

## Playback

Opened from disk, the page plays each track from `files` in `data.js`: a
percent-encoded URL relative to the page, the same relative form the `.m3u8`
files use. Served over http, it asks `/audio?i=<n>` instead, because an http
page cannot load a `file://` URL.

`/audio?i=<n>` serves one track. Byte-range support is hand-rolled because
`SimpleHTTPRequestHandler` has none, and without it seeking silently fails. The
server must stay threaded: single-threaded, streaming a track blocks every other
request including the page itself.

Decoding is the browser's job. Do not add a decoder — `<audio>` handles MP3,
AAC/M4A, WAV and FLAC natively. The server's only responsibility is correct
`Content-Type`, `Accept-Ranges`, `Content-Range` and status (206 vs 200 vs 416).

The queue is whatever rows are on screen, in the order shown, minus unresolved
ones. Sorting or filtering the table changes what plays next.

## The /play endpoint

The page posts `{name, indices}` — row numbers into the track pool, never paths.
The server maps them through its own `paths.json`, never through anything the
page sends, then writes `_now_playing.m3u8` and launches VLC. Indices outside the pool are
rejected. Keep it that way: any change that lets the page name a path directly
turns a local convenience into an arbitrary-file-open.

`SIGCHLD` is set to `SIG_IGN` so launched VLC processes are reaped; without it
every click leaves a zombie.

## Skins

`BASE_TOKENS` holds every colour, shape and type value; `SKINS` is a list of
`Skin(id, label, era, tokens)`, the first of which is the base and carries no
overrides. `render_skins()` turns those into `:root` plus one `[data-skin]`
block each, and the page receives the list as JSON — so the menu and the
stylesheet cannot disagree, and a skin cannot name a token that does not exist.

Adding one means adding a `Skin(...)` entry. Nothing else.

Tests read `BASE_TOKENS`, `SKINS` and `REPEAT_CYCLE` directly. Do not go back to
parsing the generated CSS or page script: a regex looking for three-string
arrays once matched an unrelated `["off","all","one"]` and reported it as a
skin, and a declaration splitter that ignored comments failed a skin for having
one. Both were the test being wrong about working code.

## Column data

`FIELDS` in `build_browser.py` is the single list of what gets carried out of the
library and how it renders. The fourth element is whether a column shows by
default; everything else is reachable from View Options. Adding a field means
adding one row there — the page builds its columns from the data.

Only genuine plumbing is excluded: `Track ID`, `Persistent ID`, `Location`,
`Track Type`, the folder-count pair, the `Sort *` keys, the `* Computed` flags.

## demangle's safety properties

All four are covered by `tests/test_demangle.py` and are the point of the tool:

1. Only acts when the target name is held by an *empty* directory.
2. `rmdir` clears the placeholder, so nothing with content can be removed.
3. `os.rename` (never `mv`) — it fails rather than moving a file *into* a
   directory.
4. All-or-nothing: any conflict in the plan means no renames at all.

The journal is the only undo, so it is opened `"x"` under a timestamped name; a
second run must never truncate an earlier one. That regression shipped once and
now has three tests on it.

## Testing

Tests live in `tests/`. The generators are verifiable against real output: track
counts, resolution rates, and the `.m3u8` line count should match what the
scripts report. When changing layout, measure the DOM rather than judging from a
screenshot — column widths and scroll behaviour are easy to misread by eye.

Tests on destructive behaviour are worth mutating to check they bite: break a
guard on purpose and confirm the suite fails. One test here passed against a
broken build because the crash message happened to contain the string it matched
for, which is why the refusal tests now assert on `REFUSING TO RUN` and the
absence of a traceback.

## Code style

- `ruff` is the linter and formatter — config in `pyproject.toml`.
- Naming: `snake_case` functions/vars, `PascalCase` classes.
- Imports: stdlib → third-party → local.
- Comments: explain *why*, not *what*.
- Requires Python 3.11+ (`tomllib`).

## Boundaries

- Don't touch `.scaffold.json` by hand.
- `data/` is gitignored and holds personal listening history. Never commit it.
- These scripts only ever read the music library. Nothing here renames, moves,
  or deletes audio.
