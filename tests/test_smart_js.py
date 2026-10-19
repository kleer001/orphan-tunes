"""static/smart.js, the rule evaluator, run in Node.

The unit tests use a small pool built here. The oracle tests run the decoded
rules of each iTunes smart playlist against the real library, with "now" set to
the export date, and compare the result with the list iTunes saved.
"""

import datetime
import json
import os
import shutil
import subprocess

import pytest

import config
from build_browser import FIELDS, STATIC

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="needs node")

SMART = os.path.join(STATIC, "smart.js")
PAGE_FIELDS = [[label, kind, show] for _, label, kind, show in FIELDS] + [["Found", "found", False]]
COL = {f[0]: i for i, f in enumerate(PAGE_FIELDS)}

# Reads one job from stdin, or a list of jobs from a file, and prints the picks.
RUNNER = """
const Smart=require(process.argv[1]);
const fs=require("fs");
const job=JSON.parse(fs.readFileSync(process.argv[2]||0,"utf8"));
const run=j=>Smart.evaluate(j.rules,job.tracks,job.fields,job.ids,{now:job.now,seed:j.seed});
console.log(JSON.stringify(job.jobs?job.jobs.map(run):run(job)));
"""


def node(job, path=None):
    args = [NODE, "-e", RUNNER, SMART] + ([path] if path else [])
    out = subprocess.run(args, input=None if path else json.dumps(job),
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def track(**values):
    """A pool row with every column empty except the ones given, by label."""
    row = [0 if kind not in ("text", "date") else "" for _, kind, _ in PAGE_FIELDS]
    row[COL["Checked"]] = 1
    row[COL["Media Kind"]] = "Music"
    for label, value in values.items():
        row[COL[label.replace("_", " ")]] = value
    return row


def pick(tracks, *rules, match="all", limit=None, checked=False, now="2020-02-09 22:28:50",
         seed=1):
    job = {"rules": {"match": match, "rules": [dict(zip(("field", "op", "value"), r, strict=True))
                                               for r in rules],
                     "limit": limit, "checkedOnly": checked},
           "tracks": tracks, "fields": PAGE_FIELDS, "ids": list(range(len(tracks))),
           "now": _ms(now), "seed": seed}
    return node(job)


def _ms(stamp):
    when = datetime.datetime.fromisoformat(stamp).replace(tzinfo=datetime.UTC)
    return when.timestamp() * 1000


NAMES = [track(Song_Name="Blue in Green", Artist="Miles Davis"),
         track(Song_Name="So What", Artist="miles davis"),
         track(Song_Name="Naima", Artist="John Coltrane")]


@pytest.mark.parametrize("op,value,expected", [
    ("is", "MILES DAVIS", [0, 1]),
    ("is not", "Miles Davis", [2]),
    ("contains", "davis", [0, 1]),
    ("does not contain", "davis", [2]),
    ("starts with", "john", [2]),
    ("ends with", "trane", [2]),
])
def test_text_rules_ignore_case(op, value, expected):
    assert pick(NAMES, ("Artist", op, value)) == expected


PLAYS = [track(Plays=0), track(Plays=5), track(Plays=10)]


@pytest.mark.parametrize("op,value,expected", [
    ("is", 5, [1]), ("is not", 5, [0, 2]), ("greater than", 4, [1, 2]),
    ("less than", 5, [0]), ("in range", [5, 10], [1, 2]),
])
def test_number_rules(op, value, expected):
    assert pick(PLAYS, ("Plays", op, value)) == expected


def test_a_size_rule_reads_megabytes_and_a_rating_rule_reads_stars():
    tracks = [track(Size=3 * 1024 * 1024, Rating=80), track(Size=1024 * 1024, Rating=40)]
    assert pick(tracks, ("Size", "greater than", 2)) == [0]
    assert pick(tracks, ("Rating", "is", 4)) == [0]


def test_a_computed_rating_counts_only_from_a_hand_set_album_rating():
    """iTunes 12.8's saved lists hold a track whose rating came from an album
    rating set by hand, and leave out one whose album rating it worked out."""
    tracks = [track(Rating=79.5, Album_Rating=80),      # album rated by hand
              track(Rating=79.5, Album_Rating=79.5),    # album rating worked out too
              track(Rating=80)]
    assert pick(tracks, ("Rating", "is", 4)) == [0, 2]


DATES = [track(Last_Played="2020-02-01 10:00:00"), track(Last_Played="2017-06-01 10:00:00"),
         track(Last_Played="")]


@pytest.mark.parametrize("op,value,expected", [
    ("is after", "2019-12-31", [0]),
    ("is before", "2019-12-31", [1]),
    ("in the last", {"n": 2, "unit": "weeks"}, [0]),
    ("not in the last", {"n": 24, "unit": "months"}, [1, 2]),
])
def test_date_rules_and_a_track_never_played(op, value, expected):
    """A track never played is in no date range, so it is "not in the last"."""
    assert pick(DATES, ("Last Played", op, value)) == expected


def test_a_boolean_rule_and_only_checked():
    tracks = [track(Compilation=1), track(Compilation=0, Checked=0)]
    assert pick(tracks, ("Compilation", "is", True)) == [0]
    assert pick(tracks, ("Compilation", "is", False)) == [1]
    assert pick(tracks, checked=True) == [0]


def test_any_matches_one_rule_and_no_rules_match_everything():
    assert pick(NAMES, ("Song Name", "is", "Naima"), ("Song Name", "is", "So What"),
                match="any") == [1, 2]
    assert pick(NAMES) == [0, 1, 2]


def test_a_limit_orders_then_cuts():
    assert pick(PLAYS, limit={"count": 2, "unit": "items", "by": "most often played"}) == [2, 1]
    assert pick(DATES, limit={"count": 2, "unit": "items",
                              "by": "least recently played"}) == [2, 1]


def test_a_size_limit_stops_at_the_first_track_that_does_not_fit():
    """iTunes stops there: it does not pass over a big track for a small one."""
    mb = 1024 * 1024
    tracks = [track(Plays=3, Size=600 * mb), track(Plays=2, Size=600 * mb),
              track(Plays=1, Size=100 * mb)]
    assert pick(tracks, limit={"count": 1, "unit": "GB", "by": "most often played"}) == [0]


def test_random_picks_the_same_tracks_for_one_seed():
    tracks = [track(Plays=i) for i in range(50)]
    limit = {"count": 5, "unit": "items", "by": "random"}
    first = pick(tracks, limit=limit, seed=7)
    assert pick(tracks, limit=limit, seed=7) == first
    assert len(set(first)) == 5 and pick(tracks, limit=limit, seed=8) != first


# ---- Against the lists iTunes saved ----------------------------------------------

# Rule sets whose saved list the evaluator reproduces track for track.
EXACT = ["4 star", "5star", "60-Second", "autoBach", "Clear Menser25recent",
         "HighestGrossing", "Recently Played", "recentlyAdded", "top20"]
# Limited lists where many tracks tie at the cut, so iTunes' choice among them
# is unknown. The sort-key values ahead of the tie still have to agree.
TIED = ["bottom40", "Most Played", "top40", "top90"]
SORT_KEY = {"least recently played": "Last Played", "most often played": "Plays",
            "least recently added": "Date Added"}


@pytest.fixture(scope="module")
def oracle(library, tmp_path_factory):
    smart = {p["name"]: p for p in library.playlists if "smart" in p}
    path = tmp_path_factory.mktemp("oracle") / "job.json"
    path.write_text(json.dumps({
        "tracks": library.tracks, "fields": PAGE_FIELDS,
        "ids": list(range(len(library.tracks))), "now": _ms(library.exported),
        "jobs": [{"rules": p["smart"]["rules"], "seed": 1} for p in smart.values()]
                + [{"rules": {**p["smart"]["rules"], "limit": None}, "seed": 1}
                   for p in smart.values()]}))
    picks = node(None, str(path))
    n = len(smart)
    return {name: (p["ids"], picks[k], set(picks[n + k]))
            for k, (name, p) in enumerate(smart.items())}


needs_library = pytest.mark.skipif(not os.path.isfile(config.LIBRARY),
                                   reason="needs a library export in data/")


@needs_library
@pytest.mark.parametrize("name", EXACT)
def test_the_rules_pick_what_itunes_saved(oracle, name):
    saved, mine, _ = oracle[name]
    assert sorted(mine) == sorted(saved)


@needs_library
def test_every_saved_track_meets_its_rules(oracle):
    for name, (saved, _, matched) in oracle.items():
        if name == "Clear Menser":
            continue
        assert set(saved) <= matched, name


@needs_library
@pytest.mark.parametrize("name", TIED)
def test_a_tied_limit_agrees_up_to_the_tie(oracle, library, name):
    saved, mine, _ = oracle[name]
    rules = next(p for p in library.playlists if p["name"] == name)["smart"]["rules"]
    key = COL[SORT_KEY[rules["limit"]["by"]]]
    tie = library.tracks[mine[-1]][key]

    def ahead(ids):
        return sorted(library.tracks[i][key] for i in ids if library.tracks[i][key] != tie)

    assert ahead(saved) == ahead(mine)
    assert all(library.tracks[i][key] == tie for i in set(saved) ^ set(mine))


@needs_library
@pytest.mark.xfail(strict=True, reason="iTunes leaves out an Audiobook-genre track and "
                   "tracks with no album name; nothing in the XML says why")
def test_clear_menser(oracle):
    saved, mine, _ = oracle["Clear Menser"]
    assert sorted(mine) == sorted(saved)


VALUE = {"pair": [1, 2], "span": {"n": 1, "unit": "days"}}
SAMPLE = {"text": "a", "number": 1, "date": "2020-01-01", "bool": True}


def test_every_operator_the_editor_offers_is_one_the_evaluator_knows():
    """The editor builds its menus from Smart.OPS; an operator with no test
    behind it would throw the first time a playlist used it."""
    ops = json.loads(subprocess.run(
        [NODE, "-e", "console.log(JSON.stringify(require(process.argv[1]).OPS))", SMART],
        capture_output=True, text=True, check=True).stdout)
    field = {"text": "Artist", "number": "Plays", "date": "Last Played", "bool": "Compilation"}
    for family, names in ops.items():
        for op in names:
            shape = "pair" if op == "in range" else "span" if op.endswith("in the last") else ""
            pick([track()], (field[family], op, VALUE.get(shape, SAMPLE[family])))
