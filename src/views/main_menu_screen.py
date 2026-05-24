import pyglet


class MainMenuScreen:
    def __init__(self, window, screen_manager, game_screen_type):
        self._window = window
        self._screen_manager = screen_manager
        self._game_screen_type = game_screen_type
        self._batch = pyglet.graphics.Batch()
        
        self._menu_items = ["Start Game", "Exit"]
        self._selected_index = 0
        self._labels = []
        self._highlight_color = (255, 255, 0, 255)
        self._normal_color = (255, 255, 255, 255)
        
        start_y = window.height // 2 + 30
        spacing = 60
        
        for i, item_text in enumerate(self._menu_items):
            label = pyglet.text.Label(
                item_text,
                font_size=32,
                x=window.width // 2,
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
            self._window.close()
    
    def _get_item_at(self, x, y):
        for i, label in enumerate(self._labels):
            half_width = label.content_width // 2
            half_height = label.content_height // 2
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
        if symbol == pyglet.window.key.UP:
            self._selected_index = (self._selected_index - 1) % len(self._menu_items)
            self._update_highlight()
            return True
        elif symbol == pyglet.window.key.DOWN:
            self._selected_index = (self._selected_index + 1) % len(self._menu_items)
            self._update_highlight()
            return True
        elif symbol == pyglet.window.key.ENTER or symbol == pyglet.window.key.RETURN:
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
