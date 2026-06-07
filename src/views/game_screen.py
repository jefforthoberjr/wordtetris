import math
import random
import pyglet
from views.ingame_menu import IngameMenu
from views.side_pane import SidePane
from controllers.screen_manager import ScreenType
from models.piece_pool import PiecePool
from models.square_piece import SquarePiece, PIECE_TYPES
from models.square_piece import OBSTACLE_PIECE_TYPES as SQUARE_OBSTACLE_PIECE_TYPES
from models.square_piece import OBSTACLE_GRAM_PICK_RULE as SQUARE_OBSTACLE_GRAM_PICK_RULE
from models.hex_piece import HexPiece, PIECE_TYPES as HEX_PIECE_TYPES
from models.hex_piece import OBSTACLE_PIECE_TYPES as HEX_OBSTACLE_PIECE_TYPES
from models.hex_piece import OBSTACLE_GRAM_PICK_RULE as HEX_OBSTACLE_GRAM_PICK_RULE
from models.hex_domino import hex_neighbor
from models.hex_domino import HEX_UP, HEX_DOWN
from models.hex_domino import HEX_UP_LEFT, HEX_DOWN_LEFT
from models.hex_domino import HEX_UP_RIGHT, HEX_DOWN_RIGHT
from models.square_grid import SquareGrid
from models.hex_grid import HexGrid
from models.word_dictionary import is_word, is_prefix, select_maximal_paths
from config import select_rule, get_color


# Control key bindings (formerly config.json "controls"). These now live next to
# the rule functions, ready to be folded into rule bundles in a later refactor.
CONTROL_KEYS = {
    "move_left": "A",
    "move_right": "D",
    "move_up": "W",
    "move_down": "S",
    "rotate_clockwise": "LEFT",
    "rotate_counterclockwise": "RIGHT",
    "place": "SPACE",
    "pause": "ESCAPE",
}


def _get_key(action):
    key_name = CONTROL_KEYS[action]
    return getattr(pyglet.window.key, key_name)

# Note: a cell can hold a multi-letter gram
#   - letters: how many letters the word spells (len of `text`)
#   - cells: how many cells/grams the word spans (len of `path`)
def rule_word_min2letters_min2cells(text, path):
    return len(text) >= 2 and len(path) >= 2

def rule_word_min3letters_min2cells(text, path):
    return len(text) >= 3 and len(path) >= 2

# Minimum-word rule (letters + cells), chosen by the YAML key game_screen.word_length.
_WORD_LENGTH_RULES = {
    "rule_word_min2letters_min2cells": rule_word_min2letters_min2cells,
    "rule_word_min3letters_min2cells": rule_word_min3letters_min2cells,
}


class GameScreen:
    GRID_WIDTH = 14
    PIECE_POOL_SIZE = 100
    # Obstacle pieces dropped onto the board before play begins.
    OBSTACLE_COUNT = 4
    # Obstacle cells render with their own fill (see colors.yaml) so they read
    # as pre-placed hazards distinct from the playable pieces.
    OBSTACLE_CELL_COLOR = get_color("board.obstacle_fill")

    def __init__(self, window, screen_manager):
        self._window = window
        self._screen_manager = screen_manager

        self._keys = {
            "move_left": _get_key("move_left"),
            "move_right": _get_key("move_right"),
            "move_up": _get_key("move_up"),
            "move_down": _get_key("move_down"),
            "rotate_clockwise": _get_key("rotate_clockwise"),
            "rotate_counterclockwise": _get_key("rotate_counterclockwise"),
            "place": _get_key("place"),
            "pause": _get_key("pause"),
        }
        self._menu_open = False
        self._ingame_menu = IngameMenu(window, screen_manager, ScreenType.MAIN_MENU)

        # Tracks currently-held keys, so a movement can use non-standard keys as
        # held modifiers (e.g. up-arrow). 
        self._key_state = pyglet.window.key.KeyStateHandler()
        window.push_handlers(self._key_state)

        # The grid occupies a square region on the left (its side is limited by
        # the window height); the side pane fills the remaining width to its
        # right. Both grid builders size themselves to this square region rather
        # than the full window.
        self._grid_area_size = window.height
        sidepane_x = self._grid_area_size
        sidepane_width = window.width - self._grid_area_size
        self._sidepane = SidePane(
            sidepane_x, 0, sidepane_width, window.height
        )

        # Minimum word to clear (letters + cells); see _WORD_LENGTH_RULES.
        self._word_length_rule = select_rule("game_screen.word_length", _WORD_LENGTH_RULES)

        # Spawn positioning rule, chosen by the YAML key game_screen.spawn.
        spawn_rules = {
            "rule_spawn_center": self._rule_spawn_center,
            "rule_spawn_random_spot": self._rule_spawn_random_spot,
        }
        self._spawn_rule = select_rule("game_screen.spawn", spawn_rules)

        # Spawn orientation rule (independent of position), chosen by the YAML
        # key game_screen.spawn_orientation.
        orient_rules = {
            "rule_orient_default": self._rule_orient_default,
            "rule_orient_random": self._rule_orient_random,
        }
        self._orient_rule = select_rule("game_screen.spawn_orientation", orient_rules)

        repeat_rules = {
            "rule_repeat_allow": self._rule_repeat_allow,
            "rule_repeat_block": self._rule_repeat_block,
        }
        self._repeat_rule = select_rule("game_screen.word_repeat", repeat_rules)

        # Word-selection rule, chosen by the YAML key game_screen.word_select.
        # A clear rule enumerates every candidate word as a cell path; this rule
        # decides which of those candidates actually clear. Splitting selection
        # out is the seam a future player-driven "pick your words" mode plugs
        # into; today only the original auto-select exists.
        select_rules = {
            "rule_select_mostwords_withoverlaps_withrepeats":
                self._rule_select_mostwords_withoverlaps_withrepeats,
        }
        self._select_rule = select_rule("game_screen.word_select", select_rules)

        # Nucleation rule, chosen by the YAML key game_screen.word_nucleation.
        # Of every word found on the board, this decides which count for the move
        # just made -- the gate between pathfinding and selection. Grid-agnostic.
        # rule_nucleate_none qualifies nothing, which disables clearing entirely.
        nucleation_rules = {
            "rule_adjacent_to_placed_piece": self._rule_adjacent_to_placed_piece,
            "rule_nucleate_none": self._rule_nucleate_none,
        }
        self._nucleation_rule = select_rule(
            "game_screen.word_nucleation", nucleation_rules
        )

        self._start_new_game()

    def _start_new_game(self):
        """Begin a fresh game: rebuild the board and piece pools and drop a new
        random set of obstacles. Called once at construction and again every
        time the player (re)enters from the menu via "Start Game".

        Each game gets brand-new batches so every shape from the previous game
        (grid lines, placed pieces, obstacles) is released together for GC,
        rather than piling up invisible behind the new board."""
        self._board_batch = pyglet.graphics.Batch()
        self._piece_batch = pyglet.graphics.Batch()
        # Separate batch for the starting obstacle pieces. Their cells live on
        # the board once dropped, but render through this batch so they stay
        # visually grouped and independently styleable.
        self._obstacle_batch = pyglet.graphics.Batch()

        # Grid bundle, chosen by the YAML key game_screen.grid. The chosen
        # builder also wires up its own movement + clear rules and sizes the
        # pieces, so it must run before the pools are built.
        grid_rules = {
            "rule_use_square_grid": self._rule_use_square_grid,
            "rule_use_hex_grid": self._rule_use_hex_grid,
        }
        self._board = select_rule("game_screen.grid", grid_rules)(self._window)

        # Every word cleared this game, so the repeat rule can prevent a word
        # from being cleared twice. Fresh per game, alongside the cleared-word
        # list shown in the side pane.
        self._cleared_word_history = set()
        self._sidepane.reset()

        # Starting obstacles: a small pool of pieces dropped straight onto the
        # board before the player can move anything. They use their own piece
        # set + gram-pick rules (square_obstacle.* / hex_obstacle.*) and their
        # own batch. Rebuilt every game, so each game gets a new random set.
        self._obstacle_pool = PiecePool(
            self.OBSTACLE_COUNT, self._cell_size, self._obstacle_batch,
            self._piece_class, self._obstacle_piece_types,
            gram_pick_rule=self._obstacle_gram_pick_rule,
            cell_color=self.OBSTACLE_CELL_COLOR
        )
        self._place_obstacles()

        self._piece_pool = PiecePool(
            self.PIECE_POOL_SIZE, self._cell_size, self._piece_batch,
            self._piece_class, self._piece_types
        )
        self._init_first_piece()

    def _place_obstacles(self):
        """Drop every obstacle piece onto the board before play begins. Each is
        oriented by the active orientation rule and scattered to a random,
        on-board, non-overlapping spot so the obstacles don't stack. Clearing is
        intentionally skipped here (we never call _apply_clear_rule), so the
        player doesn't start the game with words already cleared for free."""
        occupied = set()
        while True:
            piece = self._obstacle_pool.current_piece()
            self._orient_rule(piece)
            self._position_obstacle(piece, occupied)
            piece.place()
            for gx, gy, cell, label in piece.get_cell_data():
                self._board.place(gx, gy, cell, label)
                occupied.add((gx, gy))
            piece.set_visible(True)
            if self._obstacle_pool.advance() is None:
                break

    def _position_obstacle(self, piece, occupied):
        """Pick a random spot whose cells are all on-board and clear of other
        obstacles. Retries a bounded number of times, then keeps the last spot
        rather than looping forever on a crowded board."""
        for _ in range(100):
            self._rule_spawn_random_spot(piece)
            cells = piece.get_cell_positions()
            on_board = all(self._board.get_cell(x, y) is not None for (x, y) in cells)
            free = all((x, y) not in occupied for (x, y) in cells)
            if on_board and free:
                return

    def _rule_use_square_grid(self, window):
        """Build a square board and set piece sizing/type to match. Sized to the
        square grid region so columns and rows come out equal."""
        self._cell_size = math.floor(self._grid_area_size / self.GRID_WIDTH)
        self._board_height = math.floor(self._grid_area_size / self._cell_size)
        self._piece_class = SquarePiece
        self._piece_types = PIECE_TYPES
        # Obstacles get their own piece set + gram-pick (square_obstacle.* keys),
        # so they can differ from the playable pieces.
        self._obstacle_piece_types = SQUARE_OBSTACLE_PIECE_TYPES
        self._obstacle_gram_pick_rule = SQUARE_OBSTACLE_GRAM_PICK_RULE
        self._movement_rule = self._rule_square_movement
        grid_px_width = self.GRID_WIDTH * self._cell_size
        grid_px_height = self._board_height * self._cell_size
        board = SquareGrid(
            self.GRID_WIDTH, self._board_height, self._cell_size,
            grid_px_width, grid_px_height, self._board_batch
        )
        return board

    def _rule_use_hex_grid(self, window):
        """Build a flat-top hex board and set piece sizing to match.
        """
        cell_size = math.floor(self._grid_area_size / self.GRID_WIDTH)
        hex_size = cell_size / math.sqrt(3)
        board = HexGrid(
            hex_size, self._grid_area_size, self._grid_area_size,
            self._board_batch
        )
        # Keep the float hex_size: the piece must use the exact same value as
        # the grid, or it drifts off the cells across the board.
        self._cell_size = hex_size
        self._board_height = board.height
        self._piece_class = HexPiece
        self._piece_types = HEX_PIECE_TYPES
        # Obstacles get their own gram-pick (hex_obstacle.gram_pick); the hex set
        # has a single piece type, so obstacle types match the main set.
        self._obstacle_piece_types = HEX_OBSTACLE_PIECE_TYPES
        self._obstacle_gram_pick_rule = HEX_OBSTACLE_GRAM_PICK_RULE

        self._movement_rule = self._rule_hex_movement_holdshift
        # self._movement_rule = self._rule_hex_movement_arrows
        return board

    def _init_first_piece(self):
        piece = self._piece_pool.current_piece()
        self._spawn_piece(piece)
        piece.set_visible(True)
    
    def _spawn_piece(self, piece):
        """Apply the current spawn orientation, then positioning rule."""
        self._orient_rule(piece)
        self._spawn_rule(piece)

    def _rule_orient_default(self, piece):
        """Spawn in the piece's default orientation (rotation state 0)."""
        pass

    def _rule_orient_random(self, piece):
        """Spawn in a random rotation: turn clockwise a random number of times."""
        turns = random.randrange(piece.rotation_count)
        for _ in range(turns):
            piece.rotate_cw()

    def _rule_spawn_center(self, piece):
        """Position a piece at the grid's center cell. The grid computes it from
        its own dimensions, so this adapts to any grid size."""
        center_x, center_y = self._board.center_cell()
        piece.set_position(center_x, center_y)
    
    def _rule_spawn_random_spot(self, piece):
        """Position a piece at a random spot on the grid."""
        x = random.randint(0, self.GRID_WIDTH - 1)
        y = random.randint(0, self._board_height - 1)
        piece.set_position(x, y)
    
    def _rule_square_movement(self, symbol, modifiers):
        """Square grid: A/D/W/S nudge the piece by one cell. Returns handled."""
        handled = True
        if symbol == self._keys["move_left"]:
            self._move_piece(-1, 0)
        elif symbol == self._keys["move_right"]:
            self._move_piece(1, 0)
        elif symbol == self._keys["move_up"]:
            self._move_piece(0, 1)
        elif symbol == self._keys["move_down"]:
            self._move_piece(0, -1)
        else:
            handled = False
        return handled

    def _rule_hex_movement_holdshift(self, symbol, modifiers):
        """Flat-top hex: A=up-left, Shift+A=down-left, D=up-right,
        Shift+D=down-right, W=up, S=down. Returns handled."""
        shift = (modifiers & pyglet.window.key.MOD_SHIFT) != 0
        handled = True
        if symbol == self._keys["move_left"]:
            self._move_piece_hexdir(HEX_DOWN_LEFT if shift else HEX_UP_LEFT)
        elif symbol == self._keys["move_right"]:
            self._move_piece_hexdir(HEX_DOWN_RIGHT if shift else HEX_UP_RIGHT)
        elif symbol == self._keys["move_up"]:
            self._move_piece_hexdir(HEX_UP)
        elif symbol == self._keys["move_down"]:
            self._move_piece_hexdir(HEX_DOWN)
        else:
            handled = False
        return handled

    def _rule_hex_movement_arrows(self, symbol, modifiers):
        """Flat-top hex, arrow-key chords: up+A=up-left, down+A=down-left,
        up+D=up-right, down+D=down-right, W=up, S=down. A/D alone do nothing.
        Returns handled."""
        up = self._key_state[pyglet.window.key.UP]
        down = self._key_state[pyglet.window.key.DOWN]
        handled = True
        if symbol == self._keys["move_left"]:
            if up:
                self._move_piece_hexdir(HEX_UP_LEFT)
            elif down:
                self._move_piece_hexdir(HEX_DOWN_LEFT)
            else:
                handled = False
        elif symbol == self._keys["move_right"]:
            if up:
                self._move_piece_hexdir(HEX_UP_RIGHT)
            elif down:
                self._move_piece_hexdir(HEX_DOWN_RIGHT)
            else:
                handled = False
        elif symbol == self._keys["move_up"]:
            self._move_piece_hexdir(HEX_UP)
        elif symbol == self._keys["move_down"]:
            self._move_piece_hexdir(HEX_DOWN)
        else:
            handled = False
        return handled

    def _move_piece_hexdir(self, direction):
        """Move the piece to its hex neighbor in the given direction index."""
        piece = self._current_piece()
        nx, ny = hex_neighbor(piece.grid_x, piece.grid_y, direction)
        self._move_piece(nx - piece.grid_x, ny - piece.grid_y)

    def _rule_repeat_allow(self, word):
        """Allow a word to clear even if it cleared before (original behavior)."""
        return True

    def _rule_repeat_block(self, word):
        """Block a word that has already been cleared earlier this game."""
        return word not in self._cleared_word_history

    def _apply_clear_rule(self, placed_positions):
        """Run the word-clearing pipeline for the piece just placed and return
        the words cleared (for the side pane). Four stages, each its own seam:

          1. pathfind  -- find every dictionary word on the board (_find_words)
          2. nucleate  -- keep the words that count for this move
                          (self._nucleation_rule, game_screen.word_nucleation)
          3. select    -- pick which of those to clear
                          (self._select_rule, game_screen.word_select)
          4. clear     -- read each word, gate on the repeat rule, remove cells

        Stages 2 and 3 are the swappable seams a future player-driven word pick
        plugs into; stage 1's geometry is configured per board (hex_grid.word_
        pathfinding), and stage 4 is mechanical."""
        found = self._find_words()
        candidates = self._nucleation_rule(found, placed_positions)
        to_clear = set()
        cleared_words = []
        for path in self._select_rule(candidates):
            # Read the spelled word before clearing the cells it sits on.
            word = "".join(self._board.letter_at(x, y) for (x, y) in path)
            if self._repeat_rule(word):
                cleared_words.append(word)
                to_clear.update(path)
        for (x, y) in to_clear:
            self._board.clear_cell(x, y)
        for word in cleared_words:
            self._cleared_word_history.add(word)
        return cleared_words

    def _find_words(self):
        """Stage 1 (pathfind): every dictionary word spellable on the board, as
        a list of cell paths. Walks from each occupied cell via _collect_words;
        the step geometry comes from the board's forward_neighbors (square: four
        cardinals, hardcoded; hex: shaped by hex_grid.word_pathfinding), so this
        is grid-agnostic."""
        found = []  # each entry: list of (x, y) cells spelling a dictionary word
        for start in self._board.occupied_cells():
            self._collect_words(start, None, [], "", found)
        return found

    def _collect_words(self, cell, prev_direction, path, text, found):
        """Pathfinding walk: step forward from `cell` (snaking via the board's
        forward_neighbors), collecting every dictionary word reachable. Grid-
        agnostic -- each board supplies its own snake geometry. `prev_direction`
        is the step taken to reach `cell` (None at the start), which a board's
        pathfinding rule may use to veto sharp twists (the square grid ignores
        it). Prunes as soon as the letters so far begin no word."""
        letter = self._board.letter_at(*cell)
        if letter is None:
            return
        text = text + letter
        if not is_prefix(text):
            return
        path = path + [cell]
        if is_word(text) and self._word_length_rule(text, path):
            found.append(path)
        for nxt, direction in self._board.forward_neighbors(*cell, prev_direction):
            # Never step backwards onto a cell already in this word's path. The
            # right/down rules can't revisit (their directions are monotonic), so
            # this guard only bites for rules that allow turning back, like
            # rule_snake_anydirection; it also keeps that walk from looping.
            if nxt not in path:
                self._collect_words(nxt, direction, path, text, found)

    # --- Nucleation rules (game_screen.word_nucleation) --------------------
    # Stage 2: of every word _find_words turned up, decide which count for the
    # move just made. The gate between pathfinding and selection.
    def _rule_adjacent_to_placed_piece(self, found, placed_positions):
        """Keep words that bridge the just-placed piece and the existing board:
        a word must cover at least one placed cell and at least one pre-existing
        cell. This is what makes a word 'nucleate' around the new piece rather
        than clearing words made purely of old letters or purely of the piece's
        own cells."""
        new_cells = set(placed_positions)
        candidates = []
        for path in found:
            has_placed = any(cell in new_cells for cell in path)
            has_old = any(cell not in new_cells for cell in path)
            if has_placed and has_old:
                candidates.append(path)
        return candidates

    def _rule_nucleate_none(self, found, placed_positions):
        """No word ever qualifies, which disables clearing entirely."""
        return []

    # --- Word-selection rules (game_screen.word_select) --------------------
    # Stage 3: of the nucleated candidates, pick which to actually clear.
    def _rule_select_mostwords_withoverlaps_withrepeats(self, candidates):
        """Auto-select: keep every candidate path that isn't a contiguous
        sub-path of a longer one. Overlapping words (FIN/INK sharing IN) and
        repeats of one word at different board locations both survive; only
        strict sub-words are dropped (CAT inside CATEGORY). This reproduces the
        original instant-clear behavior, now a swappable selection step."""
        return select_maximal_paths(candidates)

    def _current_piece(self):
        return self._piece_pool.current_piece()
    
    def _update_hover_visibility(self):
        piece = self._current_piece()
        if piece.placed:
            return
        positions = piece.get_cell_positions()
        self._board.hide_cells_for_hover(positions)
    
    def _clear_hover_visibility(self):
        piece = self._current_piece()
        positions = piece.get_cell_positions()
        self._board.restore_cells_from_hover(positions)
    
    def _move_piece(self, dx, dy):
        self._clear_hover_visibility()
        self._current_piece().move(dx, dy)
        self._update_hover_visibility()
    
    def _rotate_piece_cw(self):
        self._clear_hover_visibility()
        self._current_piece().rotate_cw()
        self._update_hover_visibility()
    
    def _rotate_piece_ccw(self):
        self._clear_hover_visibility()
        self._current_piece().rotate_ccw()
        self._update_hover_visibility()
    
    def _place_current_piece(self):
        self._clear_hover_visibility()
        piece = self._current_piece()
        piece.place()

        placed_positions = []
        for gx, gy, cell, label in piece.get_cell_data():
            self._board.place(gx, gy, cell, label)
            placed_positions.append((gx, gy))

        cleared_words = self._apply_clear_rule(placed_positions)
        if cleared_words:
            self._sidepane.add_cleared_words(cleared_words)

        next_piece = self._piece_pool.advance()
        if next_piece:
            self._spawn_piece(next_piece)
            next_piece.set_visible(True)
            self._update_hover_visibility()
    
    def on_enter(self):
        self._menu_open = False
        self._ingame_menu.reset()
        # Entering from the menu ("Start Game") begins a fresh game, which lays
        # down a new random obstacle set.
        self._start_new_game()
    
    def on_exit(self):
        pass
    
    def draw(self):
        # glClearColor wants 0-1 floats, but colors.yaml stores 0-255 channels,
        # so normalize. Clear to the board background, then restore the default
        # window background for the menu/title screens that just call clear().
        bg = get_color("board.background")
        win_bg = get_color("window.background")
        pyglet.gl.glClearColor(bg[0] / 255, bg[1] / 255, bg[2] / 255, 1)
        self._window.clear()
        pyglet.gl.glClearColor(win_bg[0] / 255, win_bg[1] / 255, win_bg[2] / 255, 1)
        
        self._board_batch.draw()
        self._obstacle_batch.draw()
        self._piece_batch.draw()
        self._sidepane.draw()

        if self._menu_open:
            self._ingame_menu.draw()
    
    def update(self, dt):
        pass
    
    def _handle_menu_action(self, action):
        if action == "resume":
            self._menu_open = False
        elif action == "main_menu":
            self._screen_manager.switch_to(ScreenType.MAIN_MENU)
        elif action == "exit":
            self._window.close()
    
    def on_key_press(self, symbol, modifiers):
        if self._menu_open:
            action = self._ingame_menu.on_key_press(symbol, modifiers)
            if action:
                self._handle_menu_action(action)
            return True
        
        if symbol == self._keys["pause"]:
            self._menu_open = True
            self._ingame_menu.reset()
            return True
        
        if self._current_piece().placed:
            return False

        if self._movement_rule(symbol, modifiers):
            return True

        if symbol == self._keys["rotate_clockwise"]:
            self._rotate_piece_cw()
            return True
        elif symbol == self._keys["rotate_counterclockwise"]:
            self._rotate_piece_ccw()
            return True
        elif symbol == self._keys["place"]:
            self._place_current_piece()
            return True
        
        return False
    
    def on_mouse_press(self, x, y, button, modifiers):
        if self._menu_open:
            action = self._ingame_menu.on_mouse_press(x, y, button, modifiers)
            if action:
                self._handle_menu_action(action)
    
    def on_mouse_motion(self, x, y, dx, dy):
        if self._menu_open:
            self._ingame_menu.on_mouse_motion(x, y, dx, dy)
