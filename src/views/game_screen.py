import math
import pyglet
from views.ingame_menu import IngameMenu
from views.shaders import get_shape_shader
from controllers.screen_manager import ScreenType
from models.piece import Piece
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
        self._grid_height = math.floor(window.height / self._cell_size)
        
        self._grid_batch = pyglet.graphics.Batch()
        self._piece_batch = pyglet.graphics.Batch()
        
        self._grid_lines = []
        self._create_grid()
        
        self._placement_grid = Grid(self.GRID_WIDTH, self._grid_height)
        
        self._piece_pool = []
        self._current_piece_index = 0
        self._create_piece_pool()
    
    def _create_grid(self):
        line_color = (200, 200, 200)
        shape_shader = get_shape_shader()
        
        for x in range(self.GRID_WIDTH + 1):
            px = x * self._cell_size
            line = pyglet.shapes.Line(
                px, 0, px, self._window.height,
                thickness=1, color=line_color, batch=self._grid_batch,
                program=shape_shader
            )
            self._grid_lines.append(line)
        
        for y in range(self._grid_height + 1):
            py = y * self._cell_size
            line = pyglet.shapes.Line(
                0, py, self._window.width, py,
                thickness=1, color=line_color, batch=self._grid_batch,
                program=shape_shader
            )
            self._grid_lines.append(line)
    
    def _create_piece_pool(self):
        for _ in range(self.PIECE_POOL_SIZE):
            piece = Piece.create(self._cell_size, self._piece_batch, visible=True)
            self._piece_pool.append(piece)
        
        center_x = math.floor(self.GRID_WIDTH / 2) - 1
        center_y = math.floor(self._grid_height / 2)
        self._piece_pool[0].set_position(center_x, center_y)
        self._piece_pool[0].set_visible(True)
        
        for i in range(1, self.PIECE_POOL_SIZE):
            self._piece_pool[i].set_visible(False)
    
    def _current_piece(self):
        return self._piece_pool[self._current_piece_index]
    
    def _update_hover_visibility(self):
        piece = self._current_piece()
        if piece.placed:
            return
        positions = piece.get_cell_positions()
        self._placement_grid.hide_cells_for_hover(positions)
    
    def _clear_hover_visibility(self):
        piece = self._current_piece()
        positions = piece.get_cell_positions()
        self._placement_grid.restore_cells_from_hover(positions)
    
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
        
        for gx, gy, square, label in piece.get_cell_data():
            self._placement_grid.place(gx, gy, square, label)
        
        self._current_piece_index += 1
        if self._current_piece_index < self.PIECE_POOL_SIZE:
            next_piece = self._current_piece()
            center_x = math.floor(self.GRID_WIDTH / 2) - 1
            center_y = math.floor(self._grid_height / 2)
            next_piece.set_position(center_x, center_y)
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
        
        self._grid_batch.draw()
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
