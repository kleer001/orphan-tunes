"""Seeking depends entirely on byte ranges being parsed correctly."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from serve import MIME, parse_range  # noqa: E402

SIZE = 1000


def test_plain_range():
    assert parse_range("bytes=0-99", SIZE) == (0, 99)
    assert parse_range("bytes=500-599", SIZE) == (500, 599)


def test_open_ended_range_runs_to_the_end():
    assert parse_range("bytes=900-", SIZE) == (900, 999)


def test_suffix_range_counts_back_from_the_end():
    assert parse_range("bytes=-100", SIZE) == (900, 999)
    # a suffix longer than the file is the whole file, not a negative offset
    assert parse_range("bytes=-5000", SIZE) == (0, 999)


def test_end_is_clamped_to_the_file():
    assert parse_range("bytes=0-99999", SIZE) == (0, 999)


def test_unsatisfiable_ranges_are_refused():
    assert parse_range("bytes=1000-", SIZE) is None      # starts past the end
    assert parse_range("bytes=900-800", SIZE) is None    # backwards
    assert parse_range("bytes=-0", SIZE) is None         # zero-length suffix


def test_malformed_headers_are_refused():
    for header in (None, "", "bytes=", "bytes=abc-def", "items=0-10",
                   "bytes=0-10, 20-30", "0-10"):
        assert parse_range(header, SIZE) is None, header


def test_every_audio_type_in_the_library_has_a_mime_type():
    # what build_browser is willing to index, the browser must be told how to decode
    for ext in (".mp3", ".m4a", ".wav", ".mp4", ".aif", ".aiff",
                ".mpga", ".m4b", ".flac", ".ogg", ".mov", ".m4v"):
        assert ext in MIME, ext


def test_aac_variants_are_served_as_mp4():
    # m4b and m4r are AAC under a different extension; the browser needs telling
    assert MIME[".m4b"] == "audio/mp4"
    assert MIME[".m4r"] == "audio/mp4"
