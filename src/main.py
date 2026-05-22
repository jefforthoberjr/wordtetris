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


@window.event
def on_draw():
    window.clear()
    batch.draw()


@window.event
def on_key_press(symbol, modifiers):
    if symbol == pyglet.window.key.ESCAPE:
        window.close()


def update(dt):
    pass


pyglet.clock.schedule_interval(update, 1 / 60)
pyglet.app.run()