import time
import pyglet
from config import CONFIG


window = pyglet.window.Window(
    width=CONFIG["window"]["width"],
    height=CONFIG["window"]["height"],
    caption=CONFIG["window"]["title"]
)

batch = pyglet.graphics.Batch()
debug_batch = pyglet.graphics.Batch()

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
last_frame_time_ms = 0.0

debug_panel = pyglet.shapes.Rectangle(
    x=window.width - 160,
    y=window.height - 60,
    width=150,
    height=50,
    color=(200, 200, 200, 180),
    batch=debug_batch
)

debug_label = pyglet.text.Label(
    "Frame: 0.00 ms",
    font_size=12,
    x=window.width - 150,
    y=window.height - 25,
    color=(0, 0, 0, 255),
    batch=debug_batch
)


def on_draw():
    global last_frame_time_ms
    start_time = time.perf_counter()
    
    window.clear()
    batch.draw()
    
    if debug_visible:
        debug_label.text = f"Frame: {last_frame_time_ms:.2f} ms"
        debug_batch.draw()
    
    end_time = time.perf_counter()
    last_frame_time_ms = (end_time - start_time) * 1000


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