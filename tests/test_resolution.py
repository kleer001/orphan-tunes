"""The generators are only useful if track resolution stays honest."""
import os
import unicodedata
import urllib.parse

import pytest

import config
import make_playlists
from make_playlists import index_by_name, locate, safe_name


def _track(recorded):
    """A library entry whose Location spells its accents as e + combining mark."""
    nfd = unicodedata.normalize("NFD", recorded)
    return {"Location": "file://" + urllib.parse.quote(nfd)}


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(make_playlists, "RECORDED_ROOT", "/Users/you/Music")
    monkeypatch.setattr(make_playlists, "LOCAL_ROOT", str(tmp_path))
    return tmp_path


def test_locate_finds_an_accented_path_spelled_the_other_way(library):
    (library / "Björk").mkdir()
    (library / "Björk" / "Jóga.mp3").write_bytes(b"x")
    path, how = locate(_track("/Users/you/Music/Björk/Jóga.mp3"), index_by_name(library))
    assert (path, how) == (str(library / "Björk" / "Jóga.mp3"), "direct")


def test_locate_finds_a_moved_accented_name_spelled_the_other_way(library):
    (library / "Homogenic").mkdir()
    (library / "Homogenic" / "Jóga.mp3").write_bytes(b"x")
    path, how = locate(_track("/Users/you/Music/Björk/Jóga.mp3"), index_by_name(library))
    assert (path, how) == (str(library / "Homogenic" / "Jóga.mp3"), "moved")


def test_safe_name_strips_path_separators():
    taken = set()
    assert "/" not in safe_name("AC/DC mix", taken)


def test_safe_name_disambiguates_collisions():
    taken = set()
    first = safe_name("dupe", taken)
    assert safe_name("dupe", taken) != first


def test_safe_name_survives_a_title_that_is_all_punctuation():
    assert safe_name("...", set())


@pytest.mark.skipif(not os.path.isfile(config.LIBRARY),
                    reason="needs a library export in data/")
def test_locate_returns_a_real_file_or_nothing():
    import plistlib

    with open(config.LIBRARY, "rb") as fh:
        tracks = plistlib.load(fh)["Tracks"]
    index = index_by_name(config.LOCAL_ROOT)

    checked = 0
    for track in tracks.values():
        if not track.get("Location"):
            continue
        path, how = locate(track, index)
        # locate never invents a path: it returns one that exists, or None
        assert path is None or os.path.isfile(path), f"{how}: {path}"
        checked += 1
        if checked >= 400:
            break
    assert checked, "library had no locatable tracks"
