"""game_screen.replenish_wait: a vacated cell refills after a timer, or after a number of
submitted words (valid or not)."""
import config
from views.game_screen import GameScreen


def _screen(rule, words=3, seconds=5.0):
    """A bare GameScreen (no GL window) recording refills rather than placing grams."""
    gs = GameScreen.__new__(GameScreen)
    config.CONFIG["rules"]["game_screen.replenish_wait"] = rule
    config.CONFIG["rules"]["game_screen.replenish_wait_words"] = words
    gs._replenish_delay_seconds = seconds
    gs._pending_replenishes = []
    gs._bind_replenish_wait_rule()
    gs.filled = []
    gs._replenish_cell_now = lambda x, y, length=None: gs.filled.append((x, y, length))
    gs._recompute_candidates = lambda: None
    return gs


def _restore_config():
    config.CONFIG.clear()
    config.CONFIG.update(config.load_config())


def test_words_wait_ignores_the_clock_and_fills_on_the_tick_after_the_last_submit():
    try:
        gs = _screen("rule_replenish_wait_words")
        gs._schedule_replenish(1, 2, 3)
        gs._update_pending_replenishes(1000.0)
        assert gs.filled == []
        gs._note_word_submitted()
        gs._note_word_submitted()
        gs._update_pending_replenishes(0.1)
        assert gs.filled == []
        gs._note_word_submitted()
        assert gs.filled == []                     # never mid-submit
        gs._update_pending_replenishes(0.1)
        assert gs.filled == [(1, 2, 3)]            # the pinned length rides the wait
        assert gs._pending_replenishes == []
    finally:
        _restore_config()


def test_each_cell_counts_only_the_words_submitted_after_it_was_vacated():
    try:
        gs = _screen("rule_replenish_wait_words", words=2)
        gs._schedule_replenish(0, 0)
        gs._note_word_submitted()
        gs._schedule_replenish(1, 1)
        gs._note_word_submitted()
        gs._update_pending_replenishes(0.1)
        assert gs.filled == [(0, 0, None)]
        gs._note_word_submitted()
        gs._update_pending_replenishes(0.1)
        assert gs.filled == [(0, 0, None), (1, 1, None)]
    finally:
        _restore_config()


def test_zero_words_fills_instantly():
    try:
        gs = _screen("rule_replenish_wait_words", words=0)
        gs._schedule_replenish(4, 4)
        assert gs.filled == [(4, 4, None)]
        assert gs._pending_replenishes == []
    finally:
        _restore_config()


def test_seconds_wait_counts_time_and_ignores_submits():
    try:
        gs = _screen("rule_replenish_wait_seconds", seconds=5.0)
        gs._schedule_replenish(2, 2)
        for _ in range(10):
            gs._note_word_submitted()
        gs._update_pending_replenishes(4.0)
        assert gs.filled == []
        gs._update_pending_replenishes(1.0)
        assert gs.filled == [(2, 2, None)]
    finally:
        _restore_config()


def _muncher(lives=3):
    gs = _screen("rule_replenish_wait_words")
    gs._muncher_lives = lives
    gs.rejected = []
    gs._muncher_reject = lambda word, reason: gs.rejected.append(reason)
    gs.banked = []
    gs._shooting_submit = lambda word, path, segments: gs.banked.append(word)
    gs._word_length_rule = lambda word, path: True
    gs._repeat_rule = lambda word: True
    return gs


def test_muncher_counts_rejected_and_accepted_words_and_forced_clears_but_not_empty():
    try:
        gs = _muncher()
        gs._schedule_replenish(3, 3)
        gs._muncher_submit("", [], [])             # nothing eaten: not a submission
        assert gs._pending_replenishes[0][2] == 3
        gs._muncher_submit("ZZXQ", [(0, 0)], ["ZZXQ"])      # not a word
        assert gs.rejected == ["not_in_dictionary"]
        assert gs._pending_replenishes[0][2] == 2
        gs._muncher_submit("CAT", [(0, 0)], ["CAT"])
        assert gs.banked == ["CAT"]
        assert gs._pending_replenishes[0][2] == 1
        gs._muncher_forced_clear("ZZ", [(0, 0)], ["ZZ"])
        gs._update_pending_replenishes(0.1)
        assert gs.filled == [(3, 3, None)]
    finally:
        _restore_config()


def test_typed_submit_counts_invalid_words_and_not_its_own_cleared_cells():
    try:
        gs = _screen("rule_replenish_wait_words", words=1)
        gs._muncher = False
        gs._botanical = False
        gs._single_phase = False
        # A word whose submit vacates a cell: that cell waits for the NEXT word.
        gs._submit_clear_rule = lambda word: gs._schedule_replenish(5, 5)
        gs._on_submit_word("cat")
        gs._update_pending_replenishes(0.1)
        assert gs.filled == []
        # An invalid word clears nothing, and still counts.
        gs._submit_clear_rule = lambda word: None
        gs._on_submit_word("zzxq")
        gs._update_pending_replenishes(0.1)
        assert gs.filled == [(5, 5, None)]
    finally:
        _restore_config()


def test_muncher_preset_waits_three_submitted_words():
    try:
        config.apply_game_mode(config._GAME_MODES_DIR / "muncher.yaml")
        rules = config.CONFIG["rules"]
        assert rules["game_screen.replenish_wait"] == "rule_replenish_wait_words"
        assert rules["game_screen.replenish_wait_words"] == 3
    finally:
        _restore_config()
