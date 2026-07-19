"""Line-blast mode (game_screen.mode = rule_mode_line_blast): the
LineBlastMovingMode pick-float-drop-line rhythm and the within-highlight
nucleation rule. Fakes stand in for the board / pane / piece so the logic is
tested without a GL window (mirrors the other view tests' __new__ + fake style)."""

import random

import pytest

from views import moving_mode as mm
from views.game_screen import GameScreen
from views.found_word import FoundWord
from models.gram import Gram
from models.square_tetrimino import SquareTetriminoType, SQUARE_TETRIMINO_ROTATIONS


# --- fakes -----------------------------------------------------------------
class _Obj:
    """A render object stand-in: records color/opacity and whether it was deleted."""
    def __init__(self):
        self.color = None
        self.opacity = 255
        self.deleted = False

    def delete(self):
        self.deleted = True


class _FakePiece:
    """SquarePiece stand-in built from ALL_PIECE_ROTATIONS geometry -- enough for
    the mode: position, rotate, cell positions/data, place. No GL."""
    def __init__(self, piece_type, cell_size, batch, visible=False,
                 gram_pick_rule=None, cell_color=None, dedup_grams=True):
        self._rotations = SQUARE_TETRIMINO_ROTATIONS[piece_type]
        self._state = 0
        self._shape = list(self._rotations[0])
        self._grams = gram_pick_rule(len(self._shape))
        self._gx = 0
        self._gy = 0
        self.placed = False
        self.visible = visible
        self._objs = [(_Obj(), _Obj()) for _ in self._shape]

    def set_position(self, gx, gy):
        self._gx, self._gy = gx, gy

    def rotate_cw(self):
        self._state = (self._state + 1) % len(self._rotations)
        self._shape = list(self._rotations[self._state])

    def rotate_ccw(self):
        self._state = (self._state - 1) % len(self._rotations)
        self._shape = list(self._rotations[self._state])

    def set_visible(self, visible):
        self.visible = visible

    def place(self):
        self.placed = True

    def get_cell_positions(self):
        return [(self._gx + dx, self._gy + dy) for dx, dy in self._shape]

    def pivot_offset(self):
        if (1, 1) in self._shape:
            return (1, 1)
        return min(self._shape, key=lambda o: (o[0] - 1) ** 2 + (o[1] - 1) ** 2)

    def get_cell_data(self):
        out = []
        for (dx, dy), (cell, label), gram in zip(self._shape, self._objs, self._grams):
            out.append((self._gx + dx, self._gy + dy, cell, label, gram, None))
        return out


class _Square:
    def __init__(self):
        self.color = None


class _BoardCell:
    def __init__(self):
        self.square = _Square()


class _Board:
    def __init__(self, w, h):
        self.width = w
        self.height = h
        self.occupied = {}                # (x, y) -> gram text
        self._cells = {(x, y): _BoardCell() for x in range(w) for y in range(h)}

    def is_valid(self, x, y):
        return 0 <= x < self.width and 0 <= y < self.height

    def is_cell_occupied(self, x, y):
        return (x, y) in self.occupied

    def get_cell(self, x, y):
        return self._cells.get((x, y))

    def cell_at(self, px, py):
        gx, gy = int(px), int(py)
        return (gx, gy) if self.is_valid(gx, gy) else None

    def center_cell(self):
        return (self.width // 2, self.height // 2)

    def place(self, x, y, square, label, gram=None, overlay=None):
        self.occupied[(x, y)] = gram.text if gram is not None else ""

    def clear_cell(self, x, y):
        self.occupied.pop((x, y), None)


class _Pane:
    def __init__(self):
        self.slots = None
        self.selected = None
        self.ended = False
        self._hit_end = False
        self._slot_hit = None

    def set_slots(self, specs, selected):
        self.slots = specs
        self.selected = selected

    def hit_end(self, x, y):
        return self._hit_end

    def slot_at(self, x, y):
        return self._slot_hit


class _GS:
    """Minimal GameScreen surface LineBlastMovingMode reaches."""
    SETTLED_CELL_COLOR = (255, 255, 255)

    def __init__(self, board, pool_size=8, slots=3):
        self._board = board
        self._moving_side_pane = _Pane()
        self._piece_class = _FakePiece
        self._piece_batch = None
        self._player_piece_types = list(SquareTetriminoType)
        self._cell_size = 10
        self._buttons = {"move_primary": 1}
        self._line_blast_pool_size = pool_size
        self._line_blast_slots = slots
        self._line_blast_valid_color = (0, 255, 0)
        self._line_blast_invalid_color = (255, 0, 0)
        self._line_blast_highlight_color = (150, 250, 150)
        self._line_blast_highlight = set()
        self.began = []
        self.ended = False

    # placement gates (real GameScreen versions do the same geometry)
    def _piece_on_board(self, piece):
        return all(self._board.is_valid(x, y) for (x, y) in piece.get_cell_positions())

    def _overlapped_cells(self, piece):
        return {(x, y) for (x, y) in piece.get_cell_positions()
                if self._board.is_cell_occupied(x, y)}

    def _begin_selection(self, placed):
        self.began.append(list(placed))

    def _enter_endgame(self):
        self.ended = True


def _mode(gs):
    m = mm.LineBlastMovingMode.__new__(mm.LineBlastMovingMode)
    m._gs = gs
    m._pool = []
    m._pool_index = 0
    m._slots = []
    m._selected = None
    m._floating = None
    m._floating_cell = None
    return m


@pytest.fixture(autouse=True)
def _fixed_grams(monkeypatch):
    # Deterministic, GL-free gram draws: every cell is an "A" (letters don't matter
    # to the placement/line logic under test).
    monkeypatch.setattr(mm, "pick_grams", lambda rule, n: [Gram("A") for _ in range(n)])
    monkeypatch.setattr(mm, "player_gram_pick_rule", lambda: (lambda n: None))


# --- pool + slots ----------------------------------------------------------
def test_start_builds_finite_pool_and_fills_slots():
    random.seed(1)
    gs = _GS(_Board(6, 6), pool_size=8, slots=3)
    m = _mode(gs)
    m.start()
    assert len(m._pool) == 8
    assert len(m._slots) == 3 and all(s is not None for s in m._slots)
    assert gs._moving_side_pane.slots == m._slots      # pushed to the pane


def test_pool_exhaustion_leaves_empty_slots():
    random.seed(2)
    gs = _GS(_Board(6, 6), pool_size=2, slots=3)       # fewer pool pieces than slots
    m = _mode(gs)
    m.start()
    assert m._slots[0] is not None and m._slots[1] is not None
    assert m._slots[2] is None                          # drained -> empty slot


# --- selecting a slot floats a piece --------------------------------------
def test_select_slot_floats_and_dims():
    random.seed(3)
    gs = _GS(_Board(6, 6))
    m = _mode(gs)
    m.start()
    m._select_slot(0)
    assert m._floating is not None and m._selected == 0
    assert gs._moving_side_pane.selected == 0           # dimmed preview


def test_floating_hidden_until_mouse_is_over_the_board():
    random.seed(31)
    gs = _GS(_Board(6, 6))
    m = _mode(gs)
    m.start()
    m._select_slot(0)
    # Built hidden: a slot is clicked from the side pane, so nothing floats yet.
    assert m._floating.visible is False
    m.on_mouse_motion(2, 2)                 # mouse moves onto the board -> revealed
    assert m._floating.visible is True
    m.on_mouse_motion(999, 2)               # mouse leaves the board (side pane) -> hidden
    assert m._floating.visible is False


def test_switching_slot_discards_previous_floating():
    random.seed(4)
    gs = _GS(_Board(6, 6))
    m = _mode(gs)
    m.start()
    m._select_slot(0)
    first = m._floating
    m._select_slot(1)
    # The old floating piece's render objects were deleted (no pile-up on switch).
    assert all(cell.deleted and label.deleted
               for _gx, _gy, cell, label, _g, _o in first.get_cell_data())
    assert m._selected == 1 and m._floating is not first


# --- placement -------------------------------------------------------------
def test_valid_drop_settles_cells_and_replenishes_slot():
    random.seed(5)
    gs = _GS(_Board(6, 6), pool_size=8)
    m = _mode(gs)
    m.start()
    used = m._slots[0]
    m._select_slot(0)
    m.on_mouse_motion(2, 2)                              # snap over empty cells
    piece = m._floating
    cells = piece.get_cell_positions()
    m.on_mouse_press(2, 2, 1)                            # drop
    assert all(gs._board.is_cell_occupied(x, y) for (x, y) in cells)
    assert m._floating is None and m._selected is None
    assert m._slots[0] is not None and m._slots[0] is not used   # slot 0 refilled


def test_illegal_drop_over_occupied_is_a_noop():
    random.seed(6)
    board = _Board(6, 6)
    gs = _GS(board)
    m = _mode(gs)
    m.start()
    m._select_slot(0)
    m.on_mouse_motion(2, 2)
    # Occupy one of the cells the floating piece covers, so the drop must overlap.
    covered = m._floating.get_cell_positions()[0]
    board.occupied[covered] = "X"
    before = dict(board.occupied)
    m.on_mouse_press(2, 2, 1)
    assert board.occupied == before                     # nothing placed
    assert m._floating is not None                       # still in hand


def test_end_button_ends_the_game():
    random.seed(7)
    gs = _GS(_Board(6, 6))
    m = _mode(gs)
    m.start()
    gs._moving_side_pane._hit_end = True
    m.on_mouse_press(999, 10, 1)
    assert gs.ended is True


# --- line completion + clear ----------------------------------------------
def test_completed_row_opens_select_over_the_line():
    board = _Board(4, 4)
    # Pre-fill row y=0 except the last cell; the mode fills it to complete the row.
    for x in range(3):
        board.occupied[(x, 0)] = "A"
    gs = _GS(board)
    m = _mode(gs)
    # Force a single-cell drop at (3, 0) via a hand-made floating piece.
    m._selected = 0
    m._slots = [None]
    m._floating = _FakePiece(SquareTetriminoType.O, 10, None,
                             gram_pick_rule=lambda n: [Gram("A")] * n)
    # Shrink it to one cell at (3,0) so the drop completes the row exactly.
    m._floating._shape = [(0, 0)]
    m._floating._grams = [Gram("A")]
    m._floating._objs = [(_Obj(), _Obj())]
    m._floating.set_position(3, 0)
    m.on_mouse_press(3, 0, 1)
    assert gs._line_blast_highlight == {(0, 0), (1, 0), (2, 0), (3, 0)}
    assert gs.began == [[]]                              # SELECT opened


def test_advance_clears_the_whole_highlighted_line():
    board = _Board(4, 4)
    for x in range(4):
        board.occupied[(x, 1)] = "A"
    gs = _GS(board)
    gs._line_blast_highlight = {(0, 1), (1, 1), (2, 1), (3, 1)}
    m = _mode(gs)
    m.advance()
    # Every highlighted cell cleared, used in a word or not; highlight reset.
    assert all(not board.is_cell_occupied(x, 1) for x in range(4))
    assert gs._line_blast_highlight == set()


# --- within-highlight nucleation (bare GameScreen instance) ----------------
def test_nucleate_within_highlight_keeps_only_inline_words():
    g = GameScreen.__new__(GameScreen)
    g._line_blast_highlight = {(0, 0), (1, 0), (2, 0)}
    inside = FoundWord([(0, 0), (1, 0), (2, 0)], ["C", "A", "T"], "CAT")
    straddle = FoundWord([(1, 0), (1, 1)], ["A", "T"], "AT")   # (1,1) not highlighted
    kept = g._rule_nucleate_within_highlight([inside, straddle], [])
    assert kept == [inside]


def test_nucleate_within_highlight_empty_highlight_keeps_nothing():
    g = GameScreen.__new__(GameScreen)
    g._line_blast_highlight = set()
    fw = FoundWord([(0, 0)], ["A"], "A")
    assert g._rule_nucleate_within_highlight([fw], []) == []
