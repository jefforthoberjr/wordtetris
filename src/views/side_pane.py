import pyglet
from views.shaders import get_shape_shader


class SidePane:
    """Blank pane sitting to the right of the grid. Owns the divider line that
    visually separates it from the grid area on its left edge.

    Intentionally empty for now; content gets added here next.
    """

    DIVIDER_COLOR = (200, 200, 200)

    def __init__(self, x, y, width, height):
        self._x = x
        self._y = y
        self._width = width
        self._height = height
        self._batch = pyglet.graphics.Batch()

        # Divider sits on the pane's left edge, between it and the grid.
        self._divider = pyglet.shapes.Line(
            x, y, x, y + height,
            thickness=1, color=self.DIVIDER_COLOR, batch=self._batch,
            program=get_shape_shader()
        )

    @property
    def x(self):
        return self._x

    @property
    def width(self):
        return self._width

    def draw(self):
        self._batch.draw()
