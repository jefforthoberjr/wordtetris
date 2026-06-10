"""Interactive word-selection (the SELECTING phase) logic in GameScreen.

GameScreen needs a real window to construct, so these build a bare instance via
__new__ and wire only the attributes the selection pipeline touches: a fake
board, fake MOVING/SELECTING side panes that record what the UI was told to
show, and a fake player dictionary tracking lifetime words.
"""
from views import game_screen as gs


class _FakeSquare:
    """The render quad of a board cell; only its .color is touched (when the
    placed piece settles from its light-blue tint), which the logic tests ignore."""

    def __init__(self):
        self.color = None


class _FakeCell:
    def __init__(self):
        self.square = _FakeSquare()


class FakeBoard:
    """Sparse {(x, y): letter} board with the methods the pipeline calls. Square
    geometry (four cardinals) so words snake/turn freely."""

    def __init__(self, cells):
        self.cells = dict(cells)

    def letter_at(self, x, y):
        return self.cells.get((x, y))

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

    def clear_cell(self, x, y):
        self.cells.pop((x, y), None)


class FakePane:
    """Stand-in for the SELECTING side pane (game_screen._selecting_side_pane)."""

    def __init__(self):
        self.accepted = []
        self.errors = None
        self.began = False
        self.word_count = None

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


class FakeSidepane:
    """Stand-in for the MOVING side pane (game_screen._moving_side_pane)."""

    def __init__(self):
        self.cleared = []
        self.word_count = None

    def add_cleared_words(self, words, new_flags=None):
        self.cleared += list(words)

    def set_word_count(self, count):
        self.word_count = count


class FakePlayerDict:
    """Stand-in for the persistent PlayerDictionary: tracks lifetime words so
    add() can report whether each cleared word was new (which colors it green)."""

    def __init__(self):
        self._words = set()

    def __len__(self):
        return len(self._words)

    def contains(self, word):
        return word.lower() in self._words

    def add(self, word, variation=None):
        w = word.lower()
        is_new = w not in self._words
        self._words.add(w)
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
    g._nucleation_rule = g._rule_adjacent_to_placed_piece
    g._moving_side_pane = FakeSidepane()
    g._piece_pool = FakePool()
    g._selecting_side_pane = FakePane()
    g._player_dict = FakePlayerDict()
    # Square separator so _clear_paths can encode the cleared word's grouping for
    # the player dictionary (these tests run square-geometry boards).
    g._gram_separator = "|"
    g._dictionary_count_rule = gs.rule_show_dictionary_count
    # No victory in these selection-logic tests, and no starting obstacles to
    # track; the victory rule just reports "not won" so flow proceeds normally.
    g._original_cells = set()
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
