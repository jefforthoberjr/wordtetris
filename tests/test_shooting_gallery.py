"""Shooting-gallery mode: the ShootingField batch-fade churn and the
ShootingGalleryMode shoot-to-spell input (greedy submit, miss timeout, buffer
resync). Fakes stand in for the board / pane / fade handles so the logic is tested
without a GL window (mirrors the other view tests' __new__ + fake-board style)."""

import random

from views import moving_mode as mm


# --- fakes -----------------------------------------------------------------
class _Handle:
    """A fade handle recorder: remembers the last progress fraction applied."""
    def __init__(self):
        self.frac = None

    def set_progress(self, frac):
        self.frac = frac


class _FieldBoard:
    """Grid of empty cells the field fills/clears; tracks occupancy only."""
    def __init__(self, w, h):
        self.width = w
        self.height = h
        self.occupied = set()

    def is_valid(self, x, y):
        return 0 <= x < self.width and 0 <= y < self.height

    def is_cell_occupied(self, x, y):
        return (x, y) in self.occupied

    def get_cell(self, x, y):
        return object()

    def clear_cell(self, x, y):
        self.occupied.discard((x, y))


class _FieldGS:
    """Minimal GameScreen surface ShootingField reaches: the board, the gram fill,
    and the two fade-handle builders."""
    def __init__(self, w=4, h=4):
        self._board = _FieldBoard(w, h)
        self.fills = []

    def _fill_one_player_cell(self, x, y):
        self._board.occupied.add((x, y))
        self.fills.append((x, y))

    def _add_cell_label_fade_handle(self, into, cell):
        into.append(_Handle())

    def _add_cell_background_fade_handles(self, into, cell):
        into.append(_Handle())


def _field(gs, batch_size=3, batch_count=1, batch_delay=2.0, fade_in=1.0,
           hold=0.0, fade_out=2.0, shot_fade=0.5):
    return mm.ShootingField(gs, batch_size, batch_count, batch_delay, fade_in,
                            hold, fade_out, shot_fade)


# --- ShootingField lifecycle ----------------------------------------------
def test_start_spawns_one_batch_of_batch_size():
    random.seed(1)
    gs = _FieldGS()
    f = _field(gs, batch_size=3)
    f.start()
    assert len(f.active_positions()) == 3
    # Every spawned cell is a filled, occupied board cell.
    assert set(f.active_positions()) == set(gs.fills) == gs._board.occupied


def test_batch_caps_at_available_empty_cells():
    random.seed(2)
    gs = _FieldGS(w=2, h=1)          # only 2 cells exist
    f = _field(gs, batch_size=5)
    f.start()
    assert len(f.active_positions()) == 2


def test_cells_fade_in_then_out_then_clear():
    random.seed(3)
    gs = _FieldGS()
    f = _field(gs, batch_size=2, fade_in=1.0, fade_out=2.0)
    f.start()
    f.tick(0.5)                      # mid fade-in
    # A live cell exists and its handles are partway up.
    assert f.active_positions()
    # Run past fade_in + fade_out: every cell finishes and clears from the board.
    for _ in range(40):
        f.tick(0.1)
        if not f.active_positions():
            break
    assert f.active_positions() == []
    assert gs._board.occupied == set()   # cleared cells left the board


def test_inter_batch_delay_then_next_batch():
    random.seed(4)
    gs = _FieldGS()
    f = _field(gs, batch_size=2, batch_delay=2.0, fade_in=0.5, fade_out=0.5)
    f.start()
    first = set(f.active_positions())
    # Drain the first batch.
    for _ in range(30):
        f.tick(0.1)
        if not f.active_positions():
            break
    assert f.active_positions() == []
    # Within the delay, still empty.
    f.tick(1.0)
    assert f.active_positions() == []
    # Past the delay, a fresh batch spawns.
    f.tick(1.1)
    assert len(f.active_positions()) == 2


def test_shoot_marks_not_live_and_uses_fast_fade():
    random.seed(5)
    gs = _FieldGS()
    f = _field(gs, batch_size=1, fade_in=0.0, fade_out=10.0, shot_fade=0.5)
    f.start()
    pos = f.active_positions()[0]
    assert f.is_live(pos)
    f.tick(0.1)                      # finish the (instant) fade-in
    f.shoot(pos)
    assert not f.is_live(pos)        # shot cells are no longer shootable
    # The slow fade_out is 10s, but the shot fade is 0.5s -- the cell clears fast.
    for _ in range(10):
        f.tick(0.1)
        if not f.active_positions():
            break
    assert f.active_positions() == []


def test_empty_board_spawns_nothing_and_does_not_crash():
    gs = _FieldGS(w=1, h=1)
    gs._board.occupied.add((0, 0))   # the only cell is already occupied
    f = _field(gs, batch_size=3)
    f.start()
    assert f.active_positions() == []
    f.tick(5.0)                      # no batch to drain; must be a safe no-op


def test_hold_keeps_cell_fully_shown_before_fade_out():
    random.seed(11)
    gs = _FieldGS()
    f = _field(gs, batch_size=1, fade_in=1.0, hold=3.0, fade_out=1.0)
    f.start()
    pos = f.active_positions()[0]
    f.tick(1.0)                       # finish the fade-in
    cell = f._cell_at(pos)
    assert cell.phase == "hold" and cell.fraction == 1.0
    f.tick(2.0)                       # deep into the hold: still fully shown, alive
    cell = f._cell_at(pos)
    assert cell.phase == "hold" and cell.fraction == 1.0
    assert f.active_positions() == [pos]
    for _ in range(30):               # past hold + fade-out: cleared
        f.tick(0.1)
        if not f.active_positions():
            break
    assert f.active_positions() == []


def test_multiple_batches_run_concurrently_and_stagger():
    random.seed(12)
    gs = _FieldGS()                   # 16 empty cells: room for 3 batches of 2
    f = _field(gs, batch_size=2, batch_count=3, batch_delay=0.1,
               fade_in=0.1, hold=2.0, fade_out=0.1)
    f.start()
    # Staggered start: only the first batch is live at t=0.
    assert len(f.active_positions()) == 2
    peak = 0
    for _ in range(100):
        f.tick(0.1)
        peak = max(peak, len(f.active_positions()))
    # Long holds vs a short stagger: all three batches overlap at the peak.
    assert peak == 6


# --- ShootingGalleryMode input --------------------------------------------
class _ModeBoard:
    def __init__(self, cells):
        self.cells = dict(cells)     # (x, y) -> gram text
        self._live = set(cells)

    def cell_at(self, px, py):
        return (int(px), int(py))    # test passes grid coords straight through

    def gram_at(self, x, y):
        text = self.cells.get((x, y))
        return None if text is None else type("G", (), {"text": text})()

    def cell_center(self, x, y):
        return (x, y)


class _Pane:
    """Just enough of the merged pane for the mode: a typed buffer + feedback."""
    def __init__(self):
        self.typed = ""
        self.errors = None
        self.cleared = False

    def on_text(self, text):
        self.typed += text

    def is_empty(self):
        return self.typed == ""

    def clear_word(self):
        self.typed = ""

    def show_errors(self, messages, reason=None):
        self.errors = messages


class _StubField:
    """Stand-in ShootingField: a fixed live set, records shots."""
    def __init__(self, live):
        self._live = set(live)
        self.shot = []

    def is_live(self, pos):
        return pos in self._live

    def shoot(self, pos):
        self.shot.append(pos)
        self._live.discard(pos)

    def tick(self, dt):
        pass                          # the mode's update ticks the field; inert here


class _ModeGS:
    def __init__(self, board):
        self._board = board
        self._buttons = {"move_primary": 1}
        self._moving_side_pane = _Pane()
        self._shooting_word_timeout_seconds = 10.0
        # The shooting preset's rule: 3+ letters, any cell count.
        self._word_length_rule = lambda text, path: len(text) >= 3
        self.submitted = []

    def _shooting_submit(self, word, path, segments):
        self.submitted.append((word, list(path), list(segments)))
        self._moving_side_pane.clear_word()


def _mode(board, live):
    m = mm.ShootingGalleryMode.__new__(mm.ShootingGalleryMode)
    m._gs = _ModeGS(board)
    m._field = _StubField(live)
    m._crosshair = None
    m._buffer = []
    m._since_shot = 0.0
    return m


def test_greedy_submit_fires_when_buffer_is_a_word(monkeypatch):
    # is_word only for CAT, so shooting C-A-T auto-submits on the third shot.
    monkeypatch.setattr(mm, "is_word", lambda w: w == "CAT")
    board = _ModeBoard({(0, 0): "C", (1, 0): "A", (2, 0): "T"})
    m = _mode(board, live=[(0, 0), (1, 0), (2, 0)])
    for pos in [(0, 0), (1, 0), (2, 0)]:
        m.on_mouse_press(pos[0], pos[1], 1)
    assert m._gs.submitted == [("CAT", [(0, 0), (1, 0), (2, 0)], ["C", "A", "T"])]
    assert m._buffer == []                       # buffer reset after submit
    assert m._gs._moving_side_pane.typed == ""   # field cleared


def test_single_letter_word_does_not_submit(monkeypatch):
    # The dictionary's obscure tier accepts "S" as a word, but the length rule
    # (3+ letters) must stop a single-letter shot from clearing + scoring.
    monkeypatch.setattr(mm, "is_word", lambda w: w in ("S", "SO"))
    board = _ModeBoard({(0, 0): "S", (1, 0): "O"})
    m = _mode(board, live=[(0, 0), (1, 0)])
    m.on_mouse_press(0, 0, 1)          # "S": a word, but too short
    m.on_mouse_press(1, 0, 1)          # "SO": a word, but still too short
    assert m._gs.submitted == []
    assert m._word() == "SO"           # buffer keeps building toward a 3+ word


def test_three_letter_word_submits_over_a_shorter_prefix(monkeypatch):
    # SOB is 3 letters -> clears; the SO prefix did not.
    monkeypatch.setattr(mm, "is_word", lambda w: w in ("SO", "SOB"))
    board = _ModeBoard({(0, 0): "S", (1, 0): "O", (2, 0): "B"})
    m = _mode(board, live=[(0, 0), (1, 0), (2, 0)])
    for pos in [(0, 0), (1, 0), (2, 0)]:
        m.on_mouse_press(pos[0], pos[1], 1)
    assert m._gs.submitted == [("SOB", [(0, 0), (1, 0), (2, 0)], ["S", "O", "B"])]


def test_single_trigram_shot_is_a_valid_word(monkeypatch):
    # One shot on a trigram cell = 3 letters, 1 cell -> allowed under min1cell.
    monkeypatch.setattr(mm, "is_word", lambda w: w == "CAT")
    board = _ModeBoard({(0, 0): "CAT"})
    m = _mode(board, live=[(0, 0)])
    m.on_mouse_press(0, 0, 1)
    assert m._gs.submitted == [("CAT", [(0, 0)], ["CAT"])]


def test_single_cell_word_blocked_under_min2cells(monkeypatch):
    # Under the min2cells rule a lone trigram cell ("SON", 1 shot) must NOT clear;
    # chaining a second shot (SO + N) reaches 2 cells and submits.
    monkeypatch.setattr(mm, "is_word", lambda w: w in ("SON", "SO"))
    board = _ModeBoard({(0, 0): "SON", (1, 0): "SO", (2, 0): "N"})
    m = _mode(board, live=[(0, 0), (1, 0), (2, 0)])
    m._gs._word_length_rule = lambda text, path: len(text) >= 3 and len(path) >= 2
    m.on_mouse_press(0, 0, 1)                      # "SON" but only 1 cell
    assert m._gs.submitted == [] and m._word() == "SON"
    m._gs._moving_side_pane.clear_word()          # start fresh
    m._buffer = []
    m.on_mouse_press(1, 0, 1)                      # "SO" (1 cell) -> too few cells
    m.on_mouse_press(2, 0, 1)                      # "SON" across 2 cells -> clears
    assert m._gs.submitted == [("SON", [(1, 0), (2, 0)], ["SO", "N"])]


def test_too_short_valid_word_times_out(monkeypatch):
    # "SO" is a dictionary word but under the length floor: it must not linger --
    # the idle timeout clears it (the completeness test matches the submit gate).
    monkeypatch.setattr(mm, "is_word", lambda w: w == "SO")
    board = _ModeBoard({(0, 0): "S", (1, 0): "O"})
    m = _mode(board, live=[(0, 0), (1, 0)])
    m.on_mouse_press(0, 0, 1)
    m.on_mouse_press(1, 0, 1)
    assert m._word() == "SO"
    m.update(11.0)
    assert m._buffer == []


def test_shooting_empty_or_dead_cell_is_a_miss(monkeypatch):
    monkeypatch.setattr(mm, "is_word", lambda w: False)
    board = _ModeBoard({(0, 0): "Q"})
    m = _mode(board, live=[(0, 0)])              # (5, 5) is not live
    m.on_mouse_press(5, 5, 1)
    assert m._buffer == []                        # a miss changes nothing
    assert m._gs._moving_side_pane.typed == ""


def test_miss_timeout_clears_a_nonword_buffer(monkeypatch):
    monkeypatch.setattr(mm, "is_word", lambda w: False)
    board = _ModeBoard({(0, 0): "X", (1, 0): "Z"})
    m = _mode(board, live=[(0, 0), (1, 0)])
    m.on_mouse_press(0, 0, 1)
    m.on_mouse_press(1, 0, 1)
    assert m._word() == "XZ"
    m.update(5.0)                                 # under the 10s timeout: still there
    assert m._buffer
    m.update(6.0)                                 # crosses the timeout: cleared
    assert m._buffer == []
    assert m._gs._moving_side_pane.errors is not None


def test_buffer_resyncs_after_external_clear(monkeypatch):
    # The Clear-word button empties the pane directly; the next shot must start
    # fresh rather than extend the stale buffer.
    monkeypatch.setattr(mm, "is_word", lambda w: False)
    board = _ModeBoard({(0, 0): "A", (1, 0): "B"})
    m = _mode(board, live=[(0, 0), (1, 0)])
    m.on_mouse_press(0, 0, 1)
    assert m._word() == "A"
    m._gs._moving_side_pane.clear_word()          # external clear
    m.on_mouse_press(1, 0, 1)
    assert m._word() == "B"                        # not "AB"
