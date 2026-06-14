import pyglet
from views.shaders import get_shape_shader
from views.scrolling_word_list import ScrollingWordList
from config import get_color


class MovingSidePane:
    """Right pane shown during the MOVING phase. Owns the divider line that
    visually separates it from the grid area on its left edge, and a scrolling
    list of the words the player has cleared.
    """

    DIVIDER_COLOR = get_color("moving_side_pane.divider")
    COUNT_COLOR = get_color("moving_side_pane.word_count")
    PHASE_LABEL_COLOR = get_color("moving_side_pane.phase_label")

    def __init__(self, x, y, width, height):
        self._x = x
        self._y = y
        self._width = width
        self._height = height
        self._batch = pyglet.graphics.Batch()

        # Sized from the pane width (not fixed pixels) so it scales on retina
        # displays, matching the selecting side pane.
        margin = max(6, width // 12)
        base = max(12, int(width * 0.09))
        line_h = base * 1.6

        # Divider sits on the pane's left edge, between it and the grid.
        self._divider = pyglet.shapes.Line(
            x, y, x, y + height,
            thickness=1, color=self.DIVIDER_COLOR, batch=self._batch,
            program=get_shape_shader()
        )

        # Placements left until the next selection phase ("Pieces: N"), pinned to
        # the very top edge, above the cleared-word list.
        phase_label_y = y + height - margin
        self._phase_label = pyglet.text.Label(
            "", font_size=base * 0.7, x=x + margin, y=phase_label_y,
            anchor_x="left", anchor_y="top",
            color=self.PHASE_LABEL_COLOR, batch=self._batch,
        )

        # Player's lifetime dictionary size, pinned to the very bottom edge.
        count_y = y + margin
        self._count = pyglet.text.Label(
            "", font_size=base * 0.7, x=x + margin, y=count_y,
            anchor_x="left", anchor_y="bottom",
            color=self.COUNT_COLOR, batch=self._batch,
        )

        # The cleared-word list fills the pane between the count label (bottom)
        # and the select-counter label (top), reserving one line for each.
        list_bottom = count_y + line_h
        list_height = max(line_h, height - margin - line_h - line_h)
        self._word_list = ScrollingWordList(x, list_bottom, width, list_height)

    @property
    def x(self):
        return self._x

    @property
    def width(self):
        return self._width

    def add_cleared_words(self, words, new_flags=None):
        """Show words just cleared, newest on top. `new_flags`, if given, marks
        which words are new to the player's dictionary (shown green)."""
        self._word_list.add_words(words, new_flags)

    def set_word_count(self, count):
        """Show the player's lifetime dictionary size along the bottom edge."""
        self._count.text = f"Dictionary: {count} words"

    def set_phase_label(self, count):
        """Show how many more pieces until the next selection phase, top edge."""
        self._phase_label.text = f"Pieces: {count}"

    def reset(self):
        """Clear the cleared-words list back to empty for a new game."""
        self._word_list.reset()

    def draw(self):
        self._batch.draw()
        self._word_list.draw()
