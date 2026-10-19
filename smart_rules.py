#!/usr/bin/env python3
"""
iTunes smart playlist rules, decoded and turned into the page's rule format.

itunessmart reads the binary Smart Info and Smart Criteria blobs. This module
turns its rule tree into the flat form the page evaluates and edits:

    {"match": "all" | "any",
     "rules": [{"field": <column label>, "op": <operator>, "value": ...}],
     "limit": {"count": n, "unit": "items" | "minutes" | "hours" | "MB" | "GB",
               "by": <selection>} or None,
     "checkedOnly": bool}

Values are in the units the page's columns hold: stars for Rating, seconds for
Time, "YYYY-MM-DD" for a fixed date, and {"n", "unit"} for "in the last".
"""

import datetime
import re

from itunessmart.parse import SmartPlaylistParser


class Unflattenable(Exception):
    """A rule the flat editor cannot hold: a mixed and/or group, or a field,
    operator or value the page has no column or test for."""


# itunessmart field name -> the page's column label, for fields whose values
# are in the same units on both sides (Duration aside, converted below).
FIELD = {
    "Album": "Album", "AlbumArtist": "Album Artist", "Artist": "Artist",
    "Comments": "Comments", "Composer": "Composer", "Genre": "Genre",
    "Grouping": "Grouping", "Kind": "Kind", "Name": "Song Name",
    "BPM": "BPM", "BitRate": "Bit Rate", "DiskNumber": "Disc", "Plays": "Plays",
    "Rating": "Rating", "SampleRate": "Sample Rate", "Skips": "Skips",
    "Duration": "Time", "TrackNumber": "#", "Year": "Year",
    "Checked": "Checked",
    "DateAdded": "Date Added", "DateModified": "Date Modified",
    "LastPlayed": "Last Played", "LastSkipped": "Last Skipped",
    "MediaKind": "Media Kind",
}

STRING_OP = {"is": "is", "is not": "is not", "like": "contains",
             "not like": "does not contain", "starts with": "starts with",
             "ends with": "ends with"}
INT_OP = {"is": "is", "is not": "is not", "greater than": "greater than",
          "less than": "less than", "between": "in range"}
DATE_OP = {"is in the last": "in the last", "is not in the last": "not in the last",
           "is after": "is after", "is before": "is before"}

# The page's Media Kind column, from build_browser.media_kind().
MEDIA_KINDS = {"Music", "Podcast", "Movie", "TV Show"}
# iTunes adds "Media Kind is Music or Music Video" to every smart playlist made
# in the Music section, and hides it from the rule editor. The page files music
# videos under Music, so the pair is one rule here.
MUSIC_FILTER = {"field": "Media Kind", "op": "is", "value": "Music"}

UNIT = {"Items": "items", "Minutes": "minutes", "Hours": "hours", "MB": "MB", "GB": "GB"}

# itunessmart 1.2.0 reads the most/least byte the wrong way round for these
# three: a list iTunes saved as "most recently played" decodes as "least".
# Checked against the track lists in an iTunes 12.8 export.
BY = {
    "RANDOM()": "random", "SortName": "name", "SortAlbum": "album",
    "SortArtist": "artist", "Genre": "genre",
    "Rating DESC": "highest rating", "Rating ASC": "lowest rating",
    "LastPlayed ASC": "most recently played", "LastPlayed DESC": "least recently played",
    "Plays ASC": "most often played", "Plays DESC": "least often played",
    "DateAdded ASC": "most recently added", "DateAdded DESC": "least recently added",
}


FLIP = {"most": "least", "least": "most"}


def leaf(node):
    """One itunessmart rule -> one page rule."""
    field = FIELD.get(node["field"])
    if field is None:
        raise Unflattenable(f"no column for {node['field']}")
    op, value, kind = node["operator"], node.get("value"), node["type"]

    if kind == "string":
        return {"field": field, "op": STRING_OP[op], "value": value}
    if kind == "mediakind":
        if value not in MEDIA_KINDS:
            raise Unflattenable(f"no Media Kind {value}")
        return {"field": field, "op": INT_OP[op], "value": value}
    if kind == "boolean":
        return {"field": field, "op": "is", "value": value}
    if kind == "int":
        if op not in INT_OP:
            raise Unflattenable(f"no operator {op}")
        if field == "Time":                 # iTunes counts milliseconds
            value = [v / 1000 for v in value] if op == "between" else value / 1000
        return {"field": field, "op": INT_OP[op],
                "value": list(value) if op == "between" else value}
    if kind == "date" and op in DATE_OP:
        if op in ("is after", "is before"):
            day = datetime.datetime.fromtimestamp(value, datetime.UTC)
            return {"field": field, "op": DATE_OP[op], "value": day.strftime("%Y-%m-%d")}
        n, unit = node["value_date"].split()
        if unit not in ("days", "weeks", "months"):
            raise Unflattenable(f"no time unit {unit}")
        return {"field": field, "op": DATE_OP[op], "value": {"n": int(n), "unit": unit}}
    raise Unflattenable(f"no test for {node['field']} {op}")


def is_music_filter(group):
    (op, kids), = group.items()
    return op == "or" and sorted(k.get("value", "") for k in kids) == ["Music", "Music Video"] \
        and all(k.get("field") == "MediaKind" and k.get("operator") == "is" for k in kids)


def flatten(group, match):
    """The rules under one and/or group, as a single list matched by `match`.
    A sub-group joins its parent when it has one rule or the same join."""
    (_, kids), = group.items()
    rules = []
    for kid in kids:
        if "field" in kid:
            rules.append(leaf(kid))
            continue
        if is_music_filter(kid):
            rules.append(dict(MUSIC_FILTER))
            continue
        (op, sub), = kid.items()
        if len(sub) > 1 and op != match:
            raise Unflattenable("mixes all and any")
        rules.extend(flatten(kid, match))
    return rules


def convert(tree):
    """itunessmart's full tree -> the page's rule format."""
    root = tree["fulltree"]
    match = "and"
    rules = []
    if root:
        (match, _), = root.items()
        rules = flatten(root, match)
    limit = None
    if "number" in tree:
        if tree["order"] not in BY:
            raise Unflattenable(f"no selection {tree['order']}")
        limit = {"count": tree["number"], "unit": UNIT[tree["type"]], "by": BY[tree["order"]]}
    return {"match": "all" if match == "and" else "any", "rules": rules,
            "limit": limit, "checkedOnly": tree["onlychecked"]}


def decode(info, criteria):
    """(rules as iTunes words them, rules in the page's format or None, why None)."""
    parser = SmartPlaylistParser()
    parser.data(info, criteria)
    parser.parse()
    text = re.sub(r"selected by (most|least) (recently|often)",
                  lambda m: f"selected by {FLIP[m[1]]} {m[2]}", parser.output)
    try:
        return text, convert(parser.fullTree), ""
    except Unflattenable as why:
        return text, None, str(why)
