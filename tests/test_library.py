"""read_library() returns data now, so what it produces can be asserted."""

import datetime
import os

import pytest

import config
from build_browser import FIELDS, Library, cell, read_library


def test_cell_converts_milliseconds_to_whole_seconds():
    assert cell({"Total Time": 245678}, "Total Time", "time") == 246


def test_cell_renders_dates_so_they_sort_as_text():
    stamp = datetime.datetime(2018, 4, 21, 13, 5)
    assert cell({"Play Date UTC": stamp}, "Play Date UTC", "date") == "2018-04-21"


def test_cell_gives_a_missing_value_the_right_empty_for_its_kind():
    """Blank text reads as absent; a blank number would break totals."""
    assert cell({}, "Name", "text") == ""
    assert cell({}, "Play Date UTC", "date") == ""
    assert cell({}, "Total Time", "time") == 0
    assert cell({}, "Compilation", "bool") == 0


def test_cell_makes_booleans_numeric():
    assert cell({"Compilation": True}, "Compilation", "bool") == 1


def test_refs_counts_every_playlist_entry():
    lib = Library(tracks=[], paths=[], missing=0,
                  playlists=[{"name": "a", "ids": [1, 2]}, {"name": "b", "ids": [3]}])
    assert lib.refs == 3


@pytest.fixture(scope="module")
def library():
    """Parsed once: it walks 36,000 files and reads a 57 MB plist."""
    return read_library()


@pytest.mark.skipif(not os.path.isfile(config.LIBRARY),
                    reason="needs a library export in data/")
class TestAgainstTheRealLibrary:
    def test_paths_are_index_aligned_with_tracks(self, library):
        """The server maps a row number straight into paths; a skew would serve
        the wrong file."""
        assert len(library.paths) == len(library.tracks)

    def test_a_track_has_a_path_exactly_when_it_was_found(self, library):
        found = len(FIELDS)                     # the derived column sits last
        for row, path in zip(library.tracks, library.paths, strict=True):
            assert (path is not None) == (row[found] not in ("gone", "ambiguous"))

    def test_every_resolved_path_exists_on_disk(self, library):
        missing = [p for p in library.paths if p and not os.path.isfile(p)]
        assert not missing, missing[:3]

    def test_playlists_are_sorted_and_none_are_empty(self, library):
        names = [p["name"].lower() for p in library.playlists]
        assert names == sorted(names)
        assert all(p["ids"] for p in library.playlists)

    def test_every_id_indexes_into_the_pool(self, library):
        for playlist in library.playlists:
            for i in playlist["ids"]:
                assert 0 <= i < len(library.tracks)

    def test_missing_count_matches_the_unresolved_paths(self, library):
        unresolved = sum(1 for playlist in library.playlists
                         for i in playlist["ids"] if library.paths[i] is None)
        assert unresolved == library.missing
