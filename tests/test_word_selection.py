"""Interactive word-selection (the SELECTING phase) logic in GameScreen.

GameScreen needs a real window to construct, so these build a bare instance via
__new__ and wire only the attributes the selection pipeline touches: a fake
board, fake MOVING/SELECTING side panes that record what the UI was told to
show, and a fake player dictionary tracking lifetime words.
"""
from views import game_screen as gs


class _FakeSquare:
    """The render quad of a board cell; only its .color is touched (recolored to
    the placed tint on placement, then to the settled color when the piece is
    left behind), which the logic tests ignore."""

    def __init__(self):
        self.color = None


class _FakeCell:
    def __init__(self):
        self.square = _FakeSquare()


class _FakeGram:
    """Stand-in for a placed cell's Gram: its letters and whether it is a wild
    vowel (a wild cell carries no fixed letters)."""

    def __init__(self, text, is_wild=False):
        self.text = text
        self.is_wild = is_wild


class FakeBoard:
    """Sparse {(x, y): letter} board with the methods the pipeline calls. Square
    geometry (four cardinals) so words snake/turn freely. Cells listed in `wild`
    are wild-vowel cells (their letter value is ignored)."""

    def __init__(self, cells, wild=()):
        self.cells = dict(cells)
        self._wild = set(wild)

    def letter_at(self, x, y):
        letter = self.cells.get((x, y))
        if (x, y) in self._wild:
            letter = None  # a wild cell contributes no fixed letter
        return letter

    def gram_at(self, x, y):
        gram = None
        if (x, y) in self.cells:
            gram = _FakeGram(self.cells[(x, y)], is_wild=(x, y) in self._wild)
        return gram

    def occupied_cells(self):
        return list(self.cells.keys())

    def is_valid(self, x, y):
        return True

    def forward_neighbors(self, x, y, prev=None):
        steps = ((1, 0), (-1, 0), (0, 1), (0, -1))
        return [((x + dx, y + dy), d) for d, (dx, dy) in enumerate(steps)]

    def neighbors(self, x, y):
        # Physical adjacency (four cardinals), mirroring SquareGrid.neighbors.
        # is_valid is always True here, so every cardinal counts -- enough for
        # the _piece_touches_existing adjacency gate the SELECT phase now uses.
        result = []
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            result.append((x + dx, y + dy))
        return result

    def get_cell(self, x, y):
        # A present cell exposes a .square whose .color the settle step rewrites
        # (render-only); a cleared cell is gone, so return None to skip it.
        cell = None
        if (x, y) in self.cells:
            cell = _FakeCell()
        return cell

    def cell_center(self, x, y):
        # Pixel center of a cell; the disambiguation chooser reads it to lay out
        # the candidate polylines. Cell coords scaled to fake pixels is enough.
        return (x * 10, y * 10)

    def cell_at(self, px, py):
        # The select-click rule maps a pixel to a cell; these tests pass cell
        # coordinates straight through, returning None off the populated board.
        return (px, py) if (px, py) in self.cells else None

    def clear_cell(self, x, y):
        self.cells.pop((x, y), None)

    def relabel_cell(self, x, y, text):
        # Partial-gram leftover: the cell stays, holding only its leftover
        # letters (visual re-fit is real-board only; gram_at reads self.cells).
        if (x, y) in self.cells:
            self.cells[(x, y)] = text


class FakePane:
    """Stand-in for the SELECTING side pane (game_screen._selecting_side_pane)."""

    def __init__(self):
        self.accepted = []
        self.errors = None
        self.began = False
        self.word_count = None
        self.rejected = None
        self.prompt = None

    def begin(self):
        self.began = True
        self.accepted = []
        self.errors = None

    def prefill(self, word):
        # The carried hunt word pre-loaded into the field before an auto-submit.
        self.prefilled = word

    def accept_word(self, word, is_new=False, is_obscure=False, points=None):
        # is_new (green) / is_obscure (orange when also new) / points (the word's
        # score, shown "+NN") are recorded by production; the selection-logic
        # tests only assert which words were accepted, so they're unused here.
        self.accepted.append(word)
        self.errors = None

    def set_score_label(self, points):
        # The running point total shown near the timer; recorded but unused here.
        self.score = points

    def show_errors(self, messages):
        self.errors = list(messages)

    def clear_errors(self):
        self.errors = None

    def show_prompt(self, text):
        # The "Select which one:" chooser cue; recorded so tests can assert the
        # chooser is on screen.
        self.prompt = text

    def hide_prompt(self):
        self.prompt = None

    def set_word_count(self, count):
        self.word_count = count

    def reject(self, word, messages):
        # The rejected-word echo path (reject_ghost on): records the ghost word
        # and, like the real pane, still surfaces the reason(s) via errors so the
        # existing error-message assertions hold.
        self.rejected = word
        self.errors = list(messages)

    def clear_ghost(self):
        self.rejected = None


class FakeMergedPane:
    """Stand-in for the single-phase MovingSelectingSidePane, which serves BOTH
    the moving and selecting slots. Mirrors the real split: add_cleared_words (the
    _clear_paths sink) lists the word; accept_word only resets the field, so a
    cleared word is listed exactly once."""

    def __init__(self):
        self.cleared = []       # via add_cleared_words (the game-long list)
        self.accepted = []      # via accept_word (field reset; must NOT list)
        self.word_count = None

    def add_cleared_words(self, words, new_flags=None, obscure_flags=None, scores=None):
        self.cleared += list(words)

    def accept_word(self, word, is_new=False, is_obscure=False, points=None):
        self.accepted.append(word)

    def set_word_count(self, count):
        self.word_count = count

    def set_score_label(self, points):
        self.score = points

    def set_phase_label(self, count):
        self.phase_label = count

    def clear_errors(self):
        pass

    def clear_hunt(self):
        pass

    def hunt_text(self):
        return ""


class FakeSidepane:
    """Stand-in for the MOVING side pane (game_screen._moving_side_pane)."""

    def __init__(self):
        self.cleared = []
        self.word_count = None

    def add_cleared_words(self, words, new_flags=None, obscure_flags=None, scores=None):
        self.cleared += list(words)

    def set_word_count(self, count):
        self.word_count = count

    def set_score_label(self, points):
        # The running point total shown near the timer; recorded but unused here.
        self.score = points

    def set_phase_label(self, count):
        # The "Pieces: N" countdown; recorded but unused by these logic tests.
        self.phase_label = count

    def clear_hunt(self):
        # The MOVING word-hunt field is emptied whenever MOVING is left; a no-op
        # for these logic tests (no hunt text is typed).
        self.hunt_cleared = getattr(self, "hunt_cleared", 0) + 1

    def hunt_text(self):
        # No hunt word is typed in these logic tests, so swaps/spawns skip the
        # highlight refresh (guarded on a non-empty hunt).
        return ""


class FakePlayerDict:
    """Stand-in for the persistent PlayerDictionary: tracks lifetime words so
    add() can report whether each cleared word was new (which colors it green)."""

    def __init__(self):
        self._words = set()
        # (word, variation) pairs recorded, so tests can assert the encoding.
        self.added = []

    def __len__(self):
        return len(self._words)

    def contains(self, word):
        return word.lower() in self._words

    def add(self, word, variation=None):
        w = word.lower()
        is_new = w not in self._words
        self._words.add(w)
        self.added.append((w, variation))
        return is_new


class FakePool:
    def advance(self):
        return None


class FakeMovingMode:
    """Stand-in for the MOVING-phase mode (game_screen._moving_mode). The
    selection pipeline only pokes it to advance the turn once a phase ends; the
    selection-logic tests don't assert on the moving phase, so advance is a
    no-op that just records it was called."""

    def __init__(self):
        self.advanced = 0
        # Board clicks routed here by the SELECTING move-piece rule.
        self.clicks = []

    def advance(self):
        self.advanced += 1

    def on_mouse_press(self, x, y, button):
        self.clicks.append((x, y, button))


class FakeDisambigLines:
    """Stand-in for the board's disambiguation-line overlay
    (game_screen._disambig_lines). Records the last show()/clear() so tests can
    assert the chooser drew the expected candidates and highlight."""

    def __init__(self):
        self.paths = None
        self.selected = None

    def show(self, paths, selected):
        self.paths = paths
        self.selected = selected

    def clear(self):
        self.paths = None
        self.selected = None


class _InteractiveStub:
    interactive = True


def _game(board, interactive=True, history=None):
    g = gs.GameScreen.__new__(gs.GameScreen)
    # Two-phase (the original phase model) for these selection-pipeline tests; the
    # single-phase branch (merged MOVING_AND_SELECTING pane) is exercised separately.
    g._single_phase = False
    g._word_length_rule = gs.rule_word_min3letters_min2cells
    g._cleared_word_history = set(history or ())
    g._repeat_rule = lambda w: w not in g._cleared_word_history
    g._nucleation_rule = g._rule_adjacent_to_placed_pieces
    # Independent placed-cell filter (stage 2b); optional preserves the original
    # adjacent-only behavior the existing tests assert.
    g._placed_cell_rule = g._rule_placed_cell_optional
    # Independent fossil filter (stage 2c); optional preserves the original
    # behavior. The first-word-skip knob and the game-wide cleared-word counter
    # it reads are wired here too (0 => opening word hasn't landed).
    g._fossil_requirement_rule = g._rule_fossil_cell_optional
    g._fossil_first_word_rule = g._rule_fossil_skip_first_word
    g._words_cleared_this_game = 0
    # Phase-transition rules at their originals: every placement is a selection
    # turn, and an isolated placement skips selection. So _begin_selection
    # behaves as it did before the multi-placement trigger, which is what these
    # selection-logic tests exercise.
    g._select_trigger_rule = g._rule_select_every_placement
    g._select_trigger_count = 1
    g._placements_until_select = 1
    g._skip_select_rule = g._rule_skip_select_if_isolated
    # Clear-timing at its original: each submit clears immediately. The batch
    # tests below flip these two to the clear-at-phase-end pair.
    g._submit_clear_rule = g._rule_submit_clears_now
    g._endphase_clear_rule = g._rule_endphase_clear_none
    g._candidate_word_options = {}
    g._pending = []
    # Disambiguation at its original "auto-pick": several ways to spell a word
    # resolve silently to the fewest-cell one (ties at random), the behavior these
    # tests assert. The interactive cycle chooser is exercised via the game loop,
    # not these unit tests, so its state just needs to exist and read "closed".
    g._disambiguation_rule = g._rule_disambig_auto_pick
    g._disambig_cancel_rule = g._rule_disambig_cancel_on
    g._disambig_cancel_enabled = True
    g._disambig_options = []
    g._disambig_index = 0
    g._disambig_word = None
    g._disambig_commit = None
    g._disambig_lines = FakeDisambigLines()
    # Gram usage at its original: a word consumes a cell's whole gram. Partial
    # tests below flip this to rule_gram_use_partial.
    g._gram_usage_rule = g._rule_gram_use_whole
    # Fossil-word-use at its original "block": the word-finding walk treats a
    # fossilized cell as a wall and a finished word never contains one. These
    # tests start with no fossilized cells, so the rules never actually fire --
    # they just satisfy the fossil seam _collect_words / _clear_paths now call.
    g._fossilized_cells = set()
    g._fossil_is_wall_rule = g._rule_fossil_block_is_wall
    g._fossil_word_ok_rule = g._rule_fossil_block_word_ok
    # Word-trail off (original): no path trails recorded on a cleared word, so the
    # selection-logic tests need no _word_trail / board cell_center geometry.
    g._word_trail_rule = g._rule_word_trail_off
    # Select word-limit at its original "unlimited": an accepted word leaves the
    # SELECT phase open, matching the flow these tests assert.
    g._select_word_limit_rule = g._rule_unlimited_words
    # Spelling suggestions off: these tests assert exact error message lists, and
    # the "did you mean?" engine is exercised in its own test modules.
    g._spell_suggest_rule = lambda word: []
    # Clear-action at its original "remove": consumed cells leave the board
    # (partial-gram aware), the behavior the clear / partial-gram tests assert.
    g._clear_action_rule = g._rule_clear_remove
    # Per-select submit counter, reset each time a SELECT phase opens in
    # production; initialized here so the submit handlers can bump it.
    g._words_submitted_this_select = 0
    # Fake moving mode: the pipeline advances the turn through it once a phase
    # ends; these tests don't assert on the moving phase.
    g._moving_mode = FakeMovingMode()
    # Rejected-submit ghost on (production default): the echo path records both
    # the ghost word and the reason(s), so error-message assertions still hold.
    g._reject_ghost = True
    # Auto-submit-on-open off by default here (the logic tests drive submits
    # explicitly and use an empty hunt); the dedicated test flips it on.
    g._select_autosubmit_hunt = False
    # Mouse buttons the SELECTING move-piece rule passes to the moving mode.
    g._buttons = {"move_primary": "LEFT", "select_primary": "LEFT"}
    g._moving_side_pane = FakeSidepane()
    g._piece_pool = FakePool()
    g._selecting_side_pane = FakePane()
    g._player_dict = FakePlayerDict()
    # Real scorer: _clear_paths and the submit-commit handlers score each cleared
    # word into it (a pure, config-driven computation with no side effects), so
    # the pipeline needs it wired like the other collaborators above.
    g._scorer = gs.Scorer()
    # Whole-board fill bonus off: _clear_paths / _settle_placed_cells call
    # _check_board_fill, which the "off" rule short-circuits without touching the
    # (fake) board. These selection-logic tests don't exercise the fill bonus.
    g._fill_board_rule = g._rule_fill_board_off
    g._fill_board_awarded = False
    # Square separator so _clear_paths can encode the cleared word's grouping for
    # the player dictionary (these tests run square-geometry boards).
    g._gram_separator = "|"
    g._dictionary_count_rule = gs.rule_show_dictionary_count
    # No victory in these selection-logic tests, and no starting obstacles or
    # missions to track; the victory rule just reports "not won" so flow proceeds
    # normally.
    g._obstacle_cells = set()
    g._mission_cells = set()
    g._victory_rule = lambda: False
    g._phase = gs.Phase.MOVING
    g._move_placed = set()
    g._candidates = []
    g._candidate_words = {}
    g._selector = _InteractiveStub() if interactive else gs.AutoSelect()
    g._board = board
    return g


def test_interactive_enters_selecting_with_candidates():
    # T E A on the board; placing R at (3,0) forms TEAR (and EAR), both of which
    # bridge the placed R and old cells.
    g = _game(FakeBoard({(0, 0): "T", (1, 0): "E", (2, 0): "A", (3, 0): "R"}))
    g._begin_selection([(3, 0)])
    assert g._phase is gs.Phase.SELECTING
    assert g._selecting_side_pane.began
    assert set(g._candidate_words) == {"TEAR", "EAR"}


def test_submit_valid_word_clears_and_lists_it():
    g = _game(FakeBoard({(0, 0): "T", (1, 0): "E", (2, 0): "A", (3, 0): "R"}))
    g._begin_selection([(3, 0)])
    g._on_submit_word("tear")  # case-insensitive
    assert g._selecting_side_pane.accepted == ["TEAR"]
    assert g._moving_side_pane.cleared == ["TEAR"]
    assert g._board.cells == {}  # every TEAR cell removed


def test_single_phase_forces_clear_on_submit_and_lists_word():
    # Regression: single-phase (MOVING_AND_SELECTING) with a clear_at_phase_end
    # config used to defer every submit into a batch that -- with no phase end --
    # never flushed: cells stayed tinted green forever and the word never cleared
    # or appeared in the list. Single-phase now forces clear-on-submit.
    g = _game(FakeBoard({(0, 0): "T", (1, 0): "E", (2, 0): "A", (3, 0): "R"}))
    # The pre-filled-board setup single-phase runs on: words form anywhere (no
    # placed piece to nucleate around, since there is no _begin_selection).
    g._nucleation_rule = g._rule_nucleate_anywhere
    # The offending config: batch clear-at-phase-end.
    g._submit_clear_rule = g._rule_submit_defers
    g._endphase_clear_rule = g._rule_endphase_clear_pending
    # Single-phase: one merged pane in BOTH slots, and the invariant applied.
    g._single_phase = True
    merged = FakeMergedPane()
    g._moving_side_pane = merged
    g._selecting_side_pane = merged
    g._force_single_phase_clear_timing()
    assert g._submit_clear_rule == g._rule_submit_clears_now

    g._on_submit_word("tear")
    assert merged.cleared == ["TEAR"]   # listed once, via the _clear_paths sink
    assert merged.accepted == ["TEAR"]  # field reset, but did not double-list
    assert g._board.cells == {}         # actually cleared, not deferred
    assert g._pending == []             # nothing held -> no stuck green tint


def test_non_dictionary_word_errors():
    g = _game(FakeBoard({(0, 0): "T", (1, 0): "E", (2, 0): "A", (3, 0): "R"}))
    g._begin_selection([(3, 0)])
    g._on_submit_word("zzz")
    assert g._selecting_side_pane.errors == ["Word is not in the dictionary"]


def test_non_dictionary_word_shows_spelling_suggestions():
    # When the spell-suggest engine offers fixes, they appear on a second line
    # under the "not in dictionary" error.
    g = _game(FakeBoard({(0, 0): "T", (1, 0): "E", (2, 0): "A", (3, 0): "R"}))
    g._spell_suggest_rule = lambda word: ["BUTTON", "BITTEN"]
    g._begin_selection([(3, 0)])
    g._on_submit_word("buttin")
    assert g._selecting_side_pane.errors == [
        "Word is not in the dictionary",
        "Did you mean: BUTTON, BITTEN?",
    ]


def test_real_word_off_board_shows_no_suggestions():
    # A real (just-misplaced) word is a dictionary word, so no spelling fix is
    # offered even if the engine would return something.
    g = _game(FakeBoard({(0, 0): "T", (1, 0): "E", (2, 0): "A", (3, 0): "R"}))
    g._spell_suggest_rule = lambda word: ["SHOULD_NOT_APPEAR"]
    g._begin_selection([(3, 0)])
    g._on_submit_word("hello")
    assert g._selecting_side_pane.errors == ["Word isn't on the board"]


def test_real_word_not_on_board_errors():
    g = _game(FakeBoard({(0, 0): "T", (1, 0): "E", (2, 0): "A", (3, 0): "R"}))
    g._begin_selection([(3, 0)])
    g._on_submit_word("hello")  # a real word, but not on the board
    assert g._selecting_side_pane.errors == ["Word isn't on the board"]


def test_word_too_short_errors():
    # GO is a dictionary word and sits on the board, but the active length rule
    # (min 3 letters) makes it too short to clear -- a distinct message from
    # "not on the board".
    g = _game(FakeBoard({(0, 0): "G", (1, 0): "O"}))
    g._begin_selection([(1, 0)])
    g._on_submit_word("go")
    assert g._selecting_side_pane.errors == ["Word is too short"]


def test_word_not_involving_placed_piece_errors():
    # CAT is a length-OK board word, but the placed piece (an isolated S far
    # away) doesn't touch it, so it never nucleated.
    g = _game(FakeBoard({(0, 0): "C", (1, 0): "A", (2, 0): "T", (5, 5): "S"}))
    g._begin_selection([(5, 5)])
    g._on_submit_word("cat")
    assert g._selecting_side_pane.errors == ["Word didn't involve placed piece"]


def test_already_cleared_word_errors():
    g = _game(
        FakeBoard({(0, 0): "T", (1, 0): "E", (2, 0): "A", (3, 0): "R"}),
        history={"TEAR"},
    )
    g._begin_selection([(3, 0)])
    g._on_submit_word("tear")
    assert g._selecting_side_pane.errors == ["Word already cleared"]
    assert g._board.cells != {}  # nothing cleared


def test_recompute_after_clear_allows_second_word():
    # TEAR clears, leaving nothing; resubmitting it now reads as off-board.
    g = _game(FakeBoard({(0, 0): "T", (1, 0): "E", (2, 0): "A", (3, 0): "R"}))
    g._begin_selection([(3, 0)])
    g._on_submit_word("tear")
    g._on_submit_word("tear")
    assert g._selecting_side_pane.errors == ["Word isn't on the board"]


def test_auto_selector_clears_immediately_without_selecting():
    g = _game(
        FakeBoard({(0, 0): "T", (1, 0): "E", (2, 0): "A", (3, 0): "R"}),
        interactive=False,
    )
    g._begin_selection([(3, 0)])
    assert g._phase is gs.Phase.MOVING       # never enters SELECTING
    assert g._moving_side_pane.cleared == ["TEAR"]    # maximal path cleared
    assert g._board.cells == {}


# --- wild-vowel cells -------------------------------------------------------

def test_wild_cell_expands_to_multiple_words():
    # C _ T with the middle cell wild: the wild expands to 1-3 vowels, so the
    # path spells several words, including COAT via the two-vowel run "OA".
    g = _game(
        FakeBoard({(0, 0): "C", (1, 0): "X", (2, 0): "T"}, wild={(1, 0)}),
    )
    g._begin_selection([(2, 0)])
    assert g._phase is gs.Phase.SELECTING
    assert {"CAT", "COT", "CUT", "COAT"} <= set(g._candidate_words)


def test_wild_submit_clears_and_encodes_with_question_marks():
    g = _game(
        FakeBoard({(0, 0): "C", (1, 0): "X", (2, 0): "T"}, wild={(1, 0)}),
    )
    g._begin_selection([(2, 0)])
    g._on_submit_word("coat")
    assert g._selecting_side_pane.accepted == ["COAT"]
    assert g._board.cells == {}  # all three cells cleared
    # The wild cell records the run it resolved to, wrapped in "?...?".
    assert g._player_dict.added == [("coat", "c|?oa?|t")]


def test_wild_obstacle_encodes_brackets_outside_question_marks():
    # A wild cell that is also a starting obstacle encodes as [?...?].
    g = _game(
        FakeBoard({(0, 0): "C", (1, 0): "X", (2, 0): "T"}, wild={(1, 0)}),
    )
    g._obstacle_cells = {(1, 0)}
    g._begin_selection([(2, 0)])
    g._on_submit_word("cat")
    assert g._player_dict.added == [("cat", "c|[?a?]|t")]


def test_mission_cell_encodes_with_angle_brackets():
    # A starting-mission cell encodes as <...>, the obstacles' [...] twin.
    g = _game(FakeBoard({(0, 0): "C", (1, 0): "A", (2, 0): "T"}))
    g._mission_cells = {(1, 0)}
    g._begin_selection([(2, 0)])
    g._on_submit_word("cat")
    assert g._player_dict.added == [("cat", "c|<a>|t")]
    # Clearing the mission cell empties the mission-tracking set.
    assert g._mission_cells == set()


# --- multi-placement nucleation (the select-after-N trigger) ----------------

def test_all_pieces_placed_this_phase_are_nucleation_sites():
    # Two regions, TEA at row 0 and BEA at row 2. With select firing every 2nd
    # placement, the first R (row 0) is placed without opening selection, then
    # the second R (row 2) triggers it. Both placed pieces must count as
    # nucleation sites, so TEAR (around the first R) and BEAR (around the second)
    # are both clearable -- not just the word around the last piece down.
    # The R cells sit on the board (the unit-test board is pre-populated; the
    # placement just names which cells nucleate), one per region.
    g = _game(
        FakeBoard(
            {
                (0, 0): "T", (1, 0): "E", (2, 0): "A", (3, 0): "R",
                (0, 2): "B", (1, 2): "E", (2, 2): "A", (3, 2): "R",
            }
        )
    )
    g._select_trigger_rule = g._rule_select_after_n_placements
    g._select_trigger_count = 2
    g._placements_until_select = 2

    g._begin_selection([(3, 0)])             # turn 1: no selection yet
    assert g._phase is gs.Phase.MOVING
    g._begin_selection([(3, 2)])             # turn 2: selection opens
    assert g._phase is gs.Phase.SELECTING
    # The accumulated placed set carries both pieces into nucleation.
    assert g._move_placed == {(3, 0), (3, 2)}
    assert {"TEAR", "BEAR"} <= set(g._candidate_words)


# --- select-phase board clicks (move-piece routing) -------------------------

def test_select_click_move_piece_routes_to_moving_mode():
    # A SELECTING board click is handed to the active MOVING mode (so cells can be
    # rearranged without leaving word entry), passing the move_primary button;
    # then the clearable words are re-found against the (possibly changed) board.
    g = _game(FakeBoard({(0, 0): "C", (1, 0): "A", (2, 0): "T"}))
    g._move_placed = {(2, 0)}
    g._rule_select_click_move_piece(2, 0)
    assert g._moving_mode.clicks == [(2, 0, g._buttons["move_primary"])]
    # Recompute ran: CAT is on the board and nucleates around the placed cell.
    assert "CAT" in g._candidate_words


def test_select_click_none_does_nothing():
    g = _game(FakeBoard({(0, 0): "C", (1, 0): "A", (2, 0): "T"}))
    g._rule_select_click_none(1, 0)
    assert g._moving_mode.clicks == []


# --- auto-submit the carried hunt word on SELECT open -----------------------

def test_autosubmit_hunt_word_on_open():
    # ENTER into SELECT with a word in the MOVING hunt field auto-submits it, so
    # the SAME ENTER lands on the blue-path confirm (chooser open, nothing
    # committed yet) instead of needing a dead middle ENTER to submit it.
    g = _game(FakeBoard({(0, 0): "C", (1, 0): "A", (2, 0): "T"}))
    g._nucleation_rule = g._rule_nucleate_anywhere
    g._skip_select_rule = g._rule_never_skip_select
    g._select_autosubmit_hunt = True
    # Production flow: the one-or-more cycle rule opens the preview for a lone path
    # too, so a valid auto-submit shows the blue path rather than clearing outright.
    g._disambiguation_rule = g._rule_disambig_cycle_one_or_more_choices
    g._moving_side_pane.hunt_text = lambda: "cat"
    g._begin_selection([])
    assert g._phase is gs.Phase.SELECTING
    assert g._disambiguating()                    # blue-path preview is up on CAT
    assert g._selecting_side_pane.accepted == []  # not committed until confirm


def test_no_autosubmit_when_disabled():
    # With auto-submit off the hunt word is only pre-loaded, never submitted: no
    # chooser opens and nothing is accepted until the player submits manually.
    g = _game(FakeBoard({(0, 0): "C", (1, 0): "A", (2, 0): "T"}))
    g._nucleation_rule = g._rule_nucleate_anywhere
    g._skip_select_rule = g._rule_never_skip_select
    g._select_autosubmit_hunt = False
    g._disambiguation_rule = g._rule_disambig_cycle_one_or_more_choices
    g._moving_side_pane.hunt_text = lambda: "cat"
    g._begin_selection([])
    assert g._phase is gs.Phase.SELECTING
    assert not g._disambiguating()
    assert g._selecting_side_pane.accepted == []


def test_wild_mission_encodes_brackets_outside_question_marks():
    # A wild cell that is also a starting mission encodes as <?...?>.
    g = _game(
        FakeBoard({(0, 0): "C", (1, 0): "X", (2, 0): "T"}, wild={(1, 0)}),
    )
    g._mission_cells = {(1, 0)}
    g._begin_selection([(2, 0)])
    g._on_submit_word("cat")
    assert g._player_dict.added == [("cat", "c|<?a?>|t")]


def test_typed_word_prefers_fewest_cells():
    # Two adjacent wilds then T, H: OATH can clear as wild("O")+wild("A")+T+H
    # (4 cells) or as the second wild alone = "OA" + T + H (3 cells). Typing OATH
    # should take the 3-cell clear, leaving the first wild in play.
    g = _game(
        FakeBoard(
            {(0, 0): "X", (1, 0): "Y", (2, 0): "T", (3, 0): "H"},
            wild={(0, 0), (1, 0)},
        ),
    )
    g._begin_selection([(3, 0)])
    g._on_submit_word("oath")
    assert g._player_dict.added == [("oath", "?oa?|t|h")]
    # Only the three OATH cells cleared; the first wild remains on the board.
    assert g._board.cells == {(0, 0): "X"}


# --- nucleation + placed-cell requirement (stage 2) -------------------------

def test_nucleate_anywhere_keeps_words_without_placed_cells():
    # A word made purely of old cells (not touching any placed cell) still counts.
    g = _game(FakeBoard({}))
    placed = {(3, 0)}
    fw_touch = gs.FoundWord([(2, 0), (3, 0)], ["A", "B"], "AB")
    fw_far = gs.FoundWord([(7, 7), (8, 7)], ["C", "D"], "CD")
    assert g._rule_nucleate_anywhere([fw_touch, fw_far], placed) == [fw_touch, fw_far]


def test_require_placed_cell_filters_to_touching_words():
    g = _game(FakeBoard({}))
    placed = {(3, 0)}
    fw_touch = gs.FoundWord([(2, 0), (3, 0)], ["A", "B"], "AB")
    fw_far = gs.FoundWord([(7, 7), (8, 7)], ["C", "D"], "CD")
    out = g._rule_require_placed_cell([fw_touch, fw_far], placed)
    assert out == [fw_touch]


def test_placed_cell_optional_passes_all_through():
    g = _game(FakeBoard({}))
    fws = [gs.FoundWord([(7, 7)], ["C"], "C")]
    assert g._rule_placed_cell_optional(fws, {(3, 0)}) == fws


def test_anywhere_plus_require_placed_cell_composes():
    # CAT (row 0) sits apart from the placed D; CARD (row 2) is old CAR + placed
    # D. With nucleate_anywhere both purely-old CAT and CARD are candidates;
    # adding require_placed_cell drops CAT (no placed cell) but keeps CARD.
    g = _game(
        FakeBoard({(0, 0): "C", (1, 0): "A", (2, 0): "T",
                   (0, 2): "C", (1, 2): "A", (2, 2): "R", (3, 2): "D"})
    )
    g._nucleation_rule = g._rule_nucleate_anywhere
    g._move_placed = {(3, 2)}            # the placed D
    g._placed_cell_rule = g._rule_placed_cell_optional
    g._recompute_candidates()
    assert "CAT" in g._candidate_words   # purely-old word counts under anywhere
    assert "CARD" in g._candidate_words
    g._placed_cell_rule = g._rule_require_placed_cell
    g._recompute_candidates()
    assert "CAT" not in g._candidate_words   # no placed cell -> filtered out
    assert "CARD" in g._candidate_words      # touches the placed D -> kept


# --- fossil requirement (game_screen.fossil_requirement) --------------------

def test_require_fossil_cell_filters_to_touching_words():
    # With the first word already down (skip inactive), only words covering a
    # fossilized cell survive.
    g = _game(FakeBoard({}))
    g._fossilized_cells = {(3, 0)}
    g._words_cleared_this_game = 1
    fw_touch = gs.FoundWord([(2, 0), (3, 0)], ["A", "B"], "AB")
    fw_far = gs.FoundWord([(7, 7), (8, 7)], ["C", "D"], "CD")
    assert g._rule_require_fossil_cell([fw_touch, fw_far]) == [fw_touch]


def test_fossil_cell_optional_passes_all_through():
    g = _game(FakeBoard({}))
    g._words_cleared_this_game = 5   # ignored by the optional rule
    fws = [gs.FoundWord([(7, 7)], ["C"], "C")]
    assert g._rule_fossil_cell_optional(fws) == fws


def test_fossil_skip_first_word_waives_until_first_clear():
    # No word cleared yet -> the requirement is waived, so a fossil-free word
    # passes; once a word has cleared, the same word is filtered out.
    g = _game(FakeBoard({}))
    g._fossilized_cells = {(3, 0)}
    fw_far = gs.FoundWord([(7, 7), (8, 7)], ["C", "D"], "CD")
    g._words_cleared_this_game = 0
    assert g._rule_require_fossil_cell([fw_far]) == [fw_far]
    g._words_cleared_this_game = 1
    assert g._rule_require_fossil_cell([fw_far]) == []


def test_fossil_no_skip_enforces_from_first_word():
    # With the skip disabled, a fossil-free word is filtered even before any
    # word has cleared.
    g = _game(FakeBoard({}))
    g._fossil_first_word_rule = g._rule_fossil_no_skip
    g._words_cleared_this_game = 0
    fw_far = gs.FoundWord([(7, 7)], ["C"], "C")
    assert g._rule_require_fossil_cell([fw_far]) == []


def test_require_fossil_cell_composes_and_diagnoses():
    # CAT (row 0) is purely old; CARD (row 2) touches fossilized D. With the
    # fossil requirement on and a word already cleared, only CARD is a candidate,
    # and CAT's rejection is diagnosed as the fossil-specific reason.
    g = _game(
        FakeBoard({(0, 0): "C", (1, 0): "A", (2, 0): "T",
                   (0, 2): "C", (1, 2): "A", (2, 2): "R", (3, 2): "D"})
    )
    g._nucleation_rule = g._rule_nucleate_anywhere
    g._fossilized_cells = {(3, 2)}       # the D is fossilized
    g._words_cleared_this_game = 1       # skip inactive
    # Fossils must be walkable for a word to contain one, so the requirement is
    # only meaningful paired with fossil_word_use: rule_fossil_allow.
    g._fossil_is_wall_rule = g._rule_fossil_allow_is_wall
    g._fossil_word_ok_rule = g._rule_fossil_allow_word_ok
    g._fossil_requirement_rule = g._rule_require_fossil_cell
    g._recompute_candidates()
    assert "CARD" in g._candidate_words      # covers the fossilized D -> kept
    assert "CAT" not in g._candidate_words   # no fossil cell -> filtered out
    assert g._submission_error("CAT") == gs.get_string("err_not_fossil")


# --- partial gram usage (game_screen.gram_usage) ----------------------------

def _partial_game(board, min2=False):
    g = _game(board)
    g._gram_usage_rule = g._rule_gram_use_partial
    g._nucleation_rule = g._rule_nucleate_anywhere   # words anywhere, for focus
    if min2:
        g._word_length_rule = gs.rule_word_min2letters_min2cells
    g._phase = gs.Phase.SELECTING
    return g


def test_partial_gram_whole_rule_finds_only_full_grams():
    # Control: with the whole-gram rule, W + ING spells only WING, not WIN.
    g = _game(FakeBoard({(0, 0): "W", (1, 0): "ING"}))
    g._nucleation_rule = g._rule_nucleate_anywhere
    g._phase = gs.Phase.SELECTING
    g._recompute_candidates()
    assert "WING" in g._candidate_words
    assert "WIN" not in g._candidate_words


def test_partial_gram_prefix_leaves_suffix():
    # W + ING -> WIN (prefix IN of the last cell), leaving G on the board.
    g = _partial_game(FakeBoard({(0, 0): "W", (1, 0): "ING"}))
    g._recompute_candidates()
    assert "WIN" in g._candidate_words
    g._on_submit_word("win")
    assert g._moving_side_pane.cleared == ["WIN"]
    assert g._board.cells == {(1, 0): "G"}


def test_partial_gram_suffix_leaves_prefix():
    # ING + OO + D -> GOOD (suffix G of the first cell), leaving IN.
    g = _partial_game(FakeBoard({(0, 0): "ING", (1, 0): "OO", (2, 0): "D"}))
    g._recompute_candidates()
    assert "GOOD" in g._candidate_words
    g._on_submit_word("good")
    assert g._moving_side_pane.cleared == ["GOOD"]
    assert g._board.cells == {(0, 0): "IN"}


def test_partial_gram_batch_two_bites_leave_middle():
    # Batch: H ING O -> HI + GO bite both ends of ING, leaving its middle N.
    g = _partial_game(FakeBoard({(0, 0): "H", (1, 0): "ING", (2, 0): "O"}), min2=True)
    g._submit_clear_rule = g._rule_submit_defers
    g._endphase_clear_rule = g._rule_endphase_clear_pending
    g._recompute_candidates()
    g._on_submit_word("hi")
    g._on_submit_word("go")
    assert g._board.cells == {(0, 0): "H", (1, 0): "ING", (2, 0): "O"}  # held
    g._end_selection()
    assert sorted(g._moving_side_pane.cleared) == ["GO", "HI"]
    assert g._board.cells == {(1, 0): "N"}   # both ends eaten, middle remains


def test_partial_gram_batch_two_bites_can_clear_whole():
    # Batch: W ING O -> WIN + GO; prefix IN + suffix G eat all of ING, so it clears.
    g = _partial_game(FakeBoard({(0, 0): "W", (1, 0): "ING", (2, 0): "O"}), min2=True)
    g._submit_clear_rule = g._rule_submit_defers
    g._endphase_clear_rule = g._rule_endphase_clear_pending
    g._recompute_candidates()
    g._on_submit_word("win")
    g._on_submit_word("go")
    g._end_selection()
    assert g._board.cells == {}


# --- batch clearing (clear-at-phase-end) ------------------------------------

def _batch_game(board, **kwargs):
    g = _game(board, **kwargs)
    g._submit_clear_rule = g._rule_submit_defers
    g._endphase_clear_rule = g._rule_endphase_clear_pending
    return g


def test_batch_holds_words_until_phase_end_with_overlap():
    # TEAR and EAR share the A-R cells. In batch mode both are held (the board
    # never shrinks mid-phase, so the overlap is fine) and clear together only
    # when the phase ends.
    g = _batch_game(FakeBoard({(0, 0): "T", (1, 0): "E", (2, 0): "A", (3, 0): "R"}))
    g._begin_selection([(3, 0)])
    assert g._phase is gs.Phase.SELECTING
    g._on_submit_word("tear")
    g._on_submit_word("ear")
    # Held, not cleared: both listed, board untouched, nothing in the moving pane.
    assert g._selecting_side_pane.accepted == ["TEAR", "EAR"]
    assert g._board.cells != {}
    assert g._moving_side_pane.cleared == []
    g._end_selection()
    # The whole batch clears together; the union of both paths is gone.
    assert g._moving_side_pane.cleared == ["TEAR", "EAR"]
    assert g._board.cells == {}
    assert g._phase is gs.Phase.MOVING


def test_batch_single_path_word_rejected_on_repeat():
    g = _batch_game(FakeBoard({(0, 0): "T", (1, 0): "E", (2, 0): "A", (3, 0): "R"}))
    g._begin_selection([(3, 0)])
    g._on_submit_word("tear")
    g._on_submit_word("tear")  # only one way to spell TEAR here
    assert g._selecting_side_pane.accepted == ["TEAR"]
    assert g._selecting_side_pane.errors == [
        "Already selected (only one way to spell it here)"
    ]


def test_batch_same_word_allowed_once_per_distinct_path():
    # ANT spellable two ways (across the row, down the column) sharing only the A.
    # Each distinct path may be held once; a third submit is rejected.
    fw_row = gs.FoundWord([(0, 0), (1, 0), (2, 0)], ["A", "N", "T"], "ANT")
    fw_col = gs.FoundWord([(0, 0), (0, 1), (0, 2)], ["A", "N", "T"], "ANT")
    g = _batch_game(
        FakeBoard({(0, 0): "A", (1, 0): "N", (2, 0): "T", (0, 1): "N", (0, 2): "T"})
    )
    g._candidate_word_options = {"ANT": [fw_row, fw_col]}
    g._phase = gs.Phase.SELECTING
    g._on_submit_word("ant")
    g._on_submit_word("ant")
    assert g._selecting_side_pane.accepted == ["ANT", "ANT"]
    assert len(g._pending) == 2
    g._on_submit_word("ant")
    assert g._selecting_side_pane.errors == [
        "Every way to spell that here is already selected"
    ]


# --- disambiguation chooser (game_screen.clear_disambiguation) --------------
# ANT is spellable two ways (across the row, down the column) sharing only the A;
# the cycle rule offers both instead of auto-picking one.
def _ant_two_way_board():
    return FakeBoard({(0, 0): "A", (1, 0): "N", (2, 0): "T", (0, 1): "N", (0, 2): "T"})


def _ant_options():
    fw_row = gs.FoundWord([(0, 0), (1, 0), (2, 0)], ["A", "N", "T"], "ANT")
    fw_col = gs.FoundWord([(0, 0), (0, 1), (0, 2)], ["A", "N", "T"], "ANT")
    return fw_row, fw_col


def test_cycle_opens_chooser_without_clearing():
    # Submitting a word with two spellings opens the board chooser and commits
    # nothing until the player confirms.
    fw_row, fw_col = _ant_options()
    g = _batch_game(_ant_two_way_board())
    g._disambiguation_rule = g._rule_disambig_cycle_two_or_more_choices
    g._candidate_word_options = {"ANT": [fw_row, fw_col]}
    g._phase = gs.Phase.SELECTING
    g._on_submit_word("ant")
    assert g._disambiguating()
    assert g._selecting_side_pane.prompt == gs.get_string("disambig_prompt")
    assert g._disambig_lines.selected == 0                 # first highlighted
    assert len(g._disambig_lines.paths) == 2               # both candidates drawn
    assert g._pending == []                                # nothing held yet
    assert g._selecting_side_pane.accepted == []


def test_cycle_and_confirm_holds_highlighted_path():
    # Candidates order deterministically (fewest-cell, then by path): the column
    # spelling sorts first, so cycling once highlights the row, and confirming
    # holds exactly that path.
    fw_row, fw_col = _ant_options()
    g = _batch_game(_ant_two_way_board())
    g._disambiguation_rule = g._rule_disambig_cycle_two_or_more_choices
    g._candidate_word_options = {"ANT": [fw_row, fw_col]}
    g._phase = gs.Phase.SELECTING
    g._on_submit_word("ant")
    g._cycle_disambiguation(1)
    assert g._disambig_lines.selected == 1
    g._confirm_disambiguation()
    assert not g._disambiguating()
    assert g._selecting_side_pane.prompt is None           # chooser torn down
    assert g._selecting_side_pane.accepted == ["ANT"]
    assert len(g._pending) == 1
    assert g._pending[0].path == [(0, 0), (1, 0), (2, 0)]   # the row path chosen


def test_cycle_two_or_more_single_option_commits_immediately():
    # rule_disambig_cycle_two_or_more_choices: a lone spelling never opens the
    # chooser -- it holds at once (speed kept).
    fw_row, _ = _ant_options()
    g = _batch_game(FakeBoard({(0, 0): "A", (1, 0): "N", (2, 0): "T"}))
    g._disambiguation_rule = g._rule_disambig_cycle_two_or_more_choices
    g._candidate_word_options = {"ANT": [fw_row]}
    g._phase = gs.Phase.SELECTING
    g._on_submit_word("ant")
    assert not g._disambiguating()
    assert g._selecting_side_pane.accepted == ["ANT"]
    assert g._pending == [fw_row]
    assert g._disambig_lines.paths is None                  # chooser never drew


def test_cycle_one_or_more_single_option_opens_chooser():
    # rule_disambig_cycle_one_or_more_choices: a lone spelling STILL opens the
    # chooser (blue-path preview + explicit confirm), holding nothing until the
    # player confirms. The single-path prompt reads "confirm", not "select which".
    fw_row, _ = _ant_options()
    g = _batch_game(FakeBoard({(0, 0): "A", (1, 0): "N", (2, 0): "T"}))
    g._disambiguation_rule = g._rule_disambig_cycle_one_or_more_choices
    g._candidate_word_options = {"ANT": [fw_row]}
    g._phase = gs.Phase.SELECTING
    g._on_submit_word("ant")
    assert g._disambiguating()
    assert g._selecting_side_pane.prompt == gs.get_string("disambig_confirm_prompt")
    assert len(g._disambig_lines.paths) == 1               # the lone candidate drawn
    assert g._pending == []                                # nothing held yet
    assert g._selecting_side_pane.accepted == []
    # Confirming holds exactly that path.
    g._confirm_disambiguation()
    assert not g._disambiguating()
    assert g._pending == [fw_row]


def test_cycle_cancel_closes_without_holding():
    # word_clear (disambig_cancel: on) backs out: chooser closes, nothing held,
    # and the submitted word can be re-tried.
    fw_row, fw_col = _ant_options()
    g = _batch_game(_ant_two_way_board())
    g._disambiguation_rule = g._rule_disambig_cycle_two_or_more_choices
    g._candidate_word_options = {"ANT": [fw_row, fw_col]}
    g._phase = gs.Phase.SELECTING
    g._on_submit_word("ant")
    assert g._disambiguating()
    g._disambig_cancel_rule()
    assert not g._disambiguating()
    assert g._selecting_side_pane.prompt is None
    assert g._pending == []
    assert g._selecting_side_pane.accepted == []
    assert g._disambig_lines.paths is None


def test_instant_mode_routes_through_chooser():
    # Clear-on-submit also defers to the chooser: two spellings -> nothing clears
    # off the board until the player confirms.
    fw_row, fw_col = _ant_options()
    g = _game(_ant_two_way_board())                         # instant (default)
    g._disambiguation_rule = g._rule_disambig_cycle_two_or_more_choices
    g._candidate_word_options = {"ANT": [fw_row, fw_col]}
    g._phase = gs.Phase.SELECTING
    g._on_submit_word("ant")
    assert g._disambiguating()
    assert g._board.cells != {}                             # nothing cleared yet
    assert g._selecting_side_pane.accepted == []


# --- Constellation mode (game_screen.mode: rule_mode_constellation) ----------
# The typed word is assembled from grams anywhere on the board (no adjacency, no
# nucleation); _options_for / _submission_error route through the matcher when
# g._constellation is on. These reuse the _game harness with the flag flipped.

def _constellation_game(board):
    g = _game(board)
    g._constellation = True
    g._constellation_max_paths = 24
    g._constellation_turnover_rule = g._rule_constellation_no_replenish
    g._constellation_auto_end_rule = g._rule_constellation_auto_end_off
    g._phase = gs.Phase.SELECTING
    return g


def test_constellation_clears_word_from_scattered_cells():
    # C, A, T sit apart on the board; typing CAT clears all three (no adjacency).
    g = _constellation_game(FakeBoard({(0, 0): "C", (5, 5): "A", (2, 7): "T",
                                       (9, 1): "Z"}))
    g._on_submit_word("cat")
    assert "CAT" in g._cleared_word_history
    assert g._board.cells == {(9, 1): "Z"}                 # only the unused cell left
    assert g._selecting_side_pane.accepted == ["CAT"]


def test_constellation_stays_in_select_after_a_word():
    # No placed piece + board doesn't shrink under the typist => SELECT stays open
    # (unlimited words), unlike the adjacency modes' auto-close.
    g = _constellation_game(FakeBoard({(0, 0): "C", (5, 5): "A", (2, 7): "T",
                                       (1, 1): "D", (3, 3): "O", (7, 7): "G"}))
    g._on_submit_word("cat")
    assert g._phase is gs.Phase.SELECTING                  # did not end selection
    g._on_submit_word("dog")
    assert "DOG" in g._cleared_word_history


def test_constellation_rejects_word_not_on_board():
    g = _constellation_game(FakeBoard({(0, 0): "C", (1, 0): "A", (2, 0): "T"}))
    g._on_submit_word("dog")                               # a word, but no D/O/G
    assert g._cleared_word_history == set()
    assert g._board.cells == {(0, 0): "C", (1, 0): "A", (2, 0): "T"}


def test_constellation_rejects_non_word():
    g = _constellation_game(FakeBoard({(0, 0): "X", (1, 0): "Q", (2, 0): "Z"}))
    g._on_submit_word("xqz")                               # assembles, but not a word
    assert g._cleared_word_history == set()


def test_constellation_replenish_refills_only_vacated_empty_cells():
    # rule_constellation_replenish refills each cell the clear emptied (and only
    # those); _fill_one_player_cell needs the real piece machinery, so stub it to
    # record which cells it would refill and drop a placeholder gram in.
    g = _constellation_game(FakeBoard({(0, 0): "C", (5, 5): "A", (2, 7): "T",
                                       (9, 1): "Z"}))
    g._constellation_turnover_rule = g._rule_constellation_replenish
    refilled = []

    def fake_fill(x, y):
        refilled.append((x, y))
        g._board.cells[(x, y)] = "Q"        # a fresh gram lands here

    g._fill_one_player_cell = fake_fill
    g._on_submit_word("cat")
    # The three vacated cells refilled; the untouched Z cell was not.
    assert set(refilled) == {(0, 0), (5, 5), (2, 7)}
    assert (9, 1) not in refilled
    assert g._board.gram_at(9, 1).text == "Z"
    # Board never emptied: every cell holds a gram again.
    assert all(g._board.gram_at(x, y) is not None for (x, y) in g._board.cells)


def test_constellation_no_replenish_leaves_cells_empty():
    g = _constellation_game(FakeBoard({(0, 0): "C", (5, 5): "A", (2, 7): "T"}))
    called = []
    g._fill_one_player_cell = lambda x, y: called.append((x, y))
    g._on_submit_word("cat")
    assert called == []                      # no-replenish never refills
    assert g._board.cells == {}
