"""The skins are CSS, but the contract between page and stylesheet is testable."""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from build_browser import CSS, JS  # noqa: E402

BASE = "greenwood"          # lives on :root, so it needs no attribute
OFFERED = re.findall(r'\["(\w+)","([^"]+)","([^"]+)"\]', JS)


def strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def skin_blocks():
    return dict(re.findall(r'\[data-skin="(\w+)"\]\{([^}]*)\}', strip_comments(CSS)))


def test_the_page_offers_some_skins():
    assert len(OFFERED) >= 2, OFFERED


def test_the_base_skin_is_root_and_carries_no_attribute():
    assert ":root{" in CSS.replace(" ", "")
    assert f'[data-skin="{BASE}"]' not in CSS
    assert OFFERED[0][0] == BASE, "the base must be offered first"


def test_every_offered_skin_has_a_css_block():
    """A skin in the menu with no stylesheet silently does nothing when picked."""
    blocks = skin_blocks()
    for skin_id, label, _ in OFFERED:
        if skin_id == BASE:
            continue
        assert skin_id in blocks, f"{label} is offered but has no CSS"


def test_every_css_block_is_offered():
    """And a stylesheet nobody can select is dead weight."""
    offered = {s for s, _, _ in OFFERED}
    for skin_id in skin_blocks():
        assert skin_id in offered, f"{skin_id} has CSS but is not in the menu"


def test_no_itunes_skin_claims_an_era_that_changed_the_layout():
    """iTunes 11 hid the sidebar and 12 moved to tabs; neither is a repaint."""
    for _, label, era in OFFERED:
        if not era.startswith("iTunes"):
            continue
        highest = int(era.split()[-1].split("-")[-1])
        assert highest <= 10, f"{label} claims {era}, a different layout"


def test_skins_only_override_tokens_never_layout():
    """A skin that sets a real property would drift from the base layout."""
    for skin_id, block in skin_blocks().items():
        for decl in filter(None, (d.strip() for d in block.split(";"))):
            prop = decl.split(":")[0].strip()
            assert prop.startswith("--"), f"{skin_id} sets a real property: {decl}"


def test_the_base_defines_every_token_a_skin_overrides():
    base = set(re.findall(r'(--[\w-]+):',
                          strip_comments(CSS).split("[data-skin=")[0]))
    for skin_id, block in skin_blocks().items():
        for token in re.findall(r'(--[\w-]+):', block):
            assert token in base, f"{skin_id} sets {token}, never defined on :root"


def test_skin_ids_and_labels_are_unique():
    ids = [s for s, _, _ in OFFERED]
    labels = [label for _, label, _ in OFFERED]
    assert len(set(ids)) == len(ids), ids
    assert len(set(labels)) == len(labels), labels


def test_the_window_is_not_capped_to_a_fixed_size():
    """It was letterboxed at 1180x820, wasting most of a large display."""
    win = re.search(r'\.win\{([^}]*)\}', CSS).group(1)
    assert "max-width" not in win, win
    assert "max-height" not in win, win
    assert "width:100%" in win and "height:100%" in win, win


def test_the_track_pane_can_shrink():
    """Without min-width:0 a flex child refuses to go below its content width,
    which pushes the pane past the window edge instead of scrolling inside."""
    tracks = re.search(r'\.tracks\{([^}]*)\}', CSS).group(1)
    assert "min-width:0" in tracks, tracks
