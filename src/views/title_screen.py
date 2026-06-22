import math
import pyglet
from config import get_string
from controls import control_keys


class TitleScreen:
    def __init__(self, window, screen_manager, next_screen_type):
        self._window = window
        self._screen_manager = screen_manager
        self._next_screen_type = next_screen_type
        self._batch = pyglet.graphics.Batch()
        
        self._title_label = pyglet.text.Label(
            get_string("title"),
            font_size=48,
            x=math.floor(window.width / 2),
            y=math.floor(window.height / 2) + 50,
            anchor_x="center",
            anchor_y="center",
            batch=self._batch
        )
        
        self._prompt_label = pyglet.text.Label(
            get_string("title_continue"),
            font_size=20,
            x=math.floor(window.width / 2),
            y=math.floor(window.height / 2) - 50,
            anchor_x="center",
            anchor_y="center",
            batch=self._batch
        )
    
    def on_enter(self):
        pass
    
    def on_exit(self):
        pass
    
    def draw(self):
        self._window.clear()
        self._batch.draw()
    
    def update(self, dt):
        pass
    
    def on_key_press(self, symbol, modifiers):
        # The title advances on ANY key except the global debug toggle, which is
        # let through (return False) so main.py can handle it.
        if symbol in control_keys("global.debug_panel_toggle"):
            return False
        self._screen_manager.switch_to(self._next_screen_type)
        return True
    
    def on_mouse_press(self, x, y, button, modifiers):
        self._screen_manager.switch_to(self._next_screen_type)
    
    def on_mouse_motion(self, x, y, dx, dy):
        pass
