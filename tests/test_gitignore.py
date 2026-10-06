"""Nothing derived from a personal music library may reach a public repo.

These are the files the tools actually write. demangle puts its plan and journal
in the working directory, which is the repo root if that is where you ran it,
and the plan lists every path in the library.
"""

import os
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GENERATED = [
    "data/iTunes Music Library.xml",
    "data/PROVENANCE.md",
    "demangle-plan.tsv",
    "demangle-journal-20260101-000000.jsonl",
    "paths.json",
    "data.js",
    "index.html",
    "_now_playing.m3u8",
    "Some Playlist.m3u8",
]

SOURCE = [
    "build_browser.py", "make_playlists.py", "serve.py", "config.py",
    "config.toml", "tools/demangle.py", "README.md", "CLAUDE.md",
    "tests/test_gitignore.py",
]


def ignored(path):
    return subprocess.run(["git", "check-ignore", "-q", path],
                          cwd=REPO).returncode == 0


def test_everything_derived_from_the_library_is_ignored():
    leaked = [p for p in GENERATED if not ignored(p)]
    assert not leaked, f"would be committed: {leaked}"


def test_the_source_is_still_committable():
    hidden = [p for p in SOURCE if ignored(p)]
    assert not hidden, f"wrongly ignored: {hidden}"


def test_nothing_from_data_is_tracked():
    out = subprocess.run(["git", "ls-files", "data/"], cwd=REPO,
                         capture_output=True, text=True).stdout.strip()
    assert not out, f"tracked under data/: {out}"


def test_no_library_export_appears_anywhere_in_history():
    out = subprocess.run(["git", "log", "--all", "--pretty=format:", "--name-only"],
                         cwd=REPO, capture_output=True, text=True).stdout
    offenders = [ln for ln in out.splitlines()
                 if ln.startswith("data/") or ln.lower().endswith((".xml", ".m3u8"))]
    assert not offenders, f"committed at some point: {sorted(set(offenders))}"
