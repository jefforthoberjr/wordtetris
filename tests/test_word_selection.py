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

    def cell_at(self, px, py):
        # The select-click rule maps a pixel to a cell; these tests pass cell
        # coordinates straight through, returning None off the populated board.
        return (px, py) if (px, py) in self.cells else None

    def clear_cell(self, x, y):
        self.cells.pop((x, y), None)


class FakePane:
    """Stand-in for the SELECTING side pane (game_screen._selecting_side_pane)."""

    def __init__(self):
        self.accepted = []
        self.errors = None
        self.began = False
        self.word_count = None
        self.typed_grams = []

    def begin(self):
        self.began = True
        self.accepted = []
        self.errors = None

    def accept_word(self, word, is_new=False):
        # is_new (word never collected before -> listed green) is recorded by
        # production; the selection-logic tests only assert which words were
        # accepted, so the flag is accepted but unused here.
        self.accepted.append(word)
        self.errors = None

    def show_errors(self, messages):
        self.errors = list(messages)

    def set_word_count(self, count):
        self.word_count = count

    def type_gram(self, text):
        # Records grams the board click-to-type rule sends; empty (wild) grams
        # add nothing, mirroring the real pane.
        if text:
            self.typed_grams.append(text)


class FakeSidepane:
    """Stand-in for the MOVING side pane (game_screen._moving_side_pane)."""

    def __init__(self):
        self.cleared = []
        self.word_count = None

    def add_cleared_words(self, words, new_flags=None):
        self.cleared += list(words)

    def set_word_count(self, count):
        self.word_count = count

    def set_phase_label(self, count):
        # The "Pieces: N" countdown; recorded but unused by these logic tests.
        self.phase_label = count


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


class _InteractiveStub:
    interactive = True


def _game(board, interactive=True, history=None):
    g = gs.GameScreen.__new__(gs.GameScreen)
    g._word_length_rule = gs.rule_word_min3letters_min2cells
    g._cleared_word_history = set(history or ())
    g._repeat_rule = lambda w: w not in g._cleared_word_history
    g._nucleation_rule = g._rule_adjacent_to_placed_pieces
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
    g._moving_side_pane = FakeSidepane()
    g._piece_pool = FakePool()
    g._selecting_side_pane = FakePane()
    g._player_dict = FakePlayerDict()
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
    assert g._selecting_side_pane.errors is None


def test_non_dictionary_word_errors():
    g = _game(FakeBoard({(0, 0): "T", (1, 0): "E", (2, 0): "A", (3, 0): "R"}))
    g._begin_selection([(3, 0)])
    g._on_submit_word("zzz")
    assert g._selecting_side_pane.errors == ["Word is not in the dictionary"]


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


# --- select-phase board clicks (type-gram shortcut) -------------------------

def test_select_click_types_gram_no_validation():
    # Clicking board cells types their grams into the field with no rules: any
    # occupied cell counts, repeats and non-adjacent cells included. Off-board /
    # empty clicks add nothing.
    g = _game(FakeBoard({(0, 0): "C", (1, 0): "A", (2, 0): "T", (5, 5): "S"}))
    g._select_click_rule = g._rule_select_click_type_gram
    g._rule_select_click_type_gram(2, 0)     # T
    g._rule_select_click_type_gram(0, 0)     # C
    g._rule_select_click_type_gram(0, 0)     # C again (repeat allowed)
    g._rule_select_click_type_gram(5, 5)     # S (non-adjacent allowed)
    g._rule_select_click_type_gram(9, 9)     # off-board: ignored
    assert g._selecting_side_pane.typed_grams == ["T", "C", "C", "S"]


def test_select_click_none_does_nothing():
    g = _game(FakeBoard({(0, 0): "C", (1, 0): "A", (2, 0): "T"}))
    g._rule_select_click_none(1, 0)
    assert g._selecting_side_pane.typed_grams == []


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
