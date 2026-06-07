from enum import Enum

class ScreenType(Enum):
    TITLE = 1
    MAIN_MENU = 2
    GAME = 3


class ScreenManager:
    def __init__(self):
        self._current_screen = None
        self._screens = {}
    
    def register(self, screen_type, screen):
        self._screens[screen_type] = screen
    
    def switch_to(self, screen_type):
        if self._current_screen:
            self._current_screen.on_exit()
        self._current_screen = self._screens[screen_type]
        self._current_screen.on_enter()
    
    def draw(self):
        if self._current_screen:
            self._current_screen.draw()
    
    def update(self, dt):
        if self._current_screen:
            self._current_screen.update(dt)
    
    def on_key_press(self, symbol, modifiers):
        if self._current_screen:
            return self._current_screen.on_key_press(symbol, modifiers)
        return False

    def on_text(self, text):
        # Only screens that accept typed input (e.g. the game screen's word
        # entry) define on_text; others simply ignore keystrokes.
        if self._current_screen and hasattr(self._current_screen, "on_text"):
            self._current_screen.on_text(text)

    def on_mouse_press(self, x, y, button, modifiers):
        if self._current_screen:
            self._current_screen.on_mouse_press(x, y, button, modifiers)
    
    def on_mouse_motion(self, x, y, dx, dy):
        if self._current_screen:
            self._current_screen.on_mouse_motion(x, y, dx, dy)
