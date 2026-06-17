import math
import pyglet
from config import get_color, get_string


class VictoryOverlay:
    """End-state overlay: a solid panel + big centered label drawn over the grid
    region (the left square) when the game freezes. Built once and drawn only in
    the VICTORY phase. The label text distinguishes a win ("VICTORY") from a
    plain finish ("FINISHED"); set it via set_text before showing the overlay.
    """

    def __init__(self, grid_area_size, window_height):
        # Sized off the window so it scales with the framebuffer (retina-safe).
        self._batch = pyglet.graphics.Batch()
        grid_cx = math.floor(grid_area_size / 2)
        grid_cy = math.floor(window_height / 2)
        panel_w = math.floor(grid_area_size * 0.7)
        panel_h = math.floor(window_height * 0.22)
        self._panel = pyglet.shapes.Rectangle(
            grid_cx - math.floor(panel_w / 2), grid_cy - math.floor(panel_h / 2),
            panel_w, panel_h, color=get_color("victory.panel"),
            batch=self._batch,
        )
        self._label = pyglet.text.Label(
            get_string("victory"), font_size=math.floor(window_height / 8),
            x=grid_cx, y=grid_cy, anchor_x="center", anchor_y="center",
            color=get_color("victory.text"), batch=self._batch,
        )

    def set_text(self, text):
        """Set the centered label (e.g. VICTORY vs FINISHED) for this end-state."""
        self._label.text = text

    def draw(self):
        self._batch.draw()
