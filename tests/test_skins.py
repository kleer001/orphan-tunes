"""Skins are Python data, so these assert against the data itself.

Nothing here parses the generated stylesheet or the page script. An earlier
version did, and it cost twice: a regex looking for three-string arrays matched
an unrelated ["off","all","one"] and reported it as a skin, and a declaration
splitter that did not strip comments failed a skin for containing one.
"""


from build_browser import BASE_TOKENS, REPEAT_CYCLE, SKINS, render_skins

BASE = SKINS[0]


def test_the_first_skin_is_the_base_and_defines_no_overrides():
    """It lives on :root, so it needs no attribute selector to be correct."""
    assert BASE.id == "greenwood"
    assert BASE.tokens == {}


def test_only_the_base_has_no_overrides():
    empty = [s.id for s in SKINS if not s.tokens]
    assert empty == [BASE.id], empty


def test_every_override_names_a_token_the_base_defines():
    for skin in SKINS:
        unknown = set(skin.tokens) - set(BASE_TOKENS)
        assert not unknown, f"{skin.id} sets tokens that do not exist: {sorted(unknown)}"


def test_no_skin_claims_an_era_that_changed_the_layout():
    """iTunes 11 hid the sidebar and 12 moved to tabs; neither is a repaint."""
    for skin in SKINS:
        if not skin.era.startswith("iTunes"):
            continue
        highest = int(skin.era.split()[-1].split("-")[-1])
        assert highest <= 10, f"{skin.label} claims {skin.era}, a different layout"


def test_ids_labels_and_eras_are_unique():
    for field in ("id", "label", "era"):
        values = [getattr(s, field) for s in SKINS]
        assert len(set(values)) == len(values), f"duplicate {field}: {values}"


def test_ids_are_safe_in_an_attribute_selector():
    for skin in SKINS:
        assert skin.id.isidentifier() and skin.id.islower(), skin.id


def test_rendering_emits_a_block_for_every_skin_but_the_base():
    css = render_skins()
    assert ":root{" in css
    for skin in SKINS:
        assert (f'[data-skin="{skin.id}"]' in css) is bool(skin.tokens), skin.id


def test_rendered_blocks_contain_only_custom_properties():
    """A skin that set a real property would drift the shared layout."""
    for skin in SKINS:
        for name in skin.tokens:
            assert name.startswith("--"), f"{skin.id}: {name} is not a token"


def test_repeat_cycles_through_every_mode_and_returns():
    mode, seen = "off", []
    for _ in range(len(REPEAT_CYCLE)):
        seen.append(mode)
        mode = REPEAT_CYCLE[mode]
    assert seen == ["off", "all", "one"], seen
    assert mode == "off", "the cycle must return to where it started"
