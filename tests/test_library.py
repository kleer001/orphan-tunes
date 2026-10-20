"""read_library() returns data now, so what it produces can be asserted."""

import datetime
import json
import os
import shutil
import subprocess

import pytest

import build_browser
import config
from build_browser import (
    COMPILATIONS,
    FIELDS,
    Album,
    Library,
    album_of,
    cell,
    extract_art,
    file_sections,
    group_albums,
    write_data,
)


def test_cell_converts_milliseconds_to_whole_seconds():
    assert cell({"Total Time": 245678}, "Total Time", "time") == 246


def test_cell_renders_dates_so_they_sort_as_text():
    stamp = datetime.datetime(2018, 4, 21, 13, 5)
    assert cell({"Play Date UTC": stamp}, "Play Date UTC", "date") == "2018-04-21 13:05:00"


def test_media_kind_comes_from_the_built_in_section_lists():
    """An MP3 iTunes filed as an audiobook looks like music in every key it
    has; only the built-in Audiobooks list says otherwise."""
    lib = {"Tracks": {"1": {}, "2": {}, "3": {}, "4": {}},
           "Playlists": [
               {"Name": "Music", "Distinguished Kind": 4, "Playlist Items": [{"Track ID": 1}]},
               {"Name": "Audiobooks", "Distinguished Kind": 5,
                "Playlist Items": [{"Track ID": 2}]},
               {"Name": "Podcasts", "Distinguished Kind": 10,
                "Playlist Items": [{"Track ID": 3}]},
               {"Name": "mine", "Playlist Items": [{"Track ID": 4}]}]}
    file_sections(lib)
    kinds = [cell(lib["Tracks"][k], "Media Kind", "text") for k in "1234"]
    assert kinds == ["Music", "Audiobook", "Podcast", ""]


def test_a_track_is_checked_unless_itunes_marked_it_disabled():
    assert cell({}, "Checked", "bool") == 1
    assert cell({"Disabled": True}, "Checked", "bool") == 0


def test_cell_gives_a_missing_value_the_right_empty_for_its_kind():
    """Blank text reads as absent; a blank number would break totals."""
    assert cell({}, "Name", "text") == ""
    assert cell({}, "Play Date UTC", "date") == ""
    assert cell({}, "Total Time", "time") == 0
    assert cell({}, "Compilation", "bool") == 0


def test_cell_makes_booleans_numeric():
    assert cell({"Compilation": True}, "Compilation", "bool") == 1


def test_cell_marks_a_computed_rating_half_a_point_low_so_the_page_can_draw_it_hollow():
    assert cell({"Rating": 60}, "Rating", "star") == 60
    assert cell({"Rating": 60, "Rating Computed": True}, "Rating", "star") == 59.5
    assert cell({"Album Rating": 80, "Album Rating Computed": True},
                "Album Rating", "star") == 79.5


def test_refs_counts_every_playlist_entry():
    lib = Library(tracks=[], paths=[], pids=[], missing=0, music=[], audiobooks=[], albums=[],
                  exported="", playlists=[{"name": "a", "ids": [1, 2]}, {"name": "b", "ids": [3]}])
    assert lib.refs == 3


def test_page_data_is_a_script_so_the_page_opens_from_disk(tmp_path):
    """Firefox blocks fetch() between file:// pages, which left the page blank."""
    lib = Library(tracks=[["Song"]], paths=["/m/song.mp3"], pids=["A1"], missing=0, music=[],
                  audiobooks=[], albums=[], exported="2020-02-09 22:28:50",
                  playlists=[{"name": "a", "ids": [0]}])
    write_data(lib, tmp_path, {})
    text = (tmp_path / "data.js").read_text(encoding="utf-8")
    assert text.startswith("const LIBRARY=") and text.endswith(";\n")
    data = json.loads(text[len("const LIBRARY="):-2])
    assert data["playlists"] == lib.playlists
    assert data["pids"] == ["A1"] and data["exported"] == lib.exported


def test_page_gets_a_quoted_relative_url_for_each_found_track(tmp_path):
    """Opened from disk the page plays these directly; an unquoted "#" or "%"
    in a filename would break the URL."""
    song = tmp_path / "music" / "51%sincere" / "Mix #1.mp3"
    lib = Library(tracks=[["a"], ["b"]], paths=[str(song), None], pids=["A", "B"], missing=1,
                  music=[], audiobooks=[], albums=[], exported="",
                  playlists=[{"name": "a", "ids": [0, 1]}])
    out = tmp_path / "browser"
    out.mkdir()
    write_data(lib, out, {})
    text = (out / "data.js").read_text(encoding="utf-8")
    data = json.loads(text[len("const LIBRARY="):-2])
    assert data["files"] == ["../music/51%25sincere/Mix%20%231.mp3", None]


@pytest.mark.skipif(not os.path.isfile(config.LIBRARY),
                    reason="needs a library export in data/")
class TestAgainstTheRealLibrary:
    def test_paths_are_index_aligned_with_tracks(self, library):
        """The server maps a row number straight into paths; a skew would serve
        the wrong file."""
        assert len(library.paths) == len(library.tracks) == len(library.pids)

    def test_persistent_ids_are_unique(self, library):
        """Plays and ratings are stored against them."""
        assert len(set(library.pids)) == len(library.pids)

    def test_the_pool_holds_podcasts_but_the_library_source_does_not(self, library):
        kind = [label for _, label, _, _ in FIELDS].index("Media Kind")
        assert any(row[kind] == "Podcast" for row in library.tracks)
        assert all(library.tracks[i][kind] == "Music" for i in library.music)
        assert all(library.tracks[i][kind] == "Audiobook" for i in library.audiobooks)
        assert library.audiobooks and not set(library.music) & set(library.audiobooks)

    def test_a_track_has_a_path_exactly_when_it_was_found(self, library):
        found = len(FIELDS)                     # the derived column sits last
        for row, path in zip(library.tracks, library.paths, strict=True):
            assert (path is not None) == (row[found] not in ("gone", "ambiguous"))

    def test_every_resolved_path_exists_on_disk(self, library):
        missing = [p for p in library.paths if p and not os.path.isfile(p)]
        assert not missing, missing[:3]

    def test_playlists_are_sorted_and_only_smart_ones_are_empty(self, library):
        """A smart playlist is kept empty: its rules can still be copied."""
        names = [p["name"].lower() for p in library.playlists]
        assert names == sorted(names)
        assert all(p["ids"] or "smart" in p for p in library.playlists)

    def test_smart_playlists_carry_their_saved_list_and_rules(self, library):
        smart = [p for p in library.playlists if "smart" in p]
        assert smart and all(p["smart"]["text"] for p in smart)
        assert any(p["ids"] and p["smart"]["rules"] for p in smart)

    def test_every_id_indexes_into_the_pool(self, library):
        for playlist in library.playlists:
            for i in playlist["ids"]:
                assert 0 <= i < len(library.tracks)

    def test_missing_count_matches_the_unresolved_paths(self, library):
        unresolved = sum(1 for playlist in library.playlists
                         for i in playlist["ids"] if library.paths[i] is None)
        assert unresolved == library.missing


def test_compilations_are_pooled_under_one_artist():
    """Otherwise each guest artist on a compilation gets an entry of their own."""
    track = {"Compilation": True, "Artist": "Guest", "Album": "Hits"}
    assert album_of(track)[:2] == (COMPILATIONS, "Hits")


def test_album_artist_wins_over_artist():
    track = {"Album Artist": "Band", "Artist": "Band feat. Guest", "Album": "LP"}
    assert album_of(track)[0] == "Band"


def test_artists_sort_without_a_leading_the_unless_itunes_kept_a_sort_key():
    assert album_of({"Artist": "The Decemberists"})[2] == "decemberists"
    assert album_of({"Artist": "The The", "Sort Artist": "The The"})[2] == "the"
    assert album_of({"Artist": "Prince", "Sort Artist": "Artist Formerly"})[2] \
        == "artist formerly"


def test_albums_sort_by_artist_then_title_and_tracks_by_disc_then_number():
    raw = [
        {"Artist": "B", "Album": "Two", "Track Number": 2},
        {"Artist": "B", "Album": "Two", "Track Number": 1, "Disc Number": 2},
        {"Artist": "B", "Album": "Two", "Track Number": 9, "Disc Number": 1},
        {"Artist": "A", "Album": "One"},
        {"Compilation": True, "Artist": "Z", "Album": "Mix"},
    ]
    albums = group_albums(raw, [None] * len(raw))
    assert [(a.artist, a.title) for a in albums] == \
        [(COMPILATIONS, "Mix"), ("A", "One"), ("B", "Two")]
    assert albums[2].ids == [0, 2, 1]


def test_an_album_takes_its_cover_from_a_found_track_that_has_artwork():
    raw = [{"Album": "X", "Artwork Count": 1},          # has art, but not on disk
           {"Album": "X"},                              # on disk, but no art
           {"Album": "X", "Artwork Count": 1}]
    albums = group_albums(raw, [None, "/m/b.mp3", "/m/c.mp3"])
    assert albums[0].art_from == "/m/c.mp3"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_covers_are_extracted_once_and_then_read_from_the_cache(tmp_path, monkeypatch):
    song = tmp_path / "song.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=d=0.2",
                    "-f", "lavfi", "-i", "color=c=0xff0000:s=32x32:d=0.1",
                    "-map", "0:a", "-map", "1:v", "-frames:v", "1", "-c:v", "mjpeg",
                    "-disposition:v", "attached_pic", str(song)], check=True)
    albums = [Album("X", "A", 0, [0], str(song)), Album("Y", "A", 0, [1], "")]
    art = extract_art(albums, tmp_path)
    assert list(art) == [0], "only the album with a cover gets one"
    url, colour = art[0]
    assert (tmp_path / url).is_file()
    assert int(colour[1:3], 16) > 200 > int(colour[3:5], 16), colour   # red

    def refuse(*_):
        raise AssertionError("ran ffmpeg for a cover already in the cache")
    monkeypatch.setattr(build_browser, "extract_cover", refuse)
    assert extract_art(albums, tmp_path) == art


def test_the_page_loads_the_evaluator_before_the_page_script(tmp_path):
    build_browser.write_page(tmp_path, 0, 0)
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert html.index('src="smart.js"') < html.index('src="app.js"')
    assert (tmp_path / "smart.js").read_text() == build_browser.read_static("smart.js")
