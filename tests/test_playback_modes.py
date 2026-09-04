"""Shuffle and repeat are page state, but their contract is checkable here."""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from build_browser import JS  # noqa: E402


def test_repeat_cycles_off_all_one():
    """One button, three states, in iTunes' order."""
    cycle = re.search(r"repeatMode=\{([^}]*)\}\[repeatMode\]", JS)
    assert cycle, "repeat cycle not found"
    mapping = dict(re.findall(r'(\w+):"(\w+)"', cycle.group(1)))
    assert mapping == {"off": "all", "all": "one", "one": "off"}, mapping


def test_repeat_one_loops_the_element_rather_than_restarting():
    """Looping is gapless; re-triggering the source would audibly stutter."""
    assert 'audio.loop=(repeatMode==="one")' in JS


def test_running_off_the_end_only_wraps_when_repeating_all():
    step = re.search(r"function step\(by\)\{(.*?)\n\}", JS, re.S).group(1)
    assert step.count('repeatMode!=="all"') == 2, "both ends must check the mode"
    assert "stop()" in step, "without repeat it has to stop"
    assert "at=0" in step and "at=queue.length-1" in step, "both ends must wrap"


def test_the_queue_is_not_rebuilt_unless_the_visible_set_changed():
    """Rebuilding on every draw would reshuffle on each keystroke."""
    sync = re.search(r"function syncQueue\(force\)\{(.*?)\n\}", JS, re.S).group(1)
    assert "if(!force&&key===queueKey)return" in sync


def test_shuffle_keeps_the_playing_track_in_place():
    """iTunes reorders what comes next, it does not jump you elsewhere."""
    fn = re.search(r"function shuffled\(list,first\)\{(.*?)\n\}", JS, re.S).group(1)
    assert "if(first!==undefined)" in fn
    assert "out.indexOf(first)" in fn


def test_modes_are_remembered():
    assert "playlists.modes" in JS
    assert "saveModes()" in JS and "loadModes()" in JS
