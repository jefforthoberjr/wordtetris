import math
import random
import pyglet
from views.ingame_menu import IngameMenu
from controllers.screen_manager import ScreenType
from models.piece_pool import PiecePool
from models.piece import Piece, PIECE_TYPES
from models.hex_piece import HexPiece, PIECE_TYPES as HEX_PIECE_TYPES
from models.hex_domino import hex_neighbor
from models.hex_domino import HEX_UP, HEX_DOWN
from models.hex_domino import HEX_UP_LEFT, HEX_DOWN_LEFT
from models.hex_domino import HEX_UP_RIGHT, HEX_DOWN_RIGHT
from models.grid import Grid
from models.hex_grid import HexGrid
from models.word_dictionary import longest_word_span
from models.word_dictionary import is_word, is_prefix, select_maximal_paths
from config import CONFIG


def _get_key(action):
    key_name = CONFIG["controls"][action]
    return getattr(pyglet.window.key, key_name)


# Minimum word rules for the clear logic. A word only clears if it passes the
# active rule, which checks two separate things:
#   - letters: how many letters the word spells (len of `text`)
#   - cells: how many cells/grams the word spans (len of `path`)
# These differ because a cell can hold a multi-letter gram, so a whole short
# word could sit in one cell; the cell minimum forces a word to actually link
# cells together. Swap which one is active on the line in __init__.
def rule_word_min2letters_min2cells(text, path):
    return len(text) >= 2 and len(path) >= 2

def rule_word_min3letters_min2cells(text, path):
    return len(text) >= 3 and len(path) >= 2


class GameScreen:
    GRID_WIDTH = 20
    PIECE_POOL_SIZE = 100

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

        self._board_batch = pyglet.graphics.Batch()
        self._piece_batch = pyglet.graphics.Batch()

        # self._board = self._rule_use_square_grid(window)
        self._board = self._rule_use_hex_grid(window)

        # Minimum word to clear (letters + cells). Comment in the one you want.
        # self._word_length_rule = rule_word_min2letters_min2cells
        self._word_length_rule = rule_word_min3letters_min2cells

        self._piece_pool = PiecePool(
            self.PIECE_POOL_SIZE, self._cell_size, self._piece_batch,
            self._piece_class, self._piece_types
        )
        self._init_first_piece()

    def _rule_use_square_grid(self, window):
        """Build a square board and set piece sizing/type to match."""
        self._cell_size = math.floor(window.width / self.GRID_WIDTH)
        self._board_height = math.floor(window.height / self._cell_size)
        self._piece_class = Piece
        self._piece_types = PIECE_TYPES
        self._movement_rule = self._rule_square_movement
        board = Grid(
            self.GRID_WIDTH, self._board_height, self._cell_size,
            window.width, window.height, self._board_batch
        )
        return board

    def _rule_use_hex_grid(self, window):
        """Build a flat-top hex board and set piece sizing to match.
        """
        cell_size = math.floor(window.width / self.GRID_WIDTH)
        hex_size = cell_size / math.sqrt(3)
        board = HexGrid(hex_size, window.width, window.height, self._board_batch)
        # Keep the float hex_size: the piece must use the exact same value as
        # the grid, or it drifts off the cells across the board.
        self._cell_size = hex_size
        self._board_height = board.height
        self._piece_class = HexPiece
        self._piece_types = HEX_PIECE_TYPES
        
        self._movement_rule = self._rule_hex_movement_holdshift
        # self._movement_rule = self._rule_hex_movement_arrows
        return board

    def _init_first_piece(self):
        piece = self._piece_pool.current_piece()
        self._spawn_piece(piece)
        piece.set_visible(True)
    
    def _spawn_piece(self, piece):
        """Apply the current spawn positioning rule."""
        # self._rule_spawn_center(piece)
        self._rule_spawn_random_spot(piece)
    
    def _rule_spawn_center(self, piece):
        """Position a piece at the center of the grid."""
        center_x = math.floor(self.GRID_WIDTH / 2) - 1
        center_y = math.floor(self._board_height / 2)
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

    def _apply_clear_rule(self, placed_positions):
        # self._rule_clear_none(placed_positions)
        # self._rule_clear_adjacent_same_letter(placed_positions)
        # self._rule_clear_words(placed_positions)        # square grid
        self._rule_clear_hex_words(placed_positions)      # hex grid

    def _rule_clear_none(self, placed_positions):
        """No clearing (feature disabled)."""
        pass

    def _rule_clear_hex_words(self, placed_positions):
        """Hex board: clear dictionary words formed by snaking paths that step
        only up-right, down-right, or down, so a word still reads left->right
        and top->bottom. A word must cover at least one placed cell and at
        least one pre-existing cell. Every qualifying word that isn't a
        sub-path of a longer one is cleared, so a single cell can drop several
        branching words at once (including overlapping straddles)."""
        new_cells = set(placed_positions)
        found = []  # each entry: list of (x, y) cells spelling a dictionary word
        for start in self._board.occupied_cells():
            self._collect_hex_words(start, None, [], "", found)
        qualifying = []
        for path in found:
            has_placed = any(cell in new_cells for cell in path)
            has_old = any(cell not in new_cells for cell in path)
            if has_placed and has_old:
                qualifying.append(path)
        to_clear = set()
        for path in select_maximal_paths(qualifying):
            to_clear.update(path)
        for (x, y) in to_clear:
            self._board.clear_cell(x, y)
        return to_clear

    def _collect_hex_words(self, cell, prev_direction, path, text, found):
        """Walk snaking forward steps from `cell`, collecting every dictionary
        word reachable. `prev_direction` is the step taken to reach `cell` (None
        at the start), which the snake rule uses to veto sharp twists. Prunes as
        soon as the letters so far begin no word."""
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
            self._collect_hex_words(nxt, direction, path, text, found)

    def _rule_clear_words(self, placed_positions):
        """Clear dictionary words formed when the placed piece links up with
        letters already on the board. For each placed cell, scan its horizontal
        (left->right) and vertical (top->bottom) line and clear the longest
        forward-reading word that covers the cell plus at least one
        pre-existing cell. A cell may clear one word per axis, so an across and
        a down word can both go at once. Square grid only for now."""
        new_cells = set(placed_positions)
        axes = ((1, 0), (0, -1))  # across: left->right; down: top->bottom
        to_clear = set()
        for (px, py) in placed_positions:
            for (dx, dy) in axes:
                line = self._board.line_through(px, py, dx, dy)
                if not line:
                    continue
                text = "".join(self._board.letter_at(x, y) for (x, y) in line)
                is_old = [pos not in new_cells for pos in line]
                anchor = line.index((px, py))
                span = longest_word_span(text, anchor, is_old)
                if span is not None:
                    start, stop = span
                    to_clear.update(line[start:stop])
        for (x, y) in to_clear:
            self._board.clear_cell(x, y)
        return to_clear

    def _rule_clear_adjacent_same_letter(self, placed_positions):
        new_cells = set(placed_positions)
        to_clear = set()
        for (x, y) in placed_positions:
            letter = self._board.letter_at(x, y)
            if letter is not None:
                for (nx, ny) in self._board.neighbors(x, y):
                    is_old_cell = (nx, ny) not in new_cells
                    if is_old_cell and self._board.letter_at(nx, ny) == letter:
                        to_clear.add((x, y))
                        to_clear.add((nx, ny))
        for (x, y) in to_clear:
            self._board.clear_cell(x, y)
        return to_clear

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

        self._apply_clear_rule(placed_positions)

        next_piece = self._piece_pool.advance()
        if next_piece:
            self._spawn_piece(next_piece)
            next_piece.set_visible(True)
            self._update_hover_visibility()
    
    def on_enter(self):
        self._menu_open = False
        self._ingame_menu.reset()
    
    def on_exit(self):
        pass
    
    def draw(self):
        pyglet.gl.glClearColor(1, 1, 1, 1)
        self._window.clear()
        pyglet.gl.glClearColor(0, 0, 0, 1)
        
        self._board_batch.draw()
        self._piece_batch.draw()
        
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
