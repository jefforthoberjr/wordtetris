import pyglet
from views.shaders import get_shape_shader
from config import get_color, get_string


class LoadSidePane:
    """Right pane shown during the LOADING phase (the opening reveal). A bare
    twin of the moving/selecting panes: the same left-edge divider plus a single
    "LOADING..." label pinned to the top edge, where the moving pane shows its
    pieces/time counter. Kept as its own class so its UI can diverge later (a
    progress bar, a spinner, art) without touching the play panes.
    """

    DIVIDER_COLOR = get_color("moving_side_pane.divider")
    PHASE_LABEL_COLOR = get_color("moving_side_pane.phase_label")

    def __init__(self, x, y, width, height):
        self._x = x
        self._y = y
        self._width = width
        self._height = height
        self._batch = pyglet.graphics.Batch()

        # Sized from the pane width (not fixed pixels) so it scales on retina
        # displays, matching the moving/selecting side panes.
        margin = max(6, width // 12)
        base = max(12, int(width * 0.09))

        # Divider sits on the pane's left edge, between it and the grid -- the
        # same rule the moving pane draws, so the frame looks unchanged while
        # the board fades in to its left.
        self._divider = pyglet.shapes.Line(
            x, y, x, y + height,
            thickness=1, color=self.DIVIDER_COLOR, batch=self._batch,
            program=get_shape_shader()
        )

        # "LOADING..." pinned to the top edge, where the moving pane's
        # pieces/time counter sits.
        label_y = y + height - margin
        self._label = pyglet.text.Label(
            get_string("loading"), font_size=base * 0.7, x=x + margin, y=label_y,
            anchor_x="left", anchor_y="top",
            color=self.PHASE_LABEL_COLOR, batch=self._batch,
        )

    @property
    def x(self):
        return self._x

    @property
    def width(self):
        return self._width

    def set_calculating(self):
        """Swap the top-edge label to "CALCULATING..." while the blocking
        starting-coverage pass runs (game_screen.starting_coverage_dictionary)."""
        self._label.text = get_string("calculating")

    def set_loading(self):
        """Restore the default "LOADING..." label (after the coverage pass, so the
        opening reveal shows the normal text)."""
        self._label.text = get_string("loading")

    def draw(self):
        self._batch.draw()
