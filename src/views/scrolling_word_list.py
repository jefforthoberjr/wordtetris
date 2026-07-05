import pyglet
from config import CONFIG, get_color


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
    # A NEW word valid only via the obscure tier shows orange (wins over green).
    OBSCURE_TEXT_COLOR = get_color("moving_side_pane.wordlist_obscure_text")
    # How many word rows the list shows (config moving_side_pane.wordlist_rows).
    # Fewer rows pack from the top at the width-based font (blank space below);
    # more rows than naturally fit shrink the font so they all stay in the pane.
    ROWS = max(1, CONFIG["rules"]["moving_side_pane.wordlist_rows"])

    def __init__(self, x, y, width, height):
        self._batch = pyglet.graphics.Batch()

        margin = width // 16
        text_x = x + margin
        self._top_y = y + height - margin

        # Row count is configured (ROWS), not derived from height. Size the font
        # to fit PAD_LEN chars across the pane (~0.62 avg char-width/font-size for
        # the default proportional font; tune if wide words clip), but cap it so
        # all ROWS rows still fit the pane height -- so asking for more rows than
        # would naturally fit shrinks the text rather than overflowing the pane.
        self._rows = self.ROWS
        width_font = (width - 2 * margin) / (self.PAD_LEN * 0.62)
        height_font = (height - 2 * margin) / (self._rows * 1.3)
        font_size = min(width_font, height_font)
        self._row_height = font_size * 1.3

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

    def _entry_color(self, is_new, is_obscure):
        """Row color, orange (new + obscure-tier) winning over green (new) over
        the normal text color -- so a rare word the player just discovered stands
        out from an ordinary new word."""
        if is_new and is_obscure:
            return self.OBSCURE_TEXT_COLOR
        if is_new:
            return self.NEW_TEXT_COLOR
        return self.TEXT_COLOR

    def add_word(self, word, is_new=False, is_obscure=False):
        """Push one word onto the top; everything below slides down one row and
        the old bottom row falls off. Costs one .text rewrite + N label moves.
        `is_new` colors the entry green; a new word that is `is_obscure` (valid
        only via the obscure tier) shows orange instead."""
        # The label one step behind head is currently the bottom (oldest) row;
        # recycle it as the new top by overwriting only its text.
        self._head = (self._head - 1) % self._rows
        label = self._labels[self._head]
        label.text = word.ljust(self.PAD_LEN)
        # Recycled labels carry the previous occupant's color, so set it every
        # time, not just for new words.
        label.color = self._entry_color(is_new, is_obscure)
        # Reposition: rank r (0 = top) is the label r steps forward of head.
        for r in range(self._rows):
            idx = (self._head + r) % self._rows
            self._labels[idx].y = self._top_y - r * self._row_height

    def add_words(self, words, new_flags=None, obscure_flags=None):
        """Add several words, oldest first. `new_flags` / `obscure_flags`, if
        given, are parallel boolean lists marking which words are new to the
        player's dictionary and which are obscure-tier only (shown orange)."""
        if new_flags is None:
            new_flags = [False] * len(words)
        if obscure_flags is None:
            obscure_flags = [False] * len(words)
        for word, is_new, is_obscure in zip(words, new_flags, obscure_flags):
            self.add_word(word, is_new, is_obscure)

    def word_at(self, x, y):
        """The word shown at pixel y, or None if y is above the top row, below
        the last row, or on a blank row. Rows are top-anchored from self._top_y,
        each self._row_height tall; rank r (0 = top) is r steps forward of head.
        x is ignored here -- the pane bounds the horizontal hit (see
        MovingSidePane.word_at)."""
        if y > self._top_y:
            return None
        rank = int((self._top_y - y) // self._row_height)
        if rank < 0 or rank >= self._rows:
            return None
        idx = (self._head + rank) % self._rows
        word = self._labels[idx].text.rstrip()
        return word or None

    def reset(self):
        """Blank every row and restore the top-anchored order, for a new game."""
        self._head = 0
        for r, label in enumerate(self._labels):
            label.text = " " * self.PAD_LEN
            label.color = self.TEXT_COLOR
            label.y = self._top_y - r * self._row_height

    def draw(self):
        self._batch.draw()
