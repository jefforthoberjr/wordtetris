import random
import pyglet
from views.ingame_menu import IngameMenu
from controllers.screen_manager import ScreenType
from models.block import Block
from models.tetrimino import TetriminoType, TETRIMINO_SHAPES
from config import CONFIG


def _get_key(action):
    key_name = CONFIG["controls"][action]
    return getattr(pyglet.window.key, key_name)


class GameScreen:
    GRID_WIDTH = 20
    BLOCK_POOL_SIZE = 100
    
    def __init__(self, window, screen_manager):
        self._window = window
        self._screen_manager = screen_manager
        
        self._keys = {
            "move_left": _get_key("move_left"),
            "move_right": _get_key("move_right"),
            "move_up": _get_key("move_up"),
            "move_down": _get_key("move_down"),
            "rotate": _get_key("rotate"),
            "pause": _get_key("pause"),
        }
        self._menu_open = False
        self._ingame_menu = IngameMenu(window, screen_manager, ScreenType.MAIN_MENU)
        
        self._cell_size = window.width // self.GRID_WIDTH
        self._grid_height = window.height // self._cell_size
        
        self._grid_batch = pyglet.graphics.Batch()
        self._block_batch = pyglet.graphics.Batch()
        
        self._grid_lines = []
        self._create_grid()
        
        self._block_pool = []
        self._current_block_index = 0
        self._create_block_pool()
    
    def _create_grid(self):
        line_color = (200, 200, 200)
        
        for x in range(self.GRID_WIDTH + 1):
            px = x * self._cell_size
            line = pyglet.shapes.Line(
                px, 0, px, self._window.height,
                thickness=1, color=line_color, batch=self._grid_batch
            )
            self._grid_lines.append(line)
        
        for y in range(self._grid_height + 1):
            py = y * self._cell_size
            line = pyglet.shapes.Line(
                0, py, self._window.width, py,
                thickness=1, color=line_color, batch=self._grid_batch
            )
            self._grid_lines.append(line)
    
    def _create_block_pool(self):
        tetrimino_types = list(TetriminoType)
        
        for _ in range(self.BLOCK_POOL_SIZE):
            t_type = random.choice(tetrimino_types)
            shapes_data = TETRIMINO_SHAPES[t_type]
            block = Block(t_type, shapes_data, self._cell_size, self._block_batch, visible=True)
            self._block_pool.append(block)
        
        center_x = self.GRID_WIDTH // 2 - 1
        center_y = self._grid_height // 2
        self._block_pool[0].set_position(center_x, center_y)
        self._block_pool[0].set_visible(True)
        
        for i in range(1, self.BLOCK_POOL_SIZE):
            self._block_pool[i].set_visible(False)
    
    def _current_block(self):
        return self._block_pool[self._current_block_index]
    
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
        self._block_batch.draw()
        
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
        elif symbol == self._keys["move_left"]:
            self._current_block().move(-1, 0)
            return True
        elif symbol == self._keys["move_right"]:
            self._current_block().move(1, 0)
            return True
        elif symbol == self._keys["move_up"]:
            self._current_block().move(0, 1)
            return True
        elif symbol == self._keys["move_down"]:
            self._current_block().move(0, -1)
            return True
        elif symbol == self._keys["rotate"]:
            self._current_block().rotate_cw()
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
