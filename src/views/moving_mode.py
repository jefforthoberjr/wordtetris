import math
import pyglet
from config import select_rule


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
        if symbol == gs._keys["rotate_clockwise"]:
            gs._rotate_piece_cw()
            return True
        elif symbol == gs._keys["rotate_counterclockwise"]:
            gs._rotate_piece_ccw()
            return True
        elif symbol == gs._keys["place"]:
            gs._place_current_piece()
            return True
        return False

    def on_mouse_press(self, x, y, button):
        gs = self._gs
        # Left-click: a cleared-word click may swap the live piece for a word-
        # piece (consumes the click); otherwise it drives the piece on the board
        # -- click a cell it occupies to rotate, another on-board cell to jump it.
        if button == pyglet.window.mouse.LEFT:
            if gs._player_word_piece_rule(x, y):
                return
            gs._handle_move_click(x, y)
        # Right-click places the piece, the same as the place key.
        elif button == pyglet.window.mouse.RIGHT:
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

    Assumes a board pre-filled with single-cell grams (rule_formation_fill_player)
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
        if symbol == gs._keys["place"]:
            self._commit_turn()
            return True
        return False

    def on_mouse_press(self, x, y, button):
        gs = self._gs
        if self._cursor is None or button != pyglet.window.mouse.LEFT:
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

    Pairs with the OMNISWAP preset: rule_formation_fill_player (so every cell is
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

    def start(self):
        self._selected = None
        self._reset_timer()

    def update(self, dt):
        # Called while MOVING (see GameScreen.update). Both variants tick here.
        self._tick(dt)

    def update_during_select(self, dt):
        # Called while SELECTING. Only the race variant keeps counting here -- its
        # one clock spans both phases; per-phase leaves SELECT untimed.
        if self._gs._omniswap_timer_race:
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
                self._gs._enter_endgame()
            else:
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
        # ENTER commits to SELECT early (so the SELECT phase keeps ENTER as its
        # one action key: submit / surrender). Spacebar no longer triggers SELECT
        # -- in SELECT it clears the typed word -- which stops a reflexive space
        # tap from ending the game. Old behavior (place key / spacebar):
        #   if symbol == self._gs._keys["place"]:
        if symbol in (pyglet.window.key.ENTER, pyglet.window.key.RETURN):
            self._enter_select()
            return True
        return False

    def on_mouse_press(self, x, y, button):
        gs = self._gs
        if button != pyglet.window.mouse.LEFT:
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
            return
        if gs._is_fossilized(cell) or gs._board.gram_at(*cell) is None:
            # Invalid swap target (fossilized or empty): keep the cursor, ignore.
            return
        self._swap_grams(self._selected, cell)
        self._restore(cell)
        self._clear_selection()

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

