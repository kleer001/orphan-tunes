"""The skins are CSS, but the contract between page and stylesheet is testable."""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from build_browser import CSS, JS  # noqa: E402

SKINS = ("greenwood", "tofino", "kaslo")


def test_greenwood_is_the_base_stylesheet():
    """It must live on :root, so the default needs no attribute to be correct."""
    assert ":root{" in CSS.replace(" ", "")
    assert '[data-skin="greenwood"]' not in CSS


def test_the_other_skins_are_attribute_scoped():
    for skin in SKINS[1:]:
        assert f'[data-skin="{skin}"]' in CSS, skin


def test_every_skin_the_page_offers_exists_in_the_css():
    offered = set(re.findall(r'\["(\w+)","[^"]+","iTunes', JS))
    assert offered == set(SKINS), offered
    for skin in offered - {SKINS[0]}:
        assert f'[data-skin="{skin}"]' in CSS


def test_no_skin_claims_an_era_that_changed_the_layout():
    """iTunes 11 hid the sidebar and 12 moved to tabs; neither is a repaint."""
    eras = re.findall(r'"iTunes ([\d-]+)"', JS)
    assert eras, "no eras declared"
    for era in eras:
        highest = int(era.split("-")[-1])
        assert highest <= 10, f"iTunes {era} is a different layout, not a skin"


def test_skins_only_override_tokens_never_layout():
    """A skin that sets a width or a display would drift from the base layout."""
    for block in re.findall(r'\[data-skin="\w+"\]\{([^}]*)\}', CSS):
        for decl in filter(None, (d.strip() for d in block.split(";"))):
            prop = decl.split(":")[0].strip()
            assert prop.startswith("--"), f"skin sets a real property: {decl}"


def test_the_base_defines_every_token_a_skin_overrides():
    base = set(re.findall(r'(--[\w-]+):', CSS.split("[data-skin=")[0]))
    for block in re.findall(r'\[data-skin="\w+"\]\{([^}]*)\}', CSS):
        for token in re.findall(r'(--[\w-]+):', block):
            assert token in base, f"{token} overridden but never defined on :root"
