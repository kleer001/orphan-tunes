"""What the page records through POST /state, and how it reaches disk."""

import functools
import json
import socketserver
import threading
import urllib.request

import pytest

import serve
from serve import Handler, apply_change, empty_state, load_state, save_state

PID = "0123456789ABCDEF"


def test_a_play_stores_the_count_and_time_the_page_sends():
    """Absolute values, so sending one change twice cannot count a play twice."""
    state = empty_state()
    change = {"type": "play", "pid": PID, "plays": 7, "played": "2026-10-19 21:04:00"}
    apply_change(state, change)
    apply_change(state, change)
    assert state["tracks"][PID] == {"plays": 7, "played": "2026-10-19 21:04:00"}


def test_a_rating_sits_beside_the_plays():
    state = empty_state()
    apply_change(state, {"type": "play", "pid": PID, "plays": 1, "played": "2026-10-19 21:04:00"})
    apply_change(state, {"type": "rate", "pid": PID, "rating": 80})
    assert state["tracks"][PID]["rating"] == 80 and state["tracks"][PID]["plays"] == 1


def test_a_playlist_is_saved_and_deleted_by_id():
    state = empty_state()
    rules = {"match": "all", "rules": [], "limit": None, "checkedOnly": False}
    apply_change(state, {"type": "save", "id": "u1", "playlist": {"name": "Mix", "rules": rules}})
    assert state["playlists"]["u1"] == {"name": "Mix", "rules": rules}
    apply_change(state, {"type": "delete", "id": "u1"})
    assert state["playlists"] == {}


@pytest.mark.parametrize("change", [
    {},
    {"type": "erase"},
    {"type": "rate", "pid": "../../etc", "rating": 80},
    {"type": "rate", "pid": PID, "rating": 101},
    {"type": "rate", "pid": PID, "rating": True},
    {"type": "play", "pid": PID, "plays": -1, "played": "2026-10-19 21:04:00"},
    {"type": "play", "pid": PID, "plays": 1, "played": "yesterday"},
    {"type": "save", "id": "../x", "playlist": {"name": "a", "rules": {}}},
    {"type": "save", "id": "u1", "playlist": {"name": 3, "rules": {}}},
])
def test_unknown_or_malformed_changes_are_refused(change):
    state = empty_state()
    with pytest.raises(ValueError):
        apply_change(state, change)
    assert state == empty_state()


def test_the_file_is_replaced_whole_and_no_temporary_is_left(tmp_path):
    path = str(tmp_path / "data" / "state.json")
    assert load_state(path) == empty_state()
    save_state(path, {"tracks": {PID: {"rating": 20}}, "playlists": {}})
    assert load_state(path)["tracks"][PID] == {"rating": 20}
    assert [p.name for p in (tmp_path / "data").iterdir()] == ["state.json"]


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(Handler, "state_path", str(tmp_path / "state.json"))
    monkeypatch.setattr(Handler, "state", empty_state())
    handler = functools.partial(Handler, directory=str(tmp_path))
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", tmp_path
    srv.shutdown()
    srv.server_close()


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as res:
            return res.status
    except urllib.error.HTTPError as err:
        return err.code


def test_a_change_posted_to_the_server_is_on_disk_and_served_back(server):
    url, folder = server
    assert post(url + "/state", {"type": "rate", "pid": PID, "rating": 60}) == 200
    assert json.loads((folder / "state.json").read_text())["tracks"][PID] == {"rating": 60}
    with urllib.request.urlopen(url + "/state") as res:
        assert json.load(res)["tracks"][PID] == {"rating": 60}


def test_the_server_refuses_a_bad_change_and_writes_nothing(server):
    url, folder = server
    assert post(url + "/state", {"type": "rate", "pid": PID, "rating": 900}) == 400
    assert post(url + "/state", ["not", "an", "object"]) == 400
    assert not (folder / "state.json").exists()


def test_the_state_file_comes_from_config():
    assert serve.STATE.endswith(".json")
