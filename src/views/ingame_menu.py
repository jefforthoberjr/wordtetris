import math
import pyglet


class IngameMenu:
    def __init__(self, window, screen_manager, main_menu_screen_type):
        self._window = window
        self._screen_manager = screen_manager
        self._main_menu_screen_type = main_menu_screen_type
        self._batch = pyglet.graphics.Batch()
        
        self._menu_items = ["Main Menu", "Exit"]
        self._selected_index = 0
        self._labels = []
        self._highlight_color = (255, 255, 0, 255)
        self._normal_color = (255, 255, 255, 255)
        
        panel_width = 300
        panel_height = 200
        panel_x = math.floor((window.width - panel_width) / 2)
        panel_y = math.floor((window.height - panel_height) / 2)
        
        self._background = pyglet.shapes.Rectangle(
            panel_x, panel_y, panel_width, panel_height,
            color=(50, 50, 50),
            batch=self._batch
        )
        self._background.opacity = 220
        
        start_y = math.floor(window.height / 2) + 30
        spacing = 60
        
        for i, item_text in enumerate(self._menu_items):
            label = pyglet.text.Label(
                item_text,
                font_size=28,
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
            return "main_menu"
        elif self._selected_index == 1:
            return "exit"
        return None
    
    def _get_item_at(self, x, y):
        for i, label in enumerate(self._labels):
            half_width = math.floor(label.content_width / 2)
            half_height = math.floor(label.content_height / 2)
            if (label.x - half_width <= x <= label.x + half_width and
                label.y - half_height <= y <= label.y + half_height):
                return i
        return None
    
    def reset(self):
        self._selected_index = 0
        self._update_highlight()
    
    def draw(self):
        self._batch.draw()
    
    def on_key_press(self, symbol, modifiers):
        if symbol == pyglet.window.key.UP:
            self._selected_index = (self._selected_index - 1) % len(self._menu_items)
            self._update_highlight()
            return None
        elif symbol == pyglet.window.key.DOWN:
            self._selected_index = (self._selected_index + 1) % len(self._menu_items)
            self._update_highlight()
            return None
        elif symbol == pyglet.window.key.ENTER or symbol == pyglet.window.key.RETURN:
            return self._select_current()
        elif symbol == pyglet.window.key.ESCAPE:
            return "resume"
        return None
    
    def on_mouse_press(self, x, y, button, modifiers):
        item_index = self._get_item_at(x, y)
        if item_index is not None:
            self._selected_index = item_index
            self._update_highlight()
            return self._select_current()
        return None
    
    def on_mouse_motion(self, x, y, dx, dy):
        item_index = self._get_item_at(x, y)
        if item_index is not None:
            self._selected_index = item_index
            self._update_highlight()
