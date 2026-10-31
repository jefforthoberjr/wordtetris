"""game_screen.replenish_ramp: once the escalation gate is open, only 1 of 3, then 2 of 3,
then all refills take the escalated length rule, climbing at time or word milestones."""
from types import SimpleNamespace

import config
from replay import ReplaySource
from views.game_screen import GameScreen


def _screen(ramp="rule_replenish_ramp_on", milestone="rule_replenish_ramp_after_seconds",
            words_cleared=5, gate="rule_replenish_escalate_after_words"):
    """A bare GameScreen (no GL window): gate opens at 5 words, early rule is like for
    like, late rule is the no-digram wrap."""
    gs = GameScreen.__new__(GameScreen)
    rules = config.CONFIG["rules"]
    rules["game_screen.replenish_ramp"] = ramp
    rules["game_screen.replenish_ramp_milestone"] = milestone
    rules["game_screen.replenish_ramp_milestone_seconds"] = 120
    rules["game_screen.replenish_ramp_milestone_words"] = 6
    rules["game_screen.replenish_escalation_words"] = 5
    gs._replenish_length_rule = gs._rule_replenish_length_match
    gs._replenish_length_escalated_rule = gs._rule_replenish_length_skip_digram_wrap
    gs._replenish_escalation_rule = {
        "rule_replenish_escalate_off": gs._rule_replenish_escalate_off,
        "rule_replenish_escalate_after_words": gs._rule_replenish_escalate_after_words,
    }[gate]
    gs._words_cleared_this_game = words_cleared
    gs._pending_replenishes = []
    gs._bind_replenish_ramp_rules()
    return gs


def _restore_config():
    config.CONFIG.clear()
    config.CONFIG.update(config.load_config())


def _next_lengths(gs, count):
    """Lengths for `count` bitten single letters: 3 escalated, 1 held back."""
    return [gs._replenish_length_for(1) for _ in range(count)]


def test_ramp_off_escalates_every_refill_at_once():
    try:
        gs = _screen(ramp="rule_replenish_ramp_off")
        assert _next_lengths(gs, 6) == [3, 3, 3, 3, 3, 3]
    finally:
        _restore_config()


def test_time_milestones_climb_one_third_two_thirds_then_all():
    try:
        gs = _screen()
        assert _next_lengths(gs, 6) == [1, 1, 3, 1, 1, 3]
        gs._update_pending_replenishes(119.0)
        assert gs._replenish_ramp_stage == 1
        gs._update_pending_replenishes(1.0)
        assert gs._replenish_ramp_stage == 2
        assert _next_lengths(gs, 3) == [1, 3, 3]
        gs._update_pending_replenishes(120.0)
        assert gs._replenish_ramp_stage == 3
        assert _next_lengths(gs, 3) == [3, 3, 3]
        gs._update_pending_replenishes(1000.0)     # the final stage stays put
        assert gs._replenish_ramp_stage == 3
    finally:
        _restore_config()


def test_word_milestones_count_words_cleared_since_the_gate_opened_and_ignore_time():
    try:
        gs = _screen(milestone="rule_replenish_ramp_after_words")
        gs._update_pending_replenishes(1000.0)
        assert gs._replenish_ramp_stage == 1
        gs._words_cleared_this_game = 10           # 5 since the gate opened
        gs._update_pending_replenishes(0.1)
        assert gs._replenish_ramp_stage == 1
        gs._words_cleared_this_game = 11
        gs._update_pending_replenishes(0.1)
        assert gs._replenish_ramp_stage == 2
        gs._words_cleared_this_game = 17
        gs._update_pending_replenishes(0.1)
        assert gs._replenish_ramp_stage == 3
    finally:
        _restore_config()


def test_nothing_moves_while_the_gate_is_shut_and_the_clock_starts_when_it_opens():
    try:
        gs = _screen(words_cleared=4)
        gs._update_pending_replenishes(1000.0)
        assert gs._replenish_ramp_stage == 1
        assert _next_lengths(gs, 3) == [1, 1, 1]   # early rule, like for like
        gs._words_cleared_this_game = 5
        gs._update_pending_replenishes(119.0)
        assert gs._replenish_ramp_stage == 1
        # The round robin starts at the gate, not at the refills before it.
        assert _next_lengths(gs, 3) == [1, 1, 3]
    finally:
        _restore_config()


def test_ramp_is_inert_with_the_gate_welded_shut():
    try:
        gs = _screen(gate="rule_replenish_escalate_off")
        gs._update_pending_replenishes(1000.0)
        assert gs._replenish_ramp_stage == 1
        assert _next_lengths(gs, 3) == [1, 1, 1]
    finally:
        _restore_config()


def test_holding_back_applies_to_the_wrap_too():
    try:
        gs = _screen()
        assert [gs._replenish_length_for(3) for _ in range(3)] == [3, 3, 1]
    finally:
        _restore_config()


def test_new_game_restarts_the_ramp():
    try:
        gs = _screen()
        _next_lengths(gs, 2)
        gs._update_pending_replenishes(120.0)
        assert gs._replenish_ramp_stage == 2
        gs._reset_replenish_ramp()
        assert gs._replenish_ramp_stage == 1
        assert _next_lengths(gs, 3) == [1, 1, 3]
    finally:
        _restore_config()


def test_replay_lands_milestones_at_their_recorded_times():
    event = SimpleNamespace(code=6011, t=50.0, fields={"stage": 2, "final_stage": 3})
    src = ReplaySource(SimpleNamespace(events=[event]))
    src.now = 49.9
    assert src.timing_gate("replenish_ramp_milestone", True) is False
    src.now = 50.0
    assert src.timing_gate("replenish_ramp_milestone", False) is True
