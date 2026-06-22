import math
import pyglet
from config import get_color, get_string
from controls import control_keys


class MainMenuScreen:
    def __init__(self, window, screen_manager, game_screen_type,
                 dictionary_screen_type):
        self._window = window
        self._screen_manager = screen_manager
        self._game_screen_type = game_screen_type
        self._dictionary_screen_type = dictionary_screen_type
        self._batch = pyglet.graphics.Batch()

        self._menu_items = [
            get_string("menu_start"),
            get_string("menu_dictionary"),
            get_string("menu_exit"),
        ]
        self._selected_index = 0
        self._labels = []
        self._highlight_color = get_color("menu.highlight")
        self._normal_color = get_color("menu.normal")
        
        start_y = math.floor(window.height / 2) + 30
        spacing = 60
        
        for i, item_text in enumerate(self._menu_items):
            label = pyglet.text.Label(
                item_text,
                font_size=32,
                x=math.floor(window.width / 2),
                y=start_y - i * spacing,
                anchor_x="center",
                anchor_y="center",
                batch=self._batch
            )
            self._labels.append(label)
        
        self._update_highlight()
    
    def _update_highlight(self):
        for i, label in enumerate(self._labels):
            if i == self._selected_index:
                label.color = self._highlight_color
            else:
                label.color = self._normal_color
    
    def _select_current(self):
        if self._selected_index == 0:
            self._screen_manager.switch_to(self._game_screen_type)
        elif self._selected_index == 1:
            self._screen_manager.switch_to(self._dictionary_screen_type)
        elif self._selected_index == 2:
            self._window.close()
    
    def _get_item_at(self, x, y):
        for i, label in enumerate(self._labels):
            half_width = math.floor(label.content_width / 2)
            half_height = math.floor(label.content_height / 2)
            if (label.x - half_width <= x <= label.x + half_width and
                label.y - half_height <= y <= label.y + half_height):
                return i
        return None
    
    def on_enter(self):
        self._selected_index = 0
        self._update_highlight()
    
    def on_exit(self):
        pass
    
    def draw(self):
        self._window.clear()
        self._batch.draw()
    
    def update(self, dt):
        pass
    
    def on_key_press(self, symbol, modifiers):
        if symbol in control_keys("main_menu.nav_up"):
            self._selected_index = (self._selected_index - 1) % len(self._menu_items)
            self._update_highlight()
            return True
        elif symbol in control_keys("main_menu.nav_down"):
            self._selected_index = (self._selected_index + 1) % len(self._menu_items)
            self._update_highlight()
            return True
        elif symbol in control_keys("main_menu.select"):
            self._select_current()
            return True
        return False
    
    def on_mouse_press(self, x, y, button, modifiers):
        item_index = self._get_item_at(x, y)
        if item_index is not None:
            self._selected_index = item_index
            self._update_highlight()
            self._select_current()
    
    def on_mouse_motion(self, x, y, dx, dy):
        item_index = self._get_item_at(x, y)
        if item_index is not None:
            self._selected_index = item_index
            self._update_highlight()
