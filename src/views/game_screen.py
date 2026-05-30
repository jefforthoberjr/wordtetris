import math
import random
import pyglet
from views.ingame_menu import IngameMenu
from controllers.screen_manager import ScreenType
from models.piece_pool import PiecePool
from models.grid import Grid
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
        
        self._cell_size = math.floor(window.width / self.GRID_WIDTH)
        self._board_height = math.floor(window.height / self._cell_size)
        
        self._board_batch = pyglet.graphics.Batch()
        self._piece_batch = pyglet.graphics.Batch()
        
        self._board = Grid(
            self.GRID_WIDTH, self._board_height, self._cell_size,
            window.width, window.height, self._board_batch
        )
        
        self._piece_pool = PiecePool(self.PIECE_POOL_SIZE, self._cell_size, self._piece_batch)
        self._init_first_piece()
    
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
        
        for gx, gy, cell, label in piece.get_cell_data():
            self._board.place(gx, gy, cell, label)
        
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
        
        if symbol == self._keys["move_left"]:
            self._move_piece(-1, 0)
            return True
        elif symbol == self._keys["move_right"]:
            self._move_piece(1, 0)
            return True
        elif symbol == self._keys["move_up"]:
            self._move_piece(0, 1)
            return True
        elif symbol == self._keys["move_down"]:
            self._move_piece(0, -1)
            return True
        elif symbol == self._keys["rotate_clockwise"]:
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
