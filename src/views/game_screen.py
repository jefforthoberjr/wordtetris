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
from config import CONFIG


def _get_key(action):
    key_name = CONFIG["controls"][action]
    return getattr(pyglet.window.key, key_name)


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

        # Tracks currently-held keys, so a movement rule can use non-standard keys as
        # held modifiers (e.g. up-arrow). 
        self._key_state = pyglet.window.key.KeyStateHandler()
        window.push_handlers(self._key_state)

        self._board_batch = pyglet.graphics.Batch()
        self._piece_batch = pyglet.graphics.Batch()

        # self._board = self._rule_use_square_grid(window)
        self._board = self._rule_use_hex_grid(window)

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
        self._rule_clear_adjacent_same_letter(placed_positions)

    def _rule_clear_none(self, placed_positions):
        """No clearing (feature disabled)."""
        pass

    def _rule_clear_adjacent_same_letter(self, placed_positions):
        new_cells = set(placed_positions)
        to_clear = set()
        for (x, y) in placed_positions:
            letter = self._board_letter(x, y)
            if letter is not None:
                for (nx, ny) in self._square_neighbors(x, y):
                    is_old_cell = (nx, ny) not in new_cells
                    if is_old_cell and self._board_letter(nx, ny) == letter:
                        to_clear.add((x, y))
                        to_clear.add((nx, ny))
        for (x, y) in to_clear:
            self._board.clear_cell(x, y)
        return to_clear

    def _square_neighbors(self, x, y):
        neighbors = []
        neighbors.append((x - 1, y))
        neighbors.append((x + 1, y))
        neighbors.append((x, y - 1))
        neighbors.append((x, y + 1))
        return neighbors

    def _board_letter(self, x, y):
        """Letter stored in a board cell, or None if empty / off-board."""
        cell = self._board.get_cell(x, y)
        letter = None
        if cell is not None and cell.is_occupied():
            if cell.label is not None:
                letter = cell.label.text
        return letter

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
