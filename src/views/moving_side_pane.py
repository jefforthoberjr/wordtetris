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

        # Player's lifetime dictionary size, pinned to the very bottom edge.
        count_y = y + margin
        self._count = pyglet.text.Label(
            "", font_size=base * 0.7, x=x + margin, y=count_y,
            anchor_x="left", anchor_y="bottom",
            color=self.COUNT_COLOR, batch=self._batch,
        )

        # The cleared-word list fills the pane above the count label, reserving
        # one line for the latter at the bottom.
        list_bottom = count_y + line_h
        list_height = max(line_h, height - margin - line_h)
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

    def reset(self):
        """Clear the cleared-words list back to empty for a new game."""
        self._word_list.reset()

    def draw(self):
        self._batch.draw()
        self._word_list.draw()
