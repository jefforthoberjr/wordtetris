import time
import pyglet
from config import CONFIG
import debug_panel


window = pyglet.window.Window(
    width=CONFIG["window"]["width"],
    height=CONFIG["window"]["height"],
    caption=CONFIG["window"]["title"]
)

batch = pyglet.graphics.Batch()

label = pyglet.text.Label(
    "Hello, World!",
    font_size=36,
    x=window.width // 2,
    y=window.height // 2,
    anchor_x="center",
    anchor_y="center",
    batch=batch
)

debug_visible = False
debug_panel.init(window)


#vsync enabled (the default), on_draw() is called once per monitor refresh
def on_draw():
    debug_panel.start_draw()
    
    window.clear()
    batch.draw()
    
    if debug_visible:
        debug_panel.draw()
    
    debug_panel.end_draw()


def on_key_press(symbol, modifiers):
    global debug_visible
    debug_panel.start_event()
    
    if symbol == pyglet.window.key.ESCAPE:
        window.close()
    elif symbol == pyglet.window.key.F3:
        debug_visible = not debug_visible
    
    debug_panel.end_event()

#update_game_tick is called at the frequency we decide
def update_game_tick(dt):
    debug_panel.start_update()
    
    # Game logic goes here
    
    debug_panel.end_update()


window.push_handlers(
    on_draw=on_draw,
    on_key_press=on_key_press
)
pyglet.clock.schedule_interval(update_game_tick, 1 / CONFIG["game"]["ups"]) #Updates Per Second
pyglet.app.run()