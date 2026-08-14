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
    # Each row also carries a right-anchored score ("+NN"); padded to a fixed
    # width so its glyph (vertex) count stays constant across scrolls, the same
    # buffer-warming trick PAD_LEN does for the word (covers up to "+9999").
    SCORE_PAD = 5
    # Breakdown mode (scoring.word_score_display) lists several group values
    # ("+A +B +C") in the same right column, so it needs a wider fixed field.
    BREAKDOWN_SCORE_PAD = 15
    TEXT_COLOR = get_color("moving_side_pane.wordlist_text")
    # A word the player has never collected before shows green instead.
    NEW_TEXT_COLOR = get_color("moving_side_pane.wordlist_new_text")
    # A NEW word valid only via the obscure tier shows orange (wins over green).
    OBSCURE_TEXT_COLOR = get_color("moving_side_pane.wordlist_obscure_text")
    # Each word's points, shown right of the word (see add_word `score`).
    SCORE_COLOR = get_color("moving_side_pane.wordlist_score")
    # How many word rows the list shows (config moving_side_pane.wordlist_rows).
    # Fewer rows pack from the top at the width-based font (blank space below);
    # more rows than naturally fit shrink the font so they all stay in the pane.
    ROWS = max(1, CONFIG["rules"]["moving_side_pane.wordlist_rows"])

    def __init__(self, x, y, width, height):
        self._batch = pyglet.graphics.Batch()

        # Fixed width of the right-hand score field: wider in breakdown mode so
        # the "+A +B +C" group list fits (see _score_text). Fixed per instance,
        # so every row still rjusts to the same char count (the buffer-warming
        # invariant PAD_LEN relies on holds).
        display = CONFIG.get("scoring", {}).get("word_score_display", "sum")
        self._score_pad = (self.BREAKDOWN_SCORE_PAD if display == "breakdown"
                           else self.SCORE_PAD)

        margin = width // 16
        text_x = x + margin
        self._top_y = y + height - margin

        # Row count is configured (ROWS), not derived from height. Size the font
        # to fit PAD_LEN chars across the pane (~0.62 avg char-width/font-size for
        # the default proportional font; tune if wide words clip), but cap it so
        # all ROWS rows still fit the pane height -- so asking for more rows than
        # would naturally fit shrinks the text rather than overflowing the pane.
        # Re-read from the live CONFIG rather than the class-level ROWS, which was
        # resolved at import -- before any game mode was applied -- and so holds
        # the base config.yaml value. A ScrollingWordList is built per game (with
        # its side pane), so this reads the active mode's row count. Same pattern
        # as GameScreen._read_config_knobs.
        self._rows = max(1, CONFIG["rules"]["moving_side_pane.wordlist_rows"])
        width_font = (width - 2 * margin) / (self.PAD_LEN * 0.62)
        height_font = (height - 2 * margin) / (self._rows * 1.3)
        font_size = min(width_font, height_font)
        self._row_height = font_size * 1.3

        # Ring of pre-spawned rows, blank-filled to warm the vertex buffer.
        # Each rank has a word label (left) and a score label (right); the two
        # arrays are parallel and share the ring index, so a scroll recycles and
        # repositions both together.
        self._labels = []
        self._score_labels = []
        score_x = x + width - margin
        for r in range(self._rows):
            row_y = self._top_y - r * self._row_height
            label = pyglet.text.Label(
                " " * self.PAD_LEN,
                font_size=font_size,
                x=text_x, y=row_y,
                anchor_x="left", anchor_y="top",
                color=self.TEXT_COLOR, batch=self._batch,
            )
            self._labels.append(label)
            score_label = pyglet.text.Label(
                " " * self._score_pad,
                font_size=font_size,
                x=score_x, y=row_y,
                anchor_x="right", anchor_y="top",
                color=self.SCORE_COLOR, batch=self._batch,
            )
            self._score_labels.append(score_label)

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

    def _score_text(self, score):
        """The right-column text for a word's points, right-justified to the score
        field (constant glyph count), or all blanks when there's nothing to show
        (None, 0, or an empty breakdown list -- disabled scoring / no points).
        `score` is an int in sum mode ("+NN"); in breakdown mode it's a list of
        the non-zero group subtotals, rendered "+A +B +C" (see
        scoring.word_score_display)."""
        if not score:
            return " " * self._score_pad
        if isinstance(score, (list, tuple)):
            text = " ".join("+" + str(p) for p in score)
        else:
            text = "+" + str(score)
        return text.rjust(self._score_pad)

    def add_word(self, word, is_new=False, is_obscure=False, score=None):
        """Push one word onto the top; everything below slides down one row and
        the old bottom row falls off. Costs two .text rewrites + N label moves.
        `is_new` colors the entry green; a new word that is `is_obscure` (valid
        only via the obscure tier) shows orange instead. `score`, if given, shows
        as "+NN" right of the word (its points; see models/scoring.py)."""
        # The label one step behind head is currently the bottom (oldest) row;
        # recycle it as the new top by overwriting only its text.
        self._head = (self._head - 1) % self._rows
        label = self._labels[self._head]
        label.text = word.ljust(self.PAD_LEN)
        # Recycled labels carry the previous occupant's color, so set it every
        # time, not just for new words.
        label.color = self._entry_color(is_new, is_obscure)
        self._score_labels[self._head].text = self._score_text(score)
        # Reposition: rank r (0 = top) is the label r steps forward of head.
        for r in range(self._rows):
            idx = (self._head + r) % self._rows
            row_y = self._top_y - r * self._row_height
            self._labels[idx].y = row_y
            self._score_labels[idx].y = row_y

    def add_words(self, words, new_flags=None, obscure_flags=None, scores=None):
        """Add several words, oldest first. `new_flags` / `obscure_flags` /
        `scores`, if given, are parallel lists: which words are new to the
        player's dictionary, which are obscure-tier only (shown orange), and each
        word's points (shown "+NN" right of the word)."""
        if new_flags is None:
            new_flags = [False] * len(words)
        if obscure_flags is None:
            obscure_flags = [False] * len(words)
        if scores is None:
            scores = [None] * len(words)
        for word, is_new, is_obscure, score in zip(words, new_flags, obscure_flags, scores):
            self.add_word(word, is_new, is_obscure, score)

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
            row_y = self._top_y - r * self._row_height
            label.text = " " * self.PAD_LEN
            label.color = self.TEXT_COLOR
            label.y = row_y
            self._score_labels[r].text = " " * self._score_pad
            self._score_labels[r].y = row_y

    def draw(self):
        self._batch.draw()
