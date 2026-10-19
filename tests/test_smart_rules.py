"""The converter from itunessmart's rule tree to the page's flat rule format."""

import os
import plistlib

import pytest

import config
from build_browser import FIELDS
from smart_rules import MUSIC_FILTER, Unflattenable, convert, decode

LABELS = {label for _, label, _, _ in FIELDS}


def rule(field, operator, value, kind="string", **extra):
    return {"field": field, "type": kind, "operator": operator, "value": value, **extra}


def tree(root, **limit):
    return {"fulltree": root, "onlychecked": False, **limit}


MUSIC = {"or": [rule("MediaKind", "is", "Music", "mediakind"),
                rule("MediaKind", "is", "Music Video", "mediakind")]}


def test_the_hidden_music_filter_becomes_one_rule():
    """iTunes adds it to every smart playlist made in the Music section."""
    got = convert(tree({"and": [MUSIC, {"and": [rule("Composer", "like", "Bach")]}]}))
    assert got["match"] == "all"
    assert got["rules"] == [MUSIC_FILTER,
                            {"field": "Composer", "op": "contains", "value": "Bach"}]


def test_a_one_rule_group_joins_its_parent_whatever_its_join():
    got = convert(tree({"and": [{"or": [rule("MediaKind", "is", "Podcast", "mediakind")]},
                                {"and": [rule("Plays", "is", 0, "int")]}]}))
    assert got["rules"] == [{"field": "Media Kind", "op": "is", "value": "Podcast"},
                            {"field": "Plays", "op": "is", "value": 0}]


def test_mixed_all_and_any_is_refused():
    """The flat editor holds one join for the whole list."""
    with pytest.raises(Unflattenable):
        convert(tree({"and": [rule("Genre", "is", "Jazz"),
                              {"or": [rule("Plays", "is", 0, "int"),
                                      rule("Plays", "is", 1, "int")]}]}))


def test_a_field_with_no_column_is_refused():
    with pytest.raises(Unflattenable):
        convert(tree({"and": [rule("Show", "is", "News")]}))


def test_itunessmarts_sort_direction_is_turned_the_right_way_round():
    """itunessmart 1.2.0 decodes a saved "most recently played" as "least".
    The saved track lists in an iTunes 12.8 export settle which is right."""
    for order, by in (("LastPlayed ASC", "most recently played"),
                      ("LastPlayed DESC", "least recently played"),
                      ("Plays ASC", "most often played"),
                      ("DateAdded ASC", "most recently added")):
        got = convert(tree({}, number=50, type="Items", order=order))
        assert got["limit"] == {"count": 50, "unit": "items", "by": by}


def test_durations_become_seconds_like_the_time_column():
    got = convert(tree({"and": [rule("Duration", "less than", 2400000, "int")]}))
    assert got["rules"][0] == {"field": "Time", "op": "less than", "value": 2400}


def test_a_relative_date_keeps_its_count_and_unit():
    got = convert(tree({"and": [rule("LastPlayed", "is not in the last", 63072000, "date",
                                     value_date="24 months")]}))
    assert got["rules"][0]["value"] == {"n": 24, "unit": "months"}


def test_a_range_becomes_a_pair():
    got = convert(tree({"and": [rule("Rating", "between", (3, 4), "int")]}))
    assert got["rules"][0] == {"field": "Rating", "op": "in range", "value": [3, 4]}


def smart_playlists():
    with open(config.LIBRARY, "rb") as fh:
        lib = plistlib.load(fh)
    return [p for p in lib["Playlists"]
            if "Smart Info" in p and not p.get("Distinguished Kind")]


@pytest.mark.skipif(not os.path.isfile(config.LIBRARY),
                    reason="needs a library export in data/")
def test_every_smart_playlist_in_the_library_converts_onto_real_columns():
    for playlist in smart_playlists():
        text, rules, why = decode(playlist["Smart Info"], playlist["Smart Criteria"])
        assert rules is not None, (playlist["Name"], why)
        assert {r["field"] for r in rules["rules"]} <= LABELS, playlist["Name"]
        if rules["limit"]:
            assert rules["limit"]["by"] in text, (playlist["Name"], text)
