import math
import pyglet
from config import select_rule, get_string
from source import rand
from models.hex_grid import flattop_vertices
from models.word_dictionary import is_word, is_prefix
from models.gram import Gram
from models.square_piece import ALL_PIECE_ROTATIONS, player_gram_pick_rule
from models.gram_picker import pick_grams
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

    # Whether this mode replaces stage-1 adjacency word-finding with the
    # constellation on-submit matcher (a typed word assembled from grams anywhere
    # on the board). The engine reads it to route the SELECT pipeline; only
    # ConstellationMode flips it True.
    finds_words_by_constellation = False

    # Whether this mode is an omniswap board: a fixed pool of freely-swappable
    # grams that shrinks (fossilizes) as words form, so it can be exhausted. The
    # engine reads it to gate the omniswap auto-end + F3 word sample; only
    # OmniswapVsTimerMode flips it True.
    is_omniswap = False

    # Whether this mode is the shooting gallery: cells are SHOT (not typed) to build
    # a word, greedily submitted the instant it is a dictionary word. The engine
    # reads it to draw the crosshair overlay + hide the system cursor; only
    # ShootingGalleryMode flips it True.
    is_shooting = False

    # Whether this mode is line blast: pieces are picked from a side-pane pool and
    # dropped on an empty board (a mouse-follow floating piece), and a filled row /
    # column opens SELECT over exactly those highlighted cells. The engine reads it
    # to route mouse motion to the mode and to swap in the line-blast moving pane;
    # only LineBlastMovingMode flips it True.
    is_line_blast = False

    # Whether this mode is botanical: an empty board but for a vertical stem column,
    # where a typed word crosses one stem cell and grows out both sides as leaf cells
    # (only the crossing chunk comes from the board). The engine reads it to route
    # word submission through the botanical placement matcher instead of the SELECT
    # clear pipeline; only BotanicalMode flips it True.
    is_botanical = False

    def __init__(self, game_screen):
        self._gs = game_screen

    def start(self):
        raise NotImplementedError

    def on_key_press(self, symbol, modifiers):
        return False

    def on_mouse_press(self, x, y, button):
        pass

    def request_select(self):
        """The player asked to open the SELECT phase now (the moving pane's
        Select button). Default: commit an empty placed set, so a word may
        nucleate anywhere on the current board -- the same as the omniswap
        ENTER/timer-zero path. Modes with live-piece bookkeeping may override
        (e.g. to first place or set aside the piece in hand)."""
        self._gs._begin_selection([])

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
        # A swap under an active hunt: re-light so highlights follow the moved
        # grams (relabel_cell re-synced each overlay's text).
        if self._gs._moving_side_pane.hunt_text():
            self._gs._refresh_hunt_highlight()


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

    def __init__(self, game_screen, count, seconds, delay=0.0):
        self._gs = game_screen
        self._count = max(1, int(count))
        self._seconds = float(seconds)         # the visible FILLING duration
        self._delay = float(delay)             # silent lead-in before the fill starts
        self._timers = {}     # active sand cell (x, y) -> elapsed seconds (delay + fill)
        self._shapes = {}     # active sand cell (x, y) -> its fill Polygon

    # --- queries (renderer seam) -----------------------------------------
    def active_positions(self):
        return list(self._timers)

    def elapsed_fraction(self, pos):
        """0..1 VISIBLE fill of the sand timer at `pos`, or None if `pos` isn't one.
        Stays 0 through the silent delay, then ramps over the filling duration."""
        elapsed = self._timers.get(pos)
        if elapsed is None:
            return None
        return min(1.0, max(0.0, (elapsed - self._delay) / self._seconds))

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
            if self._timers[pos] >= self._delay + self._seconds:   # delay + fill = full life
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
    swappable), rule_fossilize_cells, rule_victory_none, rule_nucleate_anywhere
    (no placed piece to nucleate around), rule_never_skip_select and
    rule_select_every_placement. The timer length is game_screen.omniswap_timer_
    seconds.

    (WIP: swapping into a truly EMPTY cell isn't handled yet -- under
    fill_player+fossilize the board never empties, so both swap ends are always
    occupied. Other formations that leave gaps are a follow-up.)"""

    is_omniswap = True

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
                self._gs, self._gs._sand_timer_count, self._gs._sand_timer_seconds,
                self._gs._sand_timer_delay_seconds)
            self._sand.start()
        else:
            self._reset_timer()

    def update(self, dt):
        # Called while MOVING (see GameScreen.update). The countdown variants tick
        # the global clock; the sand variant fills its per-cell timers.
        if self._sand is not None:
            self._sand.tick(dt)
            self._drop_selection_if_dead()
        else:
            self._tick(dt)

    def update_during_select(self, dt):
        # Called while SELECTING. The race clock and the sand timers both span both
        # phases (continuous pressure); per-phase leaves SELECT untimed.
        if self._sand is not None:
            self._sand.tick(dt)
            self._drop_selection_if_dead()
        elif self._gs._omniswap_timer_race:
            self._tick(dt)

    def _drop_selection_if_dead(self):
        """Force an un-select if the pick-cursor cell just fossilized (its sand
        timer filled) or emptied -- a now-dead cell must not be able to complete a
        swap that was mid-pick when it ran out."""
        if (self._selected is not None
                and (self._gs._is_fossilized(self._selected)
                     or self._gs._board.gram_at(*self._selected) is None)):
            self._clear_selection()

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
                held = self._selected
                gs._board.relabel_cell(self._selected[0], self._selected[1], word)
                self._clear_selection()
                if self._sand is not None:
                    self._sand.repaint_all()
                L.log_20005("word_piece", held)
                return
        cell = gs._board.cell_at(x, y)
        if cell is None:
            return
        if self._selected is None:
            # First click: drop the pick cursor on an eligible (occupied, non-
            # fossilized) cell. Empty / fossilized clicks are ignored.
            if gs._is_fossilized(cell) or gs._board.gram_at(*cell) is None:
                L.log_20005("ignored", cell)
                return
            self._selected = cell
            self._tint(cell, gs.CURSOR_CELL_COLOR)
            L.log_20005("picked", cell)
            return
        # Second click.
        if cell == self._selected:
            # Re-click the cursor cell: cancel the pick.
            self._clear_selection()
            if self._sand is not None:
                self._sand.repaint_all()   # the cancel restored resting; re-tint sand cells
            L.log_20005("canceled", cell)
            return
        if gs._is_fossilized(cell) or gs._board.gram_at(*cell) is None:
            # Invalid swap target (fossilized or empty): keep the cursor, ignore.
            L.log_20005("invalid_target", cell, self._selected)
            return
        source = self._selected
        self._swap_grams(source, cell)
        self._restore(cell)
        self._clear_selection()
        # Sand timers follow their gram: move any timer on either swapped cell.
        if self._sand is not None:
            self._sand.on_swap(source, cell)
        L.log_20005("swapped", cell, source)

    def request_select(self):
        """The moving pane's Select button: identical to the ENTER/timer-zero
        route into SELECT (drop the pick cursor, nucleate anywhere, keep the
        race clock painted on the selecting pane)."""
        self._enter_select()

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
        # A swap under an active hunt: re-light so highlights follow the moved
        # grams (relabel_cell re-synced each overlay's text).
        if self._gs._moving_side_pane.hunt_text():
            self._gs._refresh_hunt_highlight()



class PlantVsTimerMode(OmniswapVsTimerMode):
    """MOVING_PLANT -- a pre-filled swap board (the OmniswapVsTimerMode two-click
    pick-then-swap, inherited whole) grown around a fixed GREEN STEM: the board's
    center column is fossilized cells that each carry the game's random suffix
    multigram ROOT (e.g. -MENT), rendered blank green with the root shown on the
    bottom cell (see GameScreen._rule_formation_plant). The player swaps the loose
    grams into a prefix that snakes to the stem and types the whole word; because
    every stem cell carries the root gram and the plant fossil rule keeps the stem
    WALKABLE (branches wall off), the shared adjacency pathfinder finds GOVERN ->
    stem -> MENT = GOVERNMENT with no bespoke matcher. A word whose path touches a
    stem cell is a 'plant word'; one that doesn't is an ordinary refresh word.

    Unlike its omniswap parent this mode runs NO per-mode clock: the whole match is
    a single game_screen.game_timer countdown, ticked centrally by GameScreen.update,
    so start/update/advance here only manage the pick cursor. is_omniswap is False
    so the omniswap auto-end + F3 sample (which reason about plain dictionary words,
    not root-anchored plant words) stay dormant.

    Pairs with the PLANT preset: rule_formation_plant, rule_fossil_allow (the stem
    cells are fossilized-but-walkable, a plant word still needs a fresh prefix cell),
    rule_single_phase (swap + type inline), rule_nucleate_anywhere,
    rule_game_timer_on, rule_victory_none."""

    is_omniswap = False

    def start(self):
        # No sand field and no per-mode countdown; just a clean pick cursor. The
        # match clock is game_screen.game_timer, started + ticked by the engine.
        self._selected = None
        self._sand = None

    def update(self, dt):
        # The whole-match countdown lives on the engine (game_screen.game_timer);
        # nothing per-mode to tick.
        pass

    def update_during_select(self, dt):
        pass

    def advance(self):
        # A submitted word resolved; drop any pick cursor. One continuous clock, so
        # nothing to reset or surrender (unlike the omniswap per-phase variant).
        self._clear_selection()


class BotanicalMode(MovingMode):
    """MOVING_BOTANICAL -- a word-growing crossword. The board opens empty but for a
    vertical STEM column of per-cell grams down the center; the player types words
    that each cross ONE stem cell (its gram a contiguous chunk of the word) and grow
    horizontally out both sides as leaf cells, each up to a trigram (see
    GameScreen._botanical_submit). Only the crossing chunk comes from the board -- the
    rest of the word is freely typed and auto-placed -- and one leaf grows per stem
    cell.

    Like constellation there is no piece, cursor, swap or per-mode timer: the trivial
    MOVING phase is just the typing doorway (single-phase merged pane). The match runs
    on game_screen.game_timer and ends when it expires. Pairs with the BOTANICAL
    preset: rule_formation_botanical, rule_use_square_grid, rule_single_phase,
    rule_clear_none, rule_nucleate_anywhere, rule_repeat_allow, rule_victory_none,
    rule_game_timer_on (+ game_screen.end_video for the end clip)."""

    is_botanical = True

    def start(self):
        # Nothing to set up: the formation placed the stem, and there is no
        # piece/cursor/timer to initialize. Submission is handled in _on_submit_word.
        pass

    def advance(self):
        # Never reached: botanical places + records inline on submit and never opens
        # the SELECT clear pipeline, so no turn resolves back through here.
        pass

    def on_key_press(self, symbol, modifiers):
        # No board input in botanical: in single-phase the merged pane consumes ENTER
        # as the word submit and every letter as text, so the mode handles no keys.
        return False


class ConstellationMode(MovingMode):
    """MOVING_CONSTELLATION -- a pre-filled board the player never rearranges.
    There is no live piece, cursor, timer or swap: the whole game is typing words.
    The trivial MOVING phase is only the doorway into SELECT (ENTER, or the moving
    pane's Select button); once there, the player types word after word. A word is
    accepted when its letters can be assembled from grams sitting ANYWHERE on the
    board -- each cell used once, whole grams only -- with no adjacency and no
    nucleation (see GameScreen._constellation_match). The used cells then clear or
    fossilize (game_screen.clear_action) and a word_trail 'constellation' is drawn
    through them in spelled order (a jagged line, but the star analogy holds).

    Because there is no placed piece and the board never shrinks under the typist,
    the SELECT phase does NOT auto-close after a word (the piece-adjacency end-check
    is skipped for constellation); the player keeps typing until they press Next to
    return to MOVING, or an endgame victory rule fires (rule_victory_grid_fossilized
    with fossilize / rule_victory_grid_empty with remove).

    Pairs with the CONSTELLATION preset: a fill formation (every cell a gram),
    rule_nucleate_anywhere, rule_never_skip_select, rule_select_every_placement,
    rule_word_trail_on, rule_clear_on_submit + rule_unlimited_words (so many words
    clear in one SELECT visit), and a clear_action + matching victory rule."""

    finds_words_by_constellation = True

    def start(self):
        # Nothing to set up: the starting formation already filled the board and
        # there is no piece/cursor/timer to initialize.
        pass

    def advance(self):
        # One SELECT turn resolved back to MOVING. The board is the whole game
        # state -- nothing to reset, no next piece to spawn.
        pass

    def on_key_press(self, symbol, modifiers):
        # ENTER opens SELECT (the doorway to typing); SELECT keeps ENTER as its
        # submit key. No other MOVING input exists in this mode.
        if symbol in self._gs._keys["select_open"]:
            self._gs._begin_selection([])
            return True
        return False

    def request_select(self):
        """The moving pane's Select button: same as ENTER -- open SELECT with an
        empty placed set (a word may assemble anywhere)."""
        self._gs._begin_selection([])


class _ShootingCell:
    """One live shooting-gallery target: a placed cell whose render objects fade in,
    linger, then fade out. Drives the cell's own fade handles (AlphaFade / WhiteFade,
    the same ones the opening reveal + constellation replenish use) directly, ramping
    a single visible `fraction` (0 = gone, 1 = full) through three phases:
      'in'   -- fraction 0 -> 1 over fade_in seconds (the spawn bloom)
      'hold' -- fraction pinned at 1 for hold seconds (fully shown, no fade yet)
      'out'  -- fraction 1 -> 0 over the current duration (fade_out normally, or the
                fast shot_fade once shot), after which the cell is finished and its
                board cell is cleared by the field.
    Shootable in any phase; shoot() switches it straight to a fast fade-out that
    resumes from its current dimness so the fraction never jumps."""

    def __init__(self, handles, fade_in, hold, fade_out):
        self._handles = handles
        self._hold = max(0.0, float(hold))
        self._fade_out = max(0.0001, float(fade_out))
        self.phase = "in"
        self.duration = max(0.0001, float(fade_in))
        self.clock = 0.0
        self.fraction = 0.0
        self.shot = False
        self._apply()

    @property
    def finished(self):
        return self.phase == "out" and self.clock >= self.duration

    def advance(self, dt):
        self.clock += dt
        if self.phase == "in":
            self.fraction = min(1.0, self.clock / self.duration)
            if self.clock >= self.duration:      # bloom complete -> linger fully shown
                self._enter("hold", self._hold, 1.0)
        elif self.phase == "hold":
            self.fraction = 1.0
            if self.clock >= self.duration:      # linger over -> begin fading out
                self._enter("out", self._fade_out, 1.0)
        else:
            self.fraction = max(0.0, 1.0 - self.clock / self.duration)
        self._apply()

    def shoot(self, shot_fade):
        """Switch to the fast shot fade-out, resuming from the current visible
        fraction (so a cell shot mid-bloom / mid-hold keeps its brightness, then
        drops)."""
        self.shot = True
        self.phase = "out"
        self.duration = max(0.0001, float(shot_fade))
        self.clock = (1.0 - self.fraction) * self.duration

    def _enter(self, phase, duration, fraction):
        self.phase = phase
        self.duration = max(0.0001, float(duration))
        self.clock = 0.0
        self.fraction = fraction

    def _apply(self):
        for handle in self._handles:
            handle.set_progress(self.fraction)


class _BatchSlot:
    """One independently-cycling batch inside a ShootingField. Spawns a batch of
    cells (via the field), runs them through their fade, and once they have ALL
    cleared waits batch_delay before spawning the next -- its own clock, so several
    slots run on staggered ('alternating') schedules. Positions never collide across
    slots: the field only ever draws from currently-EMPTY board cells, and every live
    cell (any slot) is a placed, occupied board cell."""

    def __init__(self, field):
        self._field = field
        self.cells = {}           # (x, y) -> _ShootingCell owned by this slot
        self._between = 0.0        # seconds until this slot's next batch spawns

    def reset(self, initial_delay):
        self.cells = {}
        self._between = float(initial_delay)   # stagger before the FIRST batch

    def tick(self, dt):
        if not self.cells:
            self._between -= dt
            if self._between <= 0:
                self._field._spawn_batch_into(self)
            return
        finished = []
        for pos, st in self.cells.items():
            st.advance(dt)
            if st.finished:
                finished.append(pos)
        for pos in finished:
            del self.cells[pos]
            self._field._gs._board.clear_cell(*pos)
        if not self.cells:
            self._between = self._field._batch_delay


class ShootingField:
    """The MOVING_SHOOTING_GALLERY churn (game_screen.shooting_*). The board opens
    empty (rule_formation_empty); this field spawns grams in fading BATCHES for the
    player to shoot. A batch is up to `batch_size` random empty cells, each given a
    fresh player gram (via _fill_one_player_cell), faded IN over `fade_in`, held fully
    shown for `hold`, then faded OUT over `fade_out` before its board cell is cleared.
    Shooting a cell switches it to the fast `shot_fade` (its gram was already banked
    in the buffer at the shot, so the fast fade is purely visual). Cells are shootable
    throughout their whole life -- mid fade-in, hold, or fade-out alike.

    `batch_count` batches run at once, each an independent _BatchSlot on its own
    clock. At start their first spawns are staggered across one full cycle so the
    batches fade on alternating schedules (e.g. 5 batches of 10 rippling across the
    board) rather than all blooming together. Each slot, once its batch clears, waits
    `batch_delay` and respawns. A single batch (batch_count=1) is the original churn.

    Structural twin of SandTimerField: an owned per-cell timer field the mode ticks
    each frame across MOVING; here the cells appear/vanish rather than fossilize."""

    def __init__(self, game_screen, batch_size, batch_count, batch_delay,
                 fade_in, hold, fade_out, shot_fade):
        self._gs = game_screen
        self._batch_size = max(1, int(batch_size))
        self._batch_delay = float(batch_delay)
        self._fade_in = float(fade_in)
        self._hold = float(hold)
        self._fade_out = float(fade_out)
        self._shot_fade = float(shot_fade)
        self._slots = [_BatchSlot(self) for _ in range(max(1, int(batch_count)))]

    # --- queries ---------------------------------------------------------
    def active_positions(self):
        out = []
        for slot in self._slots:
            out.extend(slot.cells)
        return out

    def _cell_at(self, pos):
        for slot in self._slots:
            st = slot.cells.get(pos)
            if st is not None:
                return st
        return None

    def is_live(self, pos):
        """A shootable cell: one this field owns (in any slot) not yet shot."""
        st = self._cell_at(pos)
        return st is not None and not st.shot

    # --- lifecycle -------------------------------------------------------
    def start(self):
        # Stagger each slot's FIRST batch across one full cycle so the batches fade
        # on alternating schedules instead of all at once. A lone slot starts at 0.
        cycle = self._fade_in + self._hold + self._fade_out + self._batch_delay
        stagger = cycle / len(self._slots)
        for i, slot in enumerate(self._slots):
            slot.reset(i * stagger)
        # Fire the zero-delay spawns now so the first (offset-0) batch is on the
        # board the instant play begins; later slots wait out their stagger in tick.
        self.tick(0.0)

    def shoot(self, pos):
        """Mark the cell at `pos` shot -> fast fade-out. No-op if it isn't live."""
        st = self._cell_at(pos)
        if st is not None and not st.shot:
            st.shoot(self._shot_fade)

    def tick(self, dt):
        """Advance every slot: fade its live cells, clear the finished ones, and
        respawn a drained batch after batch_delay. Called each frame while MOVING
        (paused with the menu, like every other play timer)."""
        for slot in self._slots:
            slot.tick(dt)

    # --- internals -------------------------------------------------------
    def _spawn_batch_into(self, slot):
        pool = self._empty_cells()
        for pos in self._sample(pool, min(self._batch_size, len(pool))):
            self._gs._fill_one_player_cell(*pos)     # places a fresh gram + logs it
            cell = self._gs._board.get_cell(*pos)
            handles = []
            self._gs._add_cell_label_fade_handle(handles, cell)
            self._gs._add_cell_background_fade_handles(handles, cell)
            slot.cells[pos] = _ShootingCell(
                handles, self._fade_in, self._hold, self._fade_out)

    def _empty_cells(self):
        board = self._gs._board
        out = []
        for y in range(board.height):
            for x in range(board.width):
                if board.is_valid(x, y) and not board.is_cell_occupied(x, y):
                    out.append((x, y))
        return out

    def _sample(self, pool, n):
        """`n` distinct random cells from `pool`, drawn through the seeded rand() so
        a replay reproduces the same batch (mirrors SandTimerField._refill)."""
        pool = list(pool)
        chosen = []
        for _ in range(min(n, len(pool))):
            chosen.append(pool.pop(rand().randrange(len(pool))))
        return chosen


class Crosshair:
    """The MOVING_SHOOTING_GALLERY aiming reticle that follows the mouse: four arms
    (up / down / left / right) in the crosshair color with a blank gap at the very
    center, sized to about a cell. Owns its own batch, drawn over the board by
    GameScreen.draw while MOVING (and hidden with the system cursor when the pause
    menu is open)."""

    def __init__(self, half, gap, color):
        self._half = max(2.0, float(half))       # arm reach in px from center
        self._gap = max(0.0, float(gap))         # blank radius in px at center
        self._batch = pyglet.graphics.Batch()
        program = get_shape_shader()
        thickness = max(1.0, self._half * 0.06)
        self._lines = [
            pyglet.shapes.Line(0, 0, 0, 0, thickness=thickness, color=color,
                               batch=self._batch, program=program)
            for _ in range(4)
        ]
        self.move(-1000.0, -1000.0)              # start off-screen until first motion

    def move(self, x, y):
        g, h = self._gap, self._half
        segs = ((x, y + g, x, y + h), (x, y - g, x, y - h),
                (x - g, y, x - h, y), (x + g, y, x + h, y))
        for line, (x1, y1, x2, y2) in zip(self._lines, segs):
            line.x, line.y, line.x2, line.y2 = x1, y1, x2, y2

    def draw(self):
        self._batch.draw()


class ShootingGalleryMode(MovingMode):
    """MOVING_SHOOTING_GALLERY -- a fairground shooter over an otherwise-empty board.
    The ShootingField spawns grams in fading batches; the player aims a crosshair and
    left-clicks ("shoots") a cell to append its gram to a running buffer and blow the
    cell away (a fast fade). Detection is greedy: the instant the buffer spells a
    dictionary word it auto-submits for points (see GameScreen._shooting_submit) and
    the buffer clears; a non-word buffer left idle for shooting_word_timeout_seconds
    is declared a miss (an error blip, buffer cleared). No typing and no board
    rearrangement -- one continuous real-time phase against game_screen.game_timer.

    Pairs with the SHOOTING GALLERY preset: rule_formation_empty, rule_single_phase
    (the merged pane shows the buffer + Clear-word button), rule_game_timer_on with a
    300s clock, and rule_victory_none. The shot buffer is validated as a plain
    dictionary lookup, so the constellation matcher / pathfinder both sit idle."""

    is_shooting = True

    def __init__(self, game_screen):
        super().__init__(game_screen)
        self._field = None
        self._crosshair = None
        self._buffer = []          # [(pos, gram_text)] shot toward the current word
        self._since_shot = 0.0     # seconds since the last shot (miss timeout)

    def start(self):
        gs = self._gs
        self._buffer = []
        self._since_shot = 0.0
        self._field = ShootingField(
            gs, gs._shooting_batch_size, gs._shooting_batch_count,
            gs._shooting_batch_delay_seconds, gs._shooting_fade_in_seconds,
            gs._shooting_hold_seconds, gs._shooting_fade_out_seconds,
            gs._shooting_shot_fade_seconds)
        self._field.start()
        half = gs._cell_size * gs._shooting_crosshair_scale
        self._crosshair = Crosshair(half, half * gs._shooting_crosshair_gap,
                                    gs._crosshair_color)
        gs._window.set_mouse_visible(False)      # the crosshair replaces the cursor

    def advance(self):
        # No SELECT turn ever resolves here (detection is inline + automatic).
        pass

    def update(self, dt):
        self._field.tick(dt)
        # Miss timeout: an incomplete buffer left idle clears with an error blip.
        # Greedy detection auto-submits a COMPLETE word the instant it forms, so
        # between shots the buffer is never complete -- this only fires on a genuine
        # dead-end run (too short, or not a word). Uses the same completeness test as
        # the submit gate so a valid-but-too-short buffer (e.g. "AT") still times out.
        if self._buffer:
            self._since_shot += dt
            if (self._since_shot >= self._gs._shooting_word_timeout_seconds
                    and not self._is_complete_word()):
                self._miss()

    def active_cells(self):
        # No live piece to hover-hide; the crosshair is a pure overlay.
        return []

    # --- input -----------------------------------------------------------
    def on_mouse_press(self, x, y, button):
        gs = self._gs
        if button != gs._buttons["move_primary"]:
            return
        pos = gs._board.cell_at(x, y)
        if pos is None or not self._field.is_live(pos):
            L.log_20006("miss", pos, None, self._word())
            return
        gram = gs._board.gram_at(*pos)
        text = gram.text if gram is not None else ""
        if not text:
            # A wild / empty-text cell carries no fixed letters to spell with; treat
            # a shot on it as a miss (mirrors the matcher skipping wild cells).
            L.log_20006("miss", pos, None, self._word())
            return
        # Resync if the buffer was cleared out from under the mode (the Clear-word
        # button empties the pane directly), so the next shot starts a fresh word.
        if gs._moving_side_pane.is_empty():
            self._buffer = []
        self._buffer.append((pos, text))
        self._since_shot = 0.0
        self._field.shoot(pos)                   # fast fade-out (gram already banked)
        gs._moving_side_pane.on_text(text)       # mirror it into the buffer readout
        L.log_20006("hit", pos, text, self._word())
        if self._is_complete_word():
            self._submit()
        elif self._gs._misspell_instadeath and self._is_impossible_word():
            self._instadeath()

    def on_mouse_motion(self, x, y):
        if self._crosshair is not None:
            self._crosshair.move(x, y)

    def draw_crosshair(self):
        if self._crosshair is not None:
            self._crosshair.draw()

    # --- word buffer -----------------------------------------------------
    def _word(self):
        return "".join(text for _, text in self._buffer)

    def _is_complete_word(self):
        """Whether the shot buffer is a submittable word: a dictionary word that
        also passes the active game_screen.word_length rule (the shooting preset
        uses rule_word_min3letters_min1cell, so single-letter grams like S / O / T
        never clear). The length rule reads letters + cell count, so pass the shot
        cells as the path."""
        word = self._word()
        if not word:
            return False
        path = [pos for pos, _ in self._buffer]
        return is_word(word) and self._gs._word_length_rule(word, path)

    def _is_impossible_word(self):
        """Whether the shot buffer is a dead end: no active dictionary word begins
        with it, so no further shot can ever complete a word. Checked only after the
        complete-word test fails, so a buffer that IS a word never counts as
        impossible (a full word is a prefix of itself). Gates game_screen.
        misspell_instadeath."""
        word = self._word()
        return bool(word) and not is_prefix(word)

    def _submit(self):
        path = [pos for pos, _ in self._buffer]
        segments = [text for _, text in self._buffer]
        self._gs._shooting_submit(self._word(), path, segments)
        self._buffer = []
        self._since_shot = 0.0

    def _instadeath(self):
        """game_screen.misspell_instadeath: the shot buffer became an impossible word
        (no dictionary word begins with it), so end the game outright -- a spelling
        forfeit. This overrides any running game_timer because _enter_endgame moves
        the phase to VICTORY, where _tick_game_timer no longer counts down."""
        word = self._word()
        L.log_30006(word)
        self._buffer = []
        self._since_shot = 0.0
        self._gs._enter_endgame()

    def _miss(self):
        word = self._word()
        pane = self._gs._moving_side_pane
        pane.clear_word()
        pane.show_errors([get_string("err_shooting_miss")], "shooting_miss")
        L.log_30003(word, "shooting_miss")
        self._buffer = []
        self._since_shot = 0.0


class LineBlastMovingMode(MovingMode):
    """MOVING_LINE_BLAST -- pieces are preselected into a finite pool and offered a
    few at a time in the right pane (half-size previews). The player clicks a
    preview to take it in hand, then a copy FLOATS on the board following the mouse
    (snapped to the grid, half alpha, tinted green where it would land legally, red
    where it would not); left/right arrows rotate it. A board click drops it -- but
    only on a fully-on-board, ZERO-OVERLAP spot (an illegal click does nothing).
    Placing a piece repopulates its pane slot from the pool.

    The instant a placement fills a whole row or column, those cells HIGHLIGHT and
    SELECT opens over exactly them: the player types as many words as the highlighted
    cells can spell (adjacency-pathable per square_grid.word_pathfinding, cells
    reusable across words), scoring each. On Next piece the ENTIRE highlighted set
    clears from the board (tetris line-clear, whether or not a cell was used in a
    word) and play returns to MOVING. There is no victory rule: the End-game button
    in the moving pane is the only end (auto-detect of an unplaceable hand is
    deferred).

    Pairs with the LINE BLAST preset: rule_formation_empty (the pool fills the board),
    rule_use_square_grid, rule_two_phase, rule_nucleate_within_highlight (words must
    lie inside the highlighted line), rule_clear_at_phase_end + rule_unlimited_words
    (batch several words before clearing), rule_select_click_none and
    rule_victory_none. See views/line_blast_side_pane.py for the preview pane."""

    is_line_blast = True

    FLOATING_OPACITY = 128     # half alpha for the mouse-follow floating piece

    def __init__(self, game_screen):
        super().__init__(game_screen)
        self._pool = []            # finite [(piece_type, (letters...))] preselected pool
        self._pool_index = 0       # next pool spec to deal into a slot
        self._slots = []           # per-slot spec or None (None = drained slot)
        self._selected = None      # index of the in-hand slot, or None
        self._floating = None      # the SquarePiece following the mouse, or None
        self._floating_cell = None # last grid cell under the cursor

    def start(self):
        gs = self._gs
        self._build_pool()
        self._selected = None
        self._floating = None
        self._floating_cell = None
        self._slots = [self._draw_from_pool() for _ in range(gs._line_blast_slots)]
        self._push_slots()

    def advance(self):
        """One SELECT turn resolved back to MOVING (Next piece). The submitted words
        already cleared + scored their own cells in the phase-end batch; now clear
        the REST of the highlighted line(s) too -- every highlighted cell goes,
        used in a word or not (the tetris line-clear) -- and drop the highlight."""
        gs = self._gs
        cleared = []
        for (x, y) in gs._line_blast_highlight:
            if gs._board.is_cell_occupied(x, y):
                gs._board.clear_cell(x, y)
                cleared.append((x, y))
        L.log_20007("line_clear", len(gs._line_blast_highlight))
        gs._line_blast_highlight = set()

    def request_select(self):
        """No manual Select in line blast -- SELECT opens only when a placement
        fills a line (see _try_place). The moving pane has no Select button, so this
        is never reached; kept inert so an accidental route can't nucleate nothing."""
        pass

    def active_cells(self):
        # The floating piece is half-alpha over the board on purpose (so overlaps
        # read through it), so nothing is hover-hidden.
        return []

    # --- input -----------------------------------------------------------
    def on_key_press(self, symbol, modifiers):
        gs = self._gs
        if self._floating is None:
            return False
        if symbol in gs._keys["rotate_clockwise"]:
            self._floating.rotate_cw()
            self._restyle_floating()
            return True
        if symbol in gs._keys["rotate_counterclockwise"]:
            self._floating.rotate_ccw()
            self._restyle_floating()
            return True
        return False

    def on_mouse_motion(self, x, y):
        cell = self._gs._board.cell_at(x, y)
        if self._floating is None:
            if cell is not None:
                self._floating_cell = cell
            return
        # The floating piece is shown ONLY while the mouse is over the board. A slot
        # is clicked from the side pane (off the board), so the piece is built hidden
        # and stays hidden until the player moves back onto the board here -- placing
        # it under the cursor rather than at a stale spot the player can't see coming.
        if cell is None:
            self._floating.set_visible(False)
            return
        self._floating_cell = cell
        self._snap_floating(cell)
        self._restyle_floating()
        self._floating.set_visible(True)

    def on_mouse_press(self, x, y, button):
        gs = self._gs
        if button != gs._buttons["move_primary"]:
            return
        # Right-pane controls first: the End-game button, then a piece preview.
        if gs._moving_side_pane.hit_end(x, y):
            gs._enter_endgame()
            return
        slot = gs._moving_side_pane.slot_at(x, y)
        if slot is not None:
            self._select_slot(slot)
            return
        # Otherwise a board click drops the in-hand piece (if the spot is legal).
        if self._floating is not None:
            self._try_place(x, y)

    # --- piece pool ------------------------------------------------------
    def _build_pool(self):
        """Preselect the whole finite pool up front: each piece a random player
        piece type with its cells' unigrams drawn through the configured player
        gram-pick. Seeded rand()/pick_grams keep it replay-reproducible."""
        gs = self._gs
        types = list(gs._player_piece_types)
        self._pool = []
        self._pool_index = 0
        for _ in range(gs._line_blast_pool_size):
            piece_type = types[rand().randrange(len(types))]
            n = len(ALL_PIECE_ROTATIONS[piece_type][0])
            letters = tuple(g.text for g in pick_grams(player_gram_pick_rule(), n))
            self._pool.append((piece_type, letters))
        L.log_20007("pool_built", len(self._pool))

    def _draw_from_pool(self):
        """The next pool spec, or None once the finite pool is exhausted (that slot
        then shows nothing -- the only time fewer than `slots` pieces are offered)."""
        if self._pool_index >= len(self._pool):
            return None
        spec = self._pool[self._pool_index]
        self._pool_index += 1
        return spec

    def _push_slots(self):
        self._gs._moving_side_pane.set_slots(list(self._slots), self._selected)

    # --- floating piece --------------------------------------------------
    def _select_slot(self, index):
        """Take the piece in slot `index` in hand: float a full-size copy on the
        board (at the last cursor cell) and dim the preview. Switching slots discards
        the previous floating piece."""
        if index >= len(self._slots) or self._slots[index] is None:
            return
        self._discard_floating()
        self._selected = index
        # Built HIDDEN: the mouse is on the side pane (a slot was just clicked), so
        # nothing floats on the board until the player moves back onto it
        # (on_mouse_motion snaps + reveals it under the cursor). Avoids a phantom
        # piece appearing at a spot the mouse isn't.
        self._floating = self._build_floating(self._slots[index])
        self._push_slots()
        L.log_20007("select_slot", index)

    def _build_floating(self, spec):
        gs = self._gs
        piece_type, letters = spec
        grams = [Gram(letter) for letter in letters]
        return gs._piece_class(
            piece_type, gs._cell_size, gs._piece_batch, visible=False,
            gram_pick_rule=lambda count: list(grams),
            cell_color=gs._line_blast_valid_color, dedup_grams=False)

    def _snap_floating(self, cell):
        """Position the floating piece so the cursor cell holds the piece's PIVOT
        cell (the rotation center that stays at offset (1,1); see
        SquarePiece.pivot_offset), rather than its (grid_x, grid_y) origin -- which
        for most shapes isn't even one of the piece's cells, leaving the cursor off
        to the side. The pivot offset is invariant under rotation, so the piece also
        turns about the cursor cell."""
        px, py = self._floating.pivot_offset()
        self._floating.set_position(cell[0] - px, cell[1] - py)

    def _floating_valid(self):
        """Whether the floating piece could be dropped where it sits: fully on the
        grid AND covering no occupied cell (the zero-overlap placement rule)."""
        piece = self._floating
        return (self._gs._piece_on_board(piece)
                and not self._gs._overlapped_cells(piece))

    def _restyle_floating(self):
        """Recolor the floating piece for its current spot: light green where a drop
        is legal, light red where it isn't, both at half alpha so occupied cells read
        through it."""
        gs = self._gs
        color = gs._line_blast_valid_color if self._floating_valid() else gs._line_blast_invalid_color
        for _gx, _gy, cell, label, _gram, _overlay in self._floating.get_cell_data():
            cell.color = color
            cell.opacity = self.FLOATING_OPACITY
            label.opacity = self.FLOATING_OPACITY

    def _discard_floating(self):
        """Drop the current floating piece's render objects (called on a switch /
        after a placement) so switching slots doesn't pile up shapes."""
        if self._floating is None:
            return
        for _gx, _gy, cell, label, _gram, _overlay in self._floating.get_cell_data():
            cell.delete()
            label.delete()
        self._floating = None

    def _try_place(self, x, y):
        """Drop the in-hand piece if the spot is legal (fully on board, zero
        overlap); an illegal click does nothing. On a legal drop the cells settle
        onto the board, the slot repopulates from the pool, and a completed line (if
        any) opens SELECT."""
        gs = self._gs
        cell_xy = gs._board.cell_at(x, y)
        if cell_xy is None:
            return
        # Snap to the clicked cell so a drop lands exactly where the click was, even
        # if no motion event moved the (possibly hidden) piece here first.
        self._snap_floating(cell_xy)
        piece = self._floating
        if not self._floating_valid():
            return
        # Reveal in case the piece was still hidden (clicked before a motion event
        # brought it onto the board), so the settled cells actually render.
        piece.set_visible(True)
        piece.place()
        placed = []
        for gx, gy, cell, label, gram, overlay in piece.get_cell_data():
            # Settle from the half-alpha green/red floating look to a plain board cell.
            cell.color = gs.SETTLED_CELL_COLOR
            cell.opacity = 255
            label.opacity = 255
            gs._board.place(gx, gy, cell, label, gram, overlay)
            placed.append((gx, gy))
        self._floating = None      # its render objects now belong to the board
        L.log_20007("place", len(placed))
        self._consume_selected_slot()
        lines = self._completed_line_cells()
        if lines:
            self._open_line_select(lines)

    def _consume_selected_slot(self):
        """Refill the just-placed slot from the pool (None when the pool is drained),
        keeping slot positions stable, then repaint the previews."""
        self._slots[self._selected] = self._draw_from_pool()
        self._selected = None
        self._push_slots()

    # --- line detection + select ----------------------------------------
    def _completed_line_cells(self):
        """The union of every cell in any fully-occupied row or column -- the cells
        that highlight and become the SELECT domain. Empty when the placement
        completed no line."""
        board = self._gs._board
        cells = set()
        for y in range(board.height):
            row = [(x, y) for x in range(board.width) if board.is_valid(x, y)]
            if row and all(board.is_cell_occupied(x, y) for (x, y) in row):
                cells.update(row)
        for x in range(board.width):
            col = [(x, y) for y in range(board.height) if board.is_valid(x, y)]
            if col and all(board.is_cell_occupied(x, y) for (x, y) in col):
                cells.update(col)
        return cells

    def _open_line_select(self, cells):
        """Highlight the completed line(s) and open the interactive SELECT phase
        over exactly those cells (the nucleation rule keeps only words that lie
        wholly inside the highlight). Words are found/scored by the shared pipeline;
        _begin_selection([]) enters SELECT with no placed-piece nucleation tie."""
        gs = self._gs
        gs._line_blast_highlight = set(cells)
        for (x, y) in cells:
            cell = gs._board.get_cell(x, y)
            if cell is not None and cell.square is not None:
                cell.square.color = gs._line_blast_highlight_color
        L.log_20007("line_select", len(cells))
        gs._begin_selection([])
