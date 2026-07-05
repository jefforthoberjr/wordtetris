import pyglet
from views.shaders import get_shape_shader
from config import CONFIG, get_color


class DisambiguationLines:
    """Overlay of candidate polylines for the SELECT-phase "Select which one:"
    chooser: when a submitted word can clear several ways, each candidate path is
    drawn center-to-center across the cells it would consume. The unselected
    candidates are light blue; the one the player is cycling on is dark blue and
    drawn last so it reads on top where paths overlap.

    A sibling of views.word_trail.WordTrail (same batched-Line idiom), but
    transient rather than accumulating: rebuilt on every cycle via show() and
    dropped on confirm / cancel via clear(). Style comes from config:
    game_screen.disambig_line_thickness / _opacity and the colors.yaml
    board.disambig_line[_selected] colors.

    Only ever populated under a game_screen.clear_disambiguation cycle rule
    (rule_disambig_cycle_two_or_more_choices / _one_or_more_choices); the auto-
    pick rule never opens a chooser, so this stays empty there."""

    COLOR = get_color("board.disambig_line")
    SELECTED_COLOR = get_color("board.disambig_line_selected")
    # Selected vs unselected can be different weights (the highlighted path is
    # usually thicker as well as darker), each from its own config key.
    THICKNESS = CONFIG["rules"]["game_screen.disambig_line_thickness"]
    SELECTED_THICKNESS = CONFIG["rules"]["game_screen.disambig_line_thickness_selected"]
    # Config stores opacity as a 0-1 fraction (1.0 = opaque); pyglet wants 0-255.
    OPACITY = round(255 * CONFIG["rules"]["game_screen.disambig_line_opacity"])

    def __init__(self):
        self._batch = pyglet.graphics.Batch()
        # Kept so the Line objects aren't garbage-collected while batched.
        self._segments = []

    def show(self, paths, selected):
        """Render one polyline per candidate. `paths` is a list of point lists
        (each [(px, py), ...] cell centers in word order); `selected` indexes the
        highlighted candidate. A fresh batch replaces the previous frame, so this
        doubles as the per-cycle re-render. The selected path is drawn LAST (and
        dark) so it sits above the light ones wherever they share cells. A 0/1-
        cell candidate has no segment to draw (matches WordTrail)."""
        self._batch = pyglet.graphics.Batch()
        self._segments = []
        # Unselected first, selected last -> selected renders on top.
        order = [i for i in range(len(paths)) if i != selected]
        if 0 <= selected < len(paths):
            order.append(selected)
        for i in order:
            if i == selected:
                color, thickness = self.SELECTED_COLOR, self.SELECTED_THICKNESS
            else:
                color, thickness = self.COLOR, self.THICKNESS
            self._add_path(paths[i], color, thickness)

    def _add_path(self, points, color, thickness):
        shader = get_shape_shader()
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            line = pyglet.shapes.Line(
                x1, y1, x2, y2,
                thickness=thickness, color=color,
                batch=self._batch, program=shader,
            )
            line.opacity = self.OPACITY
            self._segments.append(line)

    def clear(self):
        """Drop every candidate line (the chooser closed). A fresh batch releases
        the old segments for GC, matching WordTrail.clear()."""
        self._segments = []
        self._batch = pyglet.graphics.Batch()

    def draw(self):
        self._batch.draw()
