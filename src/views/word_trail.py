import pyglet
from views.shaders import get_shape_shader
from config import CONFIG, get_color


class WordTrail:
    """Overlay of polylines -- one per cleared word -- each connecting the pixel
    centers of the cells the word used, center to center, in word order.

    Trails accumulate for the whole game (game_screen.word_trail = option C) and
    are dropped only on a new game via clear(). Drawn after the board batches so
    they sit on top of the cells and glyphs. Toggle + style come from config:
    game_screen.word_trail (on/off), word_trail_thickness, word_trail_opacity,
    and the colors.yaml board.word_trail color."""

    COLOR = get_color("board.word_trail")
    THICKNESS = CONFIG["rules"]["game_screen.word_trail_thickness"]
    # Config stores opacity as a 0-1 fraction (0.5 = 50%); pyglet wants 0-255.
    OPACITY = round(255 * CONFIG["rules"]["game_screen.word_trail_opacity"])

    def __init__(self):
        self._batch = pyglet.graphics.Batch()
        # Kept so the Line objects aren't garbage-collected while batched.
        self._segments = []

    def add_path(self, points):
        """Add a trail along `points` (a list of (px, py) cell centers in word
        order): one Line segment between each consecutive pair. A 0/1-point path
        adds nothing."""
        shader = get_shape_shader()
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            line = pyglet.shapes.Line(
                x1, y1, x2, y2,
                thickness=self.THICKNESS, color=self.COLOR,
                batch=self._batch, program=shader,
            )
            line.opacity = self.OPACITY
            self._segments.append(line)

    def clear(self):
        """Drop every trail (a new game). A fresh batch releases the old segments
        for GC, matching the per-game batch idiom used for the board."""
        self._segments = []
        self._batch = pyglet.graphics.Batch()

    def draw(self):
        self._batch.draw()
