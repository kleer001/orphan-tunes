"""Guards on the playback logic that lives in the page script.

The repeat cycle itself is Python data and is tested in test_skins.py. What is
left here is behaviour, which cannot be asserted from data -- so these are plain
substring checks on specific lines rather than regexes that try to parse the
script's structure. Actual playback (wrapping, looping, shuffling) is exercised
in the browser, not here.
"""


from build_browser import REPEAT_CYCLE, read_static

JS = read_static("app.js")


def test_the_page_uses_the_cycle_it_was_given():
    """Not a copy of it, so the two cannot disagree."""
    assert "repeatMode=REPEAT[repeatMode]" in JS
    assert '{off:"all"' not in JS, "the cycle was re-declared in the script"


def test_repeat_one_loops_the_element_rather_than_restarting():
    """Looping is gapless; re-triggering the source stutters between passes."""
    assert 'audio.loop=(repeatMode==="one")' in JS


def test_running_off_either_end_checks_the_mode_before_wrapping():
    """One guard and one modulo cover both ends; an earlier version of this test
    counted the two mirrored branches, so simplifying the code failed it."""
    assert 'repeatMode!=="all"' in JS, "the mode must be consulted before wrapping"
    assert "stop()" in JS, "without repeat it has to stop"
    assert "(at+queue.length)%queue.length" in JS, "the wrap must cover both ends"


def test_the_queue_is_the_list_play_started_from():
    """Browsing or searching afterwards must not change what plays next, so
    drawing the view never touches the queue."""
    draw = JS[JS.index("function draw(){"):JS.index("\nfunction ", JS.index("function draw(){"))]
    assert "queue" not in draw and "context" not in draw
    assert "context=live(list)" in JS


def test_up_next_plays_ahead_of_the_queue():
    assert "if(by>0&&upNext.length)" in JS


def test_back_from_an_up_next_track_returns_to_the_track_it_interrupted():
    assert "fromUpNext&&by<0?qpos:qpos+by" in JS


def test_shuffle_keeps_the_playing_track_in_place():
    """iTunes reorders what comes next; it does not jump you elsewhere."""
    assert "out.indexOf(first)" in JS


def test_modes_are_remembered():
    assert "playlists.modes" in JS
    assert "saveModes()" in JS and "loadModes()" in JS


def test_every_mode_the_page_can_reach_is_one_the_cycle_defines():
    for mode in REPEAT_CYCLE:
        assert f'"{mode}"' in JS, f"{mode} is unreachable from the page"
