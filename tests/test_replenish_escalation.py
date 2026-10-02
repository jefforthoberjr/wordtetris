"""game_screen.replenish_escalation: the gate that swaps the EARLY replenish length
rule (game_screen.replenish_length) for the LATE one
(game_screen.replenish_length_escalated) once enough words have cleared."""
import config
from views.game_screen import GameScreen


def _screen(early, late, escalation, threshold, words_cleared):
    """A bare GameScreen (no GL window, as the muncher/selection tests do it) with just
    the replenish rule bindings __init__ would have made, wired by name."""
    gs = GameScreen.__new__(GameScreen)
    by_name = {
        "rule_replenish_length_picker": gs._rule_replenish_length_picker,
        "rule_replenish_length_match": gs._rule_replenish_length_match,
        "rule_replenish_length_grow_wrap": gs._rule_replenish_length_grow_wrap,
        "rule_replenish_length_grow_cap": gs._rule_replenish_length_grow_cap,
        "rule_replenish_escalate_off": gs._rule_replenish_escalate_off,
        "rule_replenish_escalate_after_words": gs._rule_replenish_escalate_after_words,
    }
    gs._replenish_length_rule = by_name[early]
    gs._replenish_length_escalated_rule = by_name[late]
    gs._replenish_escalation_rule = by_name[escalation]
    gs._words_cleared_this_game = words_cleared
    config.CONFIG["rules"]["game_screen.replenish_escalation_words"] = threshold
    return gs


def test_gate_off_uses_the_early_rule_however_many_words_cleared():
    gs = _screen("rule_replenish_length_match", "rule_replenish_length_grow_cap",
                 "rule_replenish_escalate_off", 5, words_cleared=99)
    assert gs._replenish_length_for(1) == 1      # match: unigram -> unigram
    assert gs._replenish_length_for(2) == 2


def test_gate_closed_below_the_threshold_then_open_at_it():
    gs = _screen("rule_replenish_length_match", "rule_replenish_length_grow_cap",
                 "rule_replenish_escalate_after_words", 5, words_cleared=4)
    assert gs._replenish_length_for(1) == 1      # still like for like
    gs._words_cleared_this_game = 5
    assert gs._replenish_length_for(1) == 2      # grow_cap: 1 -> 2
    assert gs._replenish_length_for(2) == 3
    assert gs._replenish_length_for(3) == 3      # one-way: trigram stays trigram
    gs._words_cleared_this_game = 12             # and it stays open
    assert gs._replenish_length_for(1) == 2


def test_muncher_preset_opens_all_unigrams_and_escalates_after_five():
    """The shipped muncher mode file: single letters only to start, like-for-like
    refills, then WRAPPING growth once 5 words have banked (a bitten trigram comes
    back as a single letter, so the board recycles rather than gridlocking)."""
    try:
        config.apply_game_mode(config._GAME_MODES_DIR / "muncher.yaml")
        rules = config.CONFIG["rules"]
        assert rules["gram_length.unigram_percent"] == 100
        assert rules["gram_length.digram_percent"] == 0
        assert rules["gram_length.trigramplus_percent"] == 0
        assert rules["game_screen.setup_formation"] == \
            "rule_formation_fill_vowel_core_consonant_shell"
        assert rules["game_screen.constellation_turnover"] == "rule_constellation_replenish"
        assert rules["game_screen.replenish_length"] == "rule_replenish_length_match"
        assert rules["game_screen.replenish_escalation"] == "rule_replenish_escalate_after_words"
        assert rules["game_screen.replenish_escalation_words"] == 5
        assert rules["game_screen.replenish_length_escalated"] == \
            "rule_replenish_length_grow_wrap"
    finally:
        # Restore the base so this mode swap does not leak into other tests.
        config.CONFIG.clear()
        config.CONFIG.update(config.load_config())


def test_escalated_wrap_sends_a_trigram_back_to_a_single_letter():
    """The muncher's late rule: 1 -> 2, 2 -> 3+, and 3+ WRAPS back to 1, so eating a
    trigram reopens that cell as a single letter."""
    gs = _screen("rule_replenish_length_match", "rule_replenish_length_grow_wrap",
                 "rule_replenish_escalate_after_words", 5, words_cleared=5)
    assert gs._replenish_length_for(1) == 2
    assert gs._replenish_length_for(2) == 3
    assert gs._replenish_length_for(3) == 1
