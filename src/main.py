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


def on_draw():
    debug_panel.start_frame()
    
    window.clear()
    batch.draw()
    
    if debug_visible:
        debug_panel.draw()
    
    debug_panel.end_frame()


def on_key_press(symbol, modifiers):
    global debug_visible
    if symbol == pyglet.window.key.ESCAPE:
        window.close()
    elif symbol == pyglet.window.key.F3:
        debug_visible = not debug_visible


def update(dt):
    pass


window.push_handlers(
    on_draw=on_draw,
    on_key_press=on_key_press
)
pyglet.clock.schedule_interval(update, 1 / CONFIG["window"]["fps"])
pyglet.app.run()