import pyglet
from config import CONFIG


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


def on_draw():
    window.clear()
    batch.draw()


def on_key_press(symbol, modifiers):
    if symbol == pyglet.window.key.ESCAPE:
        window.close()


def update(dt):
    pass


window.push_handlers(
    on_draw=on_draw,
    on_key_press=on_key_press
)
pyglet.clock.schedule_interval(update, 1 / 60)
pyglet.app.run()