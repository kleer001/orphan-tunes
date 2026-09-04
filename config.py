#!/usr/bin/env python3
"""Read config.toml, next to this file rather than the working directory."""

import os

import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "config.toml")


def _resolve(value):
    """Relative entries are read against the repo, not wherever you ran from."""
    return value if os.path.isabs(value) else os.path.join(HERE, value)


with open(PATH, "rb") as _fh:
    _cfg = tomllib.load(_fh)

LIBRARY = _resolve(_cfg["library"])
RECORDED_ROOT = _cfg["music"]["recorded_root"]
LOCAL_ROOT = _resolve(_cfg["music"]["local_root"])
PLAYLIST_DIR = _resolve(_cfg["output"]["playlists"])
BROWSER_DIR = _resolve(_cfg["output"]["browser"])
PORT = _cfg["serve"]["port"]
