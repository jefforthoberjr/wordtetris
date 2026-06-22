import ram_overhead
ram_overhead.measure("after_psutil")

import pyglet
ram_overhead.measure("after_pyglet")

from config import CONFIG
from controls import control_keys
import debug_panel
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
    on_mouse_motion=on_mouse_motion
)
ups = 1 / CONFIG["game"]["ups"]
pyglet.clock.schedule_interval(update_game_tick, ups) #Updates Per Second
pyglet.app.run()