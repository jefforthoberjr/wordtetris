import math
import pyglet
from config import select_rule
from source import rand
from models.hex_grid import flattop_vertices
from views.shaders import get_shape_shader
import log_codes as L


def _clip_below(verts, y_line):
    """Sutherland-Hodgman clip of a convex polygon (the hex outline) to the
    half-plane y <= y_line -- the part of the cell filled by sand rising from the
    bottom. Returns the clipped vertex list (< 3 points when nothing is filled)."""
    out = []
    n = len(verts)
    for i in range(n):
        cur, nxt = verts[i], verts[(i + 1) % n]
        cur_in, nxt_in = cur[1] <= y_line, nxt[1] <= y_line
        if cur_in:
            out.append(cur)
        if cur_in != nxt_in:   # edge crosses the fill line -> add the crossing point
            t = (y_line - cur[1]) / (nxt[1] - cur[1])
            out.append((cur[0] + t * (nxt[0] - cur[0]), y_line))
    return out


# --- cursor-path rules (game_screen.cursor_path) ---------------------------
# Order in which the MOVING_TYPEWRITER cursor visits the board's cells. Each
# returns the full ordered list of (x, y) cells; the mode walks it, skipping
# fossilized/empty cells, and ends the game when it runs off the end. Swappable
# so future modes can sweep differently (boustrophedon, columns, spiral...).

def rule_cursor_typewriter(board):
    """Standard English-typewriter sweep: start top-left, run left->right across
    a line, then carriage-return down to the next line, ending bottom-right.
    Index space: start (0, height-1), end (width-1, 0). On a flat-top hex grid
    the rows are vertically offset, so the sweep looks jittery -- accepted."""
    cells = []
    for y in range(board.height - 1, -1, -1):
        for x in range(board.width):
            if board.is_valid(x, y):
                cells.append((x, y))
    return cells


CURSOR_PATH_RULES = {
    "rule_cursor_typewriter": rule_cursor_typewriter,
}


class MovingMode:
    """Strategy for the MOVING phase, selected by the game_screen.mode bundle.

    The GameScreen 'engine' owns everything shared between modes: the board and
    grid, the SELECT pipeline (begin_selection -> candidates -> clear), word
    finding, the dictionary, drawing, the menu, and the Phase state machine. A
    MovingMode owns only the MOVING phase -- how the 'active element' is
    presented and how one player input becomes one committed action that the
    engine then runs through the shared SELECT pipeline.

    The engine drives a mode through four hooks:
      start()                   -- set up the MOVING phase for a new game
      on_key_press(sym, mods)   -- a key, only while MOVING; returns handled bool
      on_mouse_press(x, y, btn) -- a click, only while MOVING
      advance()                 -- move to the next turn. Called exactly once per
                                   committed action, after the SELECT pipeline
                                   resolves -- whether or not a SELECTING phase
                                   actually ran (every select_trigger branch ends
                                   in one advance). So 'one action -> one advance'
                                   holds for any select cadence.

    A mode commits an action by calling engine._begin_selection(changed_cells);
    the engine decides (per game_screen.select_trigger) whether to open the
    interactive SELECTING phase or resolve at once, and either way calls back
    into advance() once. active_cells() reports the cells the active element
    occupies (for hover hiding and the word-piece swap).
    """

    def __init__(self, game_screen):
        self._gs = game_screen

    def start(self):
        raise NotImplementedError

    def on_key_press(self, symbol, modifiers):
        return False

    def on_mouse_press(self, x, y, button):
        pass

    def update(self, dt):
        """Per-tick hook, called by GameScreen.update only while MOVING. Most
        modes are event-driven and ignore it; the timed modes count down here."""
        pass

    def update_during_select(self, dt):
        """Per-tick hook, called by GameScreen.update only while SELECTING. Off by
        default -- only a mode whose clock spans both phases (the omniswap race
        variant) ticks here; every other mode leaves SELECT untimed."""
        pass

    def advance(self):
        raise NotImplementedError

    def active_cells(self):
        """The (grid_x, grid_y) cells the active element currently occupies."""
        return []


class JigsawMovingMode(MovingMode):
    """MOVING_JIGSAWPUZZLE -- the original mode. One live piece at a time, fed
    from a pool with no look-ahead; the player moves/rotates it freely and places
    it anywhere, then the next piece spawns. The piece-handling bodies still live
    on GameScreen; this mode wraps them so the engine talks through the common
    MovingMode hooks (the bodies may migrate here later -- the seam is what
    matters now)."""

    def start(self):
        self._gs._init_first_piece()

    def advance(self):
        self._gs._advance_piece()

    def active_cells(self):
        return self._gs._current_piece().get_cell_positions()

    def on_key_press(self, symbol, modifiers):
        gs = self._gs
        # A placed piece (already handed to the select pipeline) takes no more
        # movement keys until the next piece spawns.
        if gs._current_piece().placed:
            return False
        if gs._movement_rule(symbol, modifiers):
            return True
        if symbol in gs._keys["rotate_clockwise"]:
            gs._rotate_piece_cw()
            return True
        elif symbol in gs._keys["rotate_counterclockwise"]:
            gs._rotate_piece_ccw()
            return True
        elif symbol in gs._keys["place"]:
            gs._place_current_piece()
            return True
        return False

    def on_mouse_press(self, x, y, button):
        gs = self._gs
        # Left-click: a cleared-word click may swap the live piece for a word-
        # piece (consumes the click); otherwise it drives the piece on the board
        # -- click a cell it occupies to rotate, another on-board cell to jump it.
        if button == gs._buttons["move_primary"]:
            if gs._player_word_piece_rule(x, y):
                return
            gs._handle_move_click(x, y)
        # The place-piece button places the piece, the same as the place key.
        elif button == gs._buttons["place_piece"]:
            gs._place_current_piece()


class TypewriterMovingMode(MovingMode):
    """MOVING_TYPEWRITER -- a single-cell cursor sweeps the pre-filled board along
    a configured path (game_screen.cursor_path). Each turn the player performs
    exactly one action on the cursor cell, which commits into the shared SELECT
    pipeline; when that turn resolves (engine calls advance()), the cursor steps
    to the next live cell. Actions:
      - left-click another board cell  -> swap the two cells' grams
      - left-click a cleared pane word -> replace the cursor gram with that word
        (the word-piece feature, game_screen.player_word_piece)
      - spacebar                       -> pass (no board change, still a turn)
    The game ends ('finished') when the cursor runs off the board.

    Assumes a board pre-filled with single-cell grams (rule_formation_fill_player_diagonal)
    and game_screen.victory: rule_victory_none. The cursor only ever rests on a
    non-fossilized, occupied cell; fossilized/empty cells are skipped silently."""

    def __init__(self, game_screen):
        super().__init__(game_screen)
        self._path = []
        self._index = 0
        self._cursor = None   # (x, y) of the current cursor cell, None once ended

    def start(self):
        self._path = select_rule(
            "game_screen.cursor_path", CURSOR_PATH_RULES
        )(self._gs._board)
        self._cursor = None
        self._seek_from(0)

    def active_cells(self):
        return [self._cursor] if self._cursor is not None else []

    def advance(self):
        # Leave the current cell (drop the cursor tint), then step to the next.
        self._restore_cursor()
        self._seek_from(self._index + 1)

    # --- cursor traversal ------------------------------------------------
    def _seek_from(self, index):
        """Rest the cursor on the first live (non-fossilized, occupied) cell at or
        after `index`, tinting it. If none remain, end the game (finished)."""
        gs = self._gs
        while index < len(self._path):
            cell = self._path[index]
            if not gs._is_fossilized(cell) and gs._board.gram_at(*cell) is not None:
                break
            index += 1
        self._index = index
        if index >= len(self._path):
            self._cursor = None
            gs._enter_endgame()
            return
        self._cursor = self._path[index]
        self._tint_cursor()

    def _tint_cursor(self):
        cell = self._gs._board.get_cell(*self._cursor)
        if cell is not None and cell.square is not None:
            cell.square.color = self._gs.CURSOR_CELL_COLOR

    def _restore_cursor(self):
        if self._cursor is None:
            return
        gs = self._gs
        cell = gs._board.get_cell(*self._cursor)
        if cell is not None and cell.square is not None:
            cell.square.color = gs._cell_resting_color(self._cursor)

    # --- input -----------------------------------------------------------
    def on_key_press(self, symbol, modifiers):
        gs = self._gs
        if self._cursor is None:
            return False
        # Spacebar = pass: no board change, but still commit a turn (which may
        # open a SELECT phase per the cadence) and advance the cursor. The cursor
        # cell still counts as placed (see _commit_turn), so a word can nucleate
        # around it even on a pass.
        if symbol in gs._keys["place"]:
            self._commit_turn()
            return True
        return False

    def on_mouse_press(self, x, y, button):
        gs = self._gs
        if self._cursor is None or button != gs._buttons["move_primary"]:
            return
        # 1) A click on a cleared word in the right pane (word-piece feature):
        #    replace the cursor cell's gram with that whole word, then commit.
        if gs._word_piece_enabled:
            word = gs._moving_side_pane.word_at(x, y)
            if word:
                gs._board.relabel_cell(self._cursor[0], self._cursor[1], word)
                self._commit_turn()
                return
        # 2) A click on another board cell: swap grams with the cursor cell. Any
        #    non-fossilized, occupied cell anywhere is a valid swap source.
        cell = gs._board.cell_at(x, y)
        if cell is None or cell == self._cursor:
            return
        if gs._is_fossilized(cell) or gs._board.gram_at(*cell) is None:
            return
        self._swap_grams(self._cursor, cell)
        # The cursor cell is always placed; whether the swapped-in cell joins it is
        # configurable (game_screen.typewriter_swap). _commit_turn keeps the cursor
        # in either way and de-dups.
        self._commit_turn(gs._typewriter_swap_rule(self._cursor, cell))

    def _commit_turn(self, changed_cells=()):
        """Commit this turn into the shared SELECT pipeline. The cursor cell is
        ALWAYS a placed (nucleation) cell -- even on a pass -- so a word can
        always nucleate around where the cursor rests; `changed_cells` adds any
        others the action placed (e.g. a swapped-in cell, per
        game_screen.typewriter_swap). (Previously a pass committed an empty placed
        set, so no word could nucleate on a pass.)"""
        placed = [self._cursor]
        for cell in changed_cells:
            if cell != self._cursor:
                placed.append(cell)
        self._gs._begin_selection(placed)

    def _swap_grams(self, a, b):
        """Exchange the letters of two occupied cells, leaving each cell's own
        background square (so the cursor tint stays on the cursor cell)."""
        board = self._gs._board
        ta = board.gram_at(*a).text
        tb = board.gram_at(*b).text
        board.relabel_cell(a[0], a[1], tb)
        board.relabel_cell(b[0], b[1], ta)


class SandTimerField:
    """The MOVING_OMNISWAP sand-timer clock (game_screen.omniswap_timer:
    rule_omniswap_timer_sand). No global countdown -- instead up to `count` board
    cells are 'sand timers' at once. Each fills over `seconds`; if it fills before
    its gram is used in a word it FOSSILIZES in place and a fresh non-fossilized
    cell takes the slot. Using a sand cell's gram in a word fossilizes it via the
    normal clear-action, freeing the slot. A sand timer FOLLOWS ITS GRAM: a swap
    moves it (with its fill) to wherever the gram went. The game ends when the whole
    board is fossilized -- no cell left to time.

    Each active cell shows a bottom-up fill in the fossil color, clipped to the hex
    outline and drawn translucent (over the cell + gram) so the gram stays readable
    as it fills. On fossilize the fill is removed and the cell's own square goes
    solid fossil grey."""

    FILL_OPACITY = 150     # translucent so the gram reads through the rising sand

    def __init__(self, game_screen, count, seconds):
        self._gs = game_screen
        self._count = max(1, int(count))
        self._seconds = float(seconds)
        self._timers = {}     # active sand cell (x, y) -> elapsed seconds
        self._shapes = {}     # active sand cell (x, y) -> its fill Polygon

    # --- queries (renderer seam) -----------------------------------------
    def active_positions(self):
        return list(self._timers)

    def elapsed_fraction(self, pos):
        """0..1 fill of the sand timer at `pos`, or None if `pos` isn't one."""
        elapsed = self._timers.get(pos)
        return None if elapsed is None else min(1.0, elapsed / self._seconds)

    # --- lifecycle -------------------------------------------------------
    def start(self):
        self._timers = {}
        self._refill()
        self._render()

    def tick(self, dt):
        """Advance every sand timer; any that fills fossilizes in place, then the
        freed slots refill. Called each frame while MOVING and SELECTING, so the
        pressure is continuous across both phases."""
        filled = []
        for pos in list(self._timers):
            self._timers[pos] += dt
            if self._timers[pos] >= self._seconds:
                filled.append(pos)
        for pos in filled:
            del self._timers[pos]
            self._gs._fossilize_cell(pos)      # ran out -> fossilize in place
        if filled:
            self._after_change()
        self._render()                          # advance the fill height each frame

    def on_swap(self, a, b):
        """A swap exchanged the grams at a and b: move any sand timer to follow its
        gram to the other cell (keeping its fill)."""
        if a in self._timers or b in self._timers:
            moved = {}
            for pos, elapsed in self._timers.items():
                moved[b if pos == a else a if pos == b else pos] = elapsed
            self._timers = moved
        self._render()

    def on_word_committed(self):
        """After a submitted word's clear-action ran: any sand cell fossilized by it
        (its gram was used) frees its slot; then refill and maybe end the game."""
        for pos in [p for p in self._timers if self._gs._is_fossilized(p)]:
            del self._timers[pos]
        self._after_change()

    def repaint_all(self):
        """Re-assert the fills (the mode restores a cell's square color after a pick;
        the fill overlay is independent, so this just refreshes it)."""
        self._render()

    # --- internals -------------------------------------------------------
    def _after_change(self):
        self._refill()
        if not self._timers and not self._eligible():
            self._gs._enter_endgame()          # whole board fossilized -- nothing left to time
        self._render()

    def _refill(self):
        while len(self._timers) < self._count:
            pool = self._eligible()
            if not pool:
                break
            pos = pool[rand().randrange(len(pool))]
            self._timers[pos] = 0.0

    def _eligible(self):
        """Occupied, non-fossilized cells that aren't already a sand timer."""
        gs, board, out = self._gs, self._gs._board, []
        for y in range(board.height):
            for x in range(board.width):
                pos = (x, y)
                if (board.is_valid(x, y) and board.gram_at(x, y) is not None
                        and pos not in self._timers and not gs._is_fossilized(pos)):
                    out.append(pos)
        return out

    # --- rendering: the bottom-up hex-clipped fill -----------------------
    def _render(self):
        """Rebuild each active cell's rising fill and drop overlays for cells that
        stopped timing (expired / used / swapped away)."""
        for pos in [p for p in self._shapes if p not in self._timers]:
            self._shapes.pop(pos).delete()
        for pos in self._timers:
            self._draw_fill(pos, self.elapsed_fraction(pos))

    def _draw_fill(self, pos, fraction):
        old = self._shapes.pop(pos, None)
        if old is not None:
            old.delete()
        if fraction <= 0.0:                     # just picked -- nothing filled yet
            return
        cx, cy = self._gs._board.cell_center(*pos)
        verts = flattop_vertices(self._gs._cell_size, cx, cy)
        ys = [v[1] for v in verts]
        bottom, top = min(ys), max(ys)
        clipped = _clip_below(verts, bottom + fraction * (top - bottom))
        if len(clipped) < 3:                    # nothing filled yet -- no polygon
            return
        poly = pyglet.shapes.Polygon(
            *clipped, color=self._gs.FOSSILIZED_CELL_COLOR,
            batch=self._gs._sand_batch, program=get_shape_shader())
        poly.opacity = self.FILL_OPACITY
        self._shapes[pos] = poly


class OmniswapVsTimerMode(MovingMode):
    """MOVING_OMNISWAP -- a board pre-filled by the starting formation, no cursor
    sweep and no piece queue. The player freely swaps any two cells (a two-click
    pick-then-swap) against a countdown, opening the interactive SELECT phase with
    ENTER (or, in the per-phase variant, automatically when the timer expires).

    game_screen.omniswap_timer picks how the clock and endgame work:

    * rule_omniswap_timer_per_phase -- the countdown runs only while MOVING and is
      paused during SELECT (unlimited time there). Timer-zero forces a last-chance
      SELECT. Entering SELECT is a commitment: leaving it without submitting a word
      ends the game (a plain 'finished', not a win). Submitting at least one word
      fossilizes those cells (game_screen.clear_action) and returns to MOVING with
      the timer reset to full.

    * rule_omniswap_timer_race -- one continuous clock counts down across BOTH
      phases (shown on the moving and selecting panes alike). The player toggles
      MOVING/SELECT freely -- ENTER opens SELECT, Next piece returns to MOVING,
      neither ends the game -- racing to form as many words as possible. The
      instant the clock hits zero the game ends ('finished', no win check). The
      timer never resets; add_time() is the seam for future word-time bonuses.

    Pairs with the OMNISWAP preset: rule_formation_fill_player_diagonal (so every cell is
    swappable), rule_clear_fossilize, rule_victory_none, rule_nucleate_anywhere
    (no placed piece to nucleate around), rule_never_skip_select and
    rule_select_every_placement. The timer length is game_screen.omniswap_timer_
    seconds.

    (WIP: swapping into a truly EMPTY cell isn't handled yet -- under
    fill_player+fossilize the board never empties, so both swap ends are always
    occupied. Other formations that leave gaps are a follow-up.)"""

    def __init__(self, game_screen):
        super().__init__(game_screen)
        self._remaining = 0.0       # seconds left this moving phase
        self._last_shown = None     # last whole-second value pushed to the pane
        self._selected = None       # (x, y) of the first-click cell, or None
        self._sand = None           # SandTimerField when the sand variant is active

    def start(self):
        self._selected = None
        # Sand variant: per-cell sand timers instead of a global countdown.
        if self._gs._omniswap_timer_sand:
            self._sand = SandTimerField(
                self._gs, self._gs._sand_timer_count, self._gs._sand_timer_seconds)
            self._sand.start()
        else:
            self._reset_timer()

    def update(self, dt):
        # Called while MOVING (see GameScreen.update). The countdown variants tick
        # the global clock; the sand variant fills its per-cell timers.
        if self._sand is not None:
            self._sand.tick(dt)
        else:
            self._tick(dt)

    def update_during_select(self, dt):
        # Called while SELECTING. The race clock and the sand timers both span both
        # phases (continuous pressure); per-phase leaves SELECT untimed.
        if self._sand is not None:
            self._sand.tick(dt)
        elif self._gs._omniswap_timer_race:
            self._tick(dt)

    def _tick(self, dt):
        # Decrement the shared countdown and act when it hits zero. What zero means
        # is the variant's only timer difference: the race ends the game outright,
        # the per-phase one forces a last-chance SELECT.
        self._remaining -= dt
        if self._remaining <= 0:
            self._remaining = 0
            self._show_time()
            if self._gs._omniswap_timer_race:
                L.log_40002("race", "ended_game")
                self._gs._enter_endgame()
            else:
                L.log_40002("per_phase", "forced_select")
                self._enter_select()
            return
        self._show_time()

    def add_time(self, seconds):
        """Extend the countdown by `seconds` and repaint it. Scaffolding for
        future rules that reward a submitted word with extra time -- the timer is
        one running accumulator, so a bonus is just an add here."""
        self._remaining += seconds
        self._show_time()

    def advance(self):
        # Called once when SELECT resolves back to MOVING. The race variant runs
        # one continuous clock, so it neither resets nor surrenders -- the player
        # bounces between phases freely until the clock runs out. The per-phase
        # variant resets the clock to full for a fresh moving phase, or ends the
        # game if the player left SELECT without submitting any word.
        gs = self._gs
        self._clear_selection()
        if self._sand is not None:
            # Like race: free MOVING/SELECT toggling, no reset/surrender. A word may
            # have fossilized a sand cell (its gram was used) -- free that slot; the
            # field ends the game when the whole board is fossilized.
            self._sand.on_word_committed()
            return
        if gs._omniswap_timer_race:
            # Entering SELECT repainted the moving pane's top label with the
            # pieces count; restore the countdown there for the moving phase.
            self._last_shown = None
            self._show_time()
            return
        if gs._words_submitted_this_select == 0:
            gs._enter_endgame()
            return
        self._reset_timer()

    def active_cells(self):
        # No live piece to hover-hide; the pick cursor is just a tint.
        return []

    # --- input -----------------------------------------------------------
    def on_key_press(self, symbol, modifiers):
        # select_open (ENTER) commits to SELECT early (so the SELECT phase keeps
        # ENTER as its one action key: submit / surrender). Spacebar no longer
        # triggers SELECT -- in SELECT it clears the typed word -- which stops a
        # reflexive space tap from ending the game. Old behavior (place key /
        # spacebar):
        #   if symbol in self._gs._keys["place"]:
        if symbol in self._gs._keys["select_open"]:
            self._enter_select()
            return True
        return False

    def on_mouse_press(self, x, y, button):
        gs = self._gs
        if button != gs._buttons["move_primary"]:
            return
        # Word-piece (game_screen.player_word_piece): with a pick cursor down, a
        # click on a cleared word in the side pane replaces that cell's gram with
        # the whole word (its old gram disappears), then drops the cursor. With no
        # cursor placed yet, a pane-word click does nothing. Like the swap, this is
        # a plain MOVING board edit -- it does not commit to SELECT.
        if gs._word_piece_enabled and self._selected is not None:
            word = gs._moving_side_pane.word_at(x, y)
            if word:
                gs._board.relabel_cell(self._selected[0], self._selected[1], word)
                self._clear_selection()
                if self._sand is not None:
                    self._sand.repaint_all()
                return
        cell = gs._board.cell_at(x, y)
        if cell is None:
            return
        if self._selected is None:
            # First click: drop the pick cursor on an eligible (occupied, non-
            # fossilized) cell. Empty / fossilized clicks are ignored.
            if gs._is_fossilized(cell) or gs._board.gram_at(*cell) is None:
                return
            self._selected = cell
            self._tint(cell, gs.CURSOR_CELL_COLOR)
            return
        # Second click.
        if cell == self._selected:
            # Re-click the cursor cell: cancel the pick.
            self._clear_selection()
            if self._sand is not None:
                self._sand.repaint_all()   # the cancel restored resting; re-tint sand cells
            return
        if gs._is_fossilized(cell) or gs._board.gram_at(*cell) is None:
            # Invalid swap target (fossilized or empty): keep the cursor, ignore.
            return
        source = self._selected
        self._swap_grams(source, cell)
        self._restore(cell)
        self._clear_selection()
        # Sand timers follow their gram: move any timer on either swapped cell.
        if self._sand is not None:
            self._sand.on_swap(source, cell)

    # --- phase / timer helpers -------------------------------------------
    def _enter_select(self):
        """Leave MOVING for the interactive SELECT phase (timer-zero or ENTER).
        The pick cursor disappears; placed set is empty (nucleate anywhere). In
        the race variant the clock keeps running, so paint it on the selecting
        pane immediately (its header still reads the placeholder until then)."""
        self._clear_selection()
        self._gs._begin_selection([])
        if self._gs._omniswap_timer_race:
            self._last_shown = None
            self._show_time()

    def _reset_timer(self):
        self._remaining = float(self._gs._omniswap_timer_seconds)
        self._last_shown = None
        L.log_40001(int(self._remaining))
        self._show_time()

    def _show_time(self):
        secs = int(math.ceil(self._remaining))
        if secs != self._last_shown:
            self._last_shown = secs
            self._gs._moving_side_pane.set_time_label(secs)
            # The race clock is visible in SELECTING too; keep that pane in sync.
            if self._gs._omniswap_timer_race:
                self._gs._selecting_side_pane.set_time_label(secs)

    # --- pick-cursor helpers ---------------------------------------------
    def _clear_selection(self):
        if self._selected is not None:
            self._restore(self._selected)
            self._selected = None

    def _tint(self, cell, color):
        c = self._gs._board.get_cell(*cell)
        if c is not None and c.square is not None:
            c.square.color = color

    def _restore(self, cell):
        self._tint(cell, self._gs._cell_resting_color(cell))

    def _swap_grams(self, a, b):
        """Exchange the letters of two occupied cells (same as the typewriter
        swap), leaving each cell's own background square in place."""
        board = self._gs._board
        ta = board.gram_at(*a).text
        tb = board.gram_at(*b).text
        board.relabel_cell(a[0], a[1], tb)
        board.relabel_cell(b[0], b[1], ta)

