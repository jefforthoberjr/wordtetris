import ram_overhead
ram_overhead.measure("after_psutil")

import pyglet
ram_overhead.measure("after_pyglet")

from config import CONFIG
from controls import control_keys
import debug_panel
import log_codes as L
from controllers.screen_manager import ScreenManager, ScreenType
from views.title_screen import TitleScreen
from views.main_menu_screen import MainMenuScreen
from views.game_screen import GameScreen
from views.dictionary_screen import DictionaryScreen

window = pyglet.window.Window(
    width=CONFIG["window"]["width"],
    height=CONFIG["window"]["height"],
    caption=CONFIG["window"]["title"]
)

ram_overhead.measure("after_window")

screen_manager = ScreenManager()
title_screen = TitleScreen(window, screen_manager, ScreenType.MAIN_MENU)
main_menu_screen = MainMenuScreen(window, screen_manager, ScreenType.GAME,
                                  ScreenType.DICTIONARY)
game_screen = GameScreen(window, screen_manager)
dictionary_screen = DictionaryScreen(window, screen_manager)
screen_manager.register(ScreenType.TITLE, title_screen)
screen_manager.register(ScreenType.MAIN_MENU, main_menu_screen)
screen_manager.register(ScreenType.GAME, game_screen)
screen_manager.register(ScreenType.DICTIONARY, dictionary_screen)
screen_manager.switch_to(ScreenType.TITLE)

debug_visible = False
debug_panel.init(window, ram_overhead.get_deltas())


#vsync enabled (the default), on_draw() is called once per monitor refresh
def on_draw():
    debug_panel.start_draw()
    
    screen_manager.draw()
    
    if debug_visible:
        debug_panel.draw()
    
    debug_panel.end_draw()


def on_key_press(symbol, modifiers):
    global debug_visible
    debug_panel.start_event()
    
    if symbol in control_keys("global.debug_panel_toggle"):
        debug_visible = not debug_visible
        result = True
    else:
        result = screen_manager.on_key_press(symbol, modifiers)
    
    debug_panel.end_event()
    return result


def on_text(text):
    debug_panel.start_event()
    screen_manager.on_text(text)
    debug_panel.end_event()


def on_mouse_press(x, y, button, modifiers):
    debug_panel.start_event()
    screen_manager.on_mouse_press(x, y, button, modifiers)
    debug_panel.end_event()


def on_mouse_motion(x, y, dx, dy):
    screen_manager.on_mouse_motion(x, y, dx, dy)


# Window focus / size events. Logged (no-op unless a session is open) so a
# macOS focus or Space change that desyncs the Retina coordinate scale -- and
# misplaces subsequent clicks -- is visible in the session timeline. These
# handlers only observe; returning nothing lets pyglet's own on_resize (which
# resets the GL viewport) still run.
def on_activate():
    w, h = window.get_size()
    L.log_00010(True, w, h, window.get_pixel_ratio())


def on_deactivate():
    w, h = window.get_size()
    L.log_00010(False, w, h, window.get_pixel_ratio())


def on_resize(width, height):
    w, h = window.get_size()
    L.log_00011(w, h, window.get_pixel_ratio())


#update_game_tick is called at the frequency we decide
def update_game_tick(dt):
    debug_panel.start_update()
    screen_manager.update(dt)
    debug_panel.end_update()


window.push_handlers(
    on_draw=on_draw,
    on_key_press=on_key_press,
    on_text=on_text,
    on_mouse_press=on_mouse_press,
    on_mouse_motion=on_mouse_motion,
    on_activate=on_activate,
    on_deactivate=on_deactivate,
    on_resize=on_resize
)
ups = 1 / CONFIG["game"]["ups"]
pyglet.clock.schedule_interval(update_game_tick, ups) #Updates Per Second
pyglet.app.run()