"""The generators are only useful if track resolution stays honest."""
import os

import pytest

import config
from make_playlists import locate, safe_name


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

    from make_playlists import index_by_name

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
