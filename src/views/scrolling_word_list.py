import math
import pyglet
from config import get_color


class ScrollingWordList:
    """Top-anchored list of cleared words: newest on top, older words slide
    down one row each time a new word arrives, and the bottom row falls off
    (no scrollback -- the user cannot scroll dropped words back into view).
    Backed by a fixed ring of pre-spawned Labels.

    Performance trade-off (measured, pyglet 2.1.14, ~30 rows, dev machine):
    scrolling this way costs 1 glyph-layout rebuild + N cheap label moves per
    word (~0.094 ms), vs. ~1.6 ms if we instead rewrote every row's .text on
    every scroll -- about 16x cheaper.

    Why: setting Label.text re-runs CPU glyph layout (advances/kerning) and
    rebuilds every vertex attribute array for that label (~52 us each), whereas
    moving a label only overwrites its `translation` attribute in place
    (~1.4 us each) with no reshape and no buffer reallocation. So each scroll
    rewrites the .text of just the one row recycled from bottom to top and
    merely repositions the rest. Padding every word to PAD_LEN chars holds the
    glyph (vertex) count constant so even that lone text update never
    reallocates the vertex buffer, and the blank pre-fill warms the buffer to
    its high-water mark at construction.
    """

    PAD_LEN = 12
    TEXT_COLOR = get_color("moving_side_pane.wordlist_text")
    # A word the player has never collected before shows green instead.
    NEW_TEXT_COLOR = get_color("moving_side_pane.wordlist_new_text")

    def __init__(self, x, y, width, height):
        self._batch = pyglet.graphics.Batch()

        margin = width // 16
        text_x = x + margin
        self._top_y = y + height - margin

        # Fit PAD_LEN chars across the pane; ~0.62 avg char-width/font-size for
        # the default proportional font. Tune the factor if wide words clip.
        font_size = (width - 2 * margin) / (self.PAD_LEN * 0.62)
        self._row_height = font_size * 1.3
        self._rows = max(1, math.floor((height - 2 * margin) / self._row_height))

        # Ring of pre-spawned rows, blank-filled to warm the vertex buffer.
        self._labels = []
        for r in range(self._rows):
            label = pyglet.text.Label(
                " " * self.PAD_LEN,
                font_size=font_size,
                x=text_x, y=self._top_y - r * self._row_height,
                anchor_x="left", anchor_y="top",
                color=self.TEXT_COLOR, batch=self._batch,
            )
            self._labels.append(label)

        # Index of the label currently shown at rank 0 (the top row).
        self._head = 0

    def add_word(self, word, is_new=False):
        """Push one word onto the top; everything below slides down one row and
        the old bottom row falls off. Costs one .text rewrite + N label moves.
        `is_new` colors the entry green (a word new to the player's dictionary)."""
        # The label one step behind head is currently the bottom (oldest) row;
        # recycle it as the new top by overwriting only its text.
        self._head = (self._head - 1) % self._rows
        label = self._labels[self._head]
        label.text = word.ljust(self.PAD_LEN)
        # Recycled labels carry the previous occupant's color, so set it every
        # time, not just for new words.
        label.color = self.NEW_TEXT_COLOR if is_new else self.TEXT_COLOR
        # Reposition: rank r (0 = top) is the label r steps forward of head.
        for r in range(self._rows):
            idx = (self._head + r) % self._rows
            self._labels[idx].y = self._top_y - r * self._row_height

    def add_words(self, words, new_flags=None):
        """Add several words, oldest first. `new_flags`, if given, is a parallel
        list of booleans marking which words are new to the player's dictionary."""
        if new_flags is None:
            new_flags = [False] * len(words)
        for word, is_new in zip(words, new_flags):
            self.add_word(word, is_new)

    def reset(self):
        """Blank every row and restore the top-anchored order, for a new game."""
        self._head = 0
        for r, label in enumerate(self._labels):
            label.text = " " * self.PAD_LEN
            label.color = self.TEXT_COLOR
            label.y = self._top_y - r * self._row_height

    def draw(self):
        self._batch.draw()
