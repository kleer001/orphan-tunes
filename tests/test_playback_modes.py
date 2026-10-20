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


def test_a_play_is_counted_when_a_track_ends_and_not_when_it_starts():
    """As iTunes counted. A skip must not raise a play count."""
    assert 'addEventListener("ended",()=>{recordPlay(nowIdx); step(1);})' in JS
    start = JS[JS.index("function start("):JS.index("\nfunction ", JS.index("function start("))]
    assert "recordPlay" not in start


def test_plays_and_ratings_are_recorded_only_when_served():
    """Opened from disk there is no server to keep them."""
    for name in ("function recordPlay(", "function rate("):
        body = JS[JS.index(name):JS.index("\n}", JS.index(name))]
        assert "if(!SERVED" in body, name


def test_recorded_values_are_keyed_by_persistent_id_not_row_number():
    """A rebuild renumbers rows; a Persistent ID stays with its track."""
    assert "pid:DATA.pids[i]" in JS
    assert "new Map(DATA.pids.map((p,i)=>[p,i]))" in JS


def test_an_itunes_smart_playlist_is_copied_never_edited():
    """Its saved list and its .m3u8 stay as iTunes left them; only a copy runs."""
    menu = JS[JS.index('$("#srclist").oncontextmenu'):JS.index('$("#newSmart").onclick')]
    assert "p?.smart?.rules?" in menu and "Duplicate as Smart Playlist" in menu
    edit = menu.index('data-m="edit"')
    assert menu.rfind("p?.user?", 0, edit) > menu.rfind("p?.smart", 0, edit)


def test_a_new_playlist_id_is_one_the_server_accepts():
    from serve import PLAYLIST_ID
    assert "Date.now().toString(36)" in JS
    digits, n, out = "0123456789abcdefghijklmnopqrstuvwxyz", 1760915000000, ""
    while n:
        n, d = divmod(n, 36)
        out = digits[d] + out
    assert PLAYLIST_ID.fullmatch(out)      # what toString(36) gives for a time in 2025


def test_the_tab_title_scrolls_the_playing_track_and_goes_back_on_stop():
    start = JS[JS.index("function start("):JS.index("\nfunction step(")]
    stop = JS[JS.index("function stop(){"):JS.index("\nfunction togglePlay(")]
    assert "setMarquee()" in start and "setMarquee()" in stop
    assert "||PAGE_TITLE" in JS, "stopping puts the page title back"
    assert "scrollTitle(on)" in JS, "the title scrolls only while the track plays"
