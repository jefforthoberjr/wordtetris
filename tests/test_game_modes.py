"""Game-mode config layer: partial mode files deep-merged onto the base
config.yaml, applied by mutating CONFIG in place so every holder sees the swap
(see config.apply_game_mode / the "Start" submenu)."""

import config


def test_deep_merge_overrides_nested_without_dropping_siblings():
    base = {"rules": {"a": 1, "b": 2}, "window": {"width": 800}}
    override = {"rules": {"b": 99, "c": 3}}
    merged = config._deep_merge(base, override)
    # Overridden + added keys land; untouched siblings and other blocks survive.
    assert merged["rules"] == {"a": 1, "b": 99, "c": 3}
    assert merged["window"] == {"width": 800}
    # Inputs are not mutated.
    assert base["rules"] == {"a": 1, "b": 2}


def test_deep_merge_replaces_lists_wholesale():
    base = {"suffix_tails": ["ION", "OUS"]}
    override = {"suffix_tails": ["ED"]}
    assert config._deep_merge(base, override)["suffix_tails"] == ["ED"]


def test_list_game_modes_returns_labels_sorted():
    modes = config.list_game_modes()
    slugs = {slug for slug, _label, _path in modes}
    # The three seeded starters ship with the repo.
    assert {"constellation", "typewriter", "omniswap"} <= slugs
    # Every mode carries a human label (never a bare slug for the seeded files).
    labels = [label for _slug, label, _path in modes]
    assert all(labels)
    # Sorted by label (case-insensitive).
    assert labels == sorted(labels, key=str.lower)


def test_apply_game_mode_mutates_config_in_place():
    original = config.CONFIG  # identity must be preserved across the swap
    slug, label = config.apply_game_mode(
        config._GAME_MODES_DIR / "typewriter.yaml"
    )
    assert slug == "typewriter"
    assert config.CONFIG is original  # same dict object, contents replaced
    assert config.CONFIG["rules"]["game_screen.mode"] == "rule_mode_typewriter"
    # mode_label is metadata, never leaked into the game config.
    assert "mode_label" not in config.CONFIG
    # A base-only block the mode file never mentions still comes through.
    assert "spell_check" in config.CONFIG
    assert config.active_mode()[:2] == (slug, label)


def test_apply_game_mode_reloads_clean_base_each_switch():
    # Switching modes must merge onto a FRESH base, not onto the prior merge, so
    # a key set only by mode A does not bleed into mode B.
    config.apply_game_mode(config._GAME_MODES_DIR / "omniswap.yaml")
    assert config.CONFIG["rules"]["game_screen.mode"] == "rule_mode_omniswap_vs_timer"
    config.apply_game_mode(config._GAME_MODES_DIR / "constellation.yaml")
    assert config.CONFIG["rules"]["game_screen.mode"] == "rule_mode_constellation"
    # Restore the base so import-order test side effects don't leak.
    config.CONFIG.clear()
    config.CONFIG.update(config.load_config())
