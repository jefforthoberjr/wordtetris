"""How the endgame typing bonus SHOWS the words to be typed, over the board region
that play has finished with (endgame.display).

Each display is a small, interchangeable view over the same target list -- built by
a rule in views/endgame_typing.py, then driven through the same three calls:
show(targets), refresh(targets) when one is typed, and update(dt) / draw() per
frame. They differ only in how the words are presented, which is the difficulty
knob: a whole page the player can read at leisure, or words that move and must be
caught. Duck-typed, no base class (see TECH.md).

A target is the dict EndgameTyping builds: {"word", "variation", "points", "done"}.
"""
import math
import pyglet

from config import CONFIG, get_color
from views.gram_preview import GramPreview


class PageDisplay:
    """One printed page: every word laid out at once in top-to-bottom columns, like
    a page of the dictionary screen. The gentlest display -- nothing moves, nothing
    scrolls off, and the whole set is readable at a glance, which is the point for a
    young player working through a list of words to copy.

    Assumes the cleared-word count stays small enough to fit one page (it is bounded
    by how many words a game produces). The font auto-shrinks to fit both the height
    and the column width, so a long list gets smaller rather than overflowing."""

    # Font sizing bounds, as fractions of the board region -- never raw pixels.
    MAX_FONT_FRACTION = 1 / 14
    MIN_FONT_FRACTION = 1 / 44
    # Line height and average glyph width as multiples of the font size (the
    # proportional default font measures ~0.62 em per char; the same figure the
    # scrolling word list uses).
    LINE_SPACING = 1.5
    CHAR_WIDTH = 0.62
    # Gap between columns, as a fraction of a column's width.
    COLUMN_GAP = 0.08
    # Cell rows are bigger than the same word in text -- each letter gets a box --
    # so cell mode starts from a smaller font and leaves more room between rows.
    CELL_FONT_SCALE = 0.75
    CELL_ROW_SPACING = 1.5

    def __init__(self, region_size, window_height, cells=False):
        self._region_size = region_size
        self._window_height = window_height
        # Draw each word as its cleared CELLS rather than as text (endgame.render).
        self._cells = cells
        self._batch = pyglet.graphics.Batch()
        self._views = []

    def show(self, targets):
        """(Re)build the page for `targets`, in the order given. A fresh batch each
        call releases the previous page's labels."""
        self._batch = pyglet.graphics.Batch()
        self._views = []
        if targets:
            self._build(targets)

    def _build(self, targets):
        margin = math.floor(self._region_size / 16)
        usable_w = self._region_size - 2 * margin
        usable_h = self._window_height - 2 * margin
        longest = 0
        for target in targets:
            if len(target["word"]) > longest:
                longest = len(target["word"])
        font_size, rows, col_width = self._fit(len(targets), longest, usable_w, usable_h)
        # A cell row is taller and wider than the same word in text, so give it a
        # smaller base size to keep the page inside the region.
        if self._cells:
            font_size = math.floor(font_size * self.CELL_FONT_SCALE)
        row_height = math.floor(font_size * self.LINE_SPACING * self._row_spacing())
        top = self._window_height - margin
        for i, target in enumerate(targets):
            col = math.floor(i / rows)
            row = i - col * rows
            view = _WordView(self._cells, font_size, self._batch)
            view.set_target(target)
            view.place(margin + col * col_width,
                       top - row * row_height - math.floor(row_height / 2))
            self._views.append(view)

    def _row_spacing(self):
        """Extra line spacing in cell mode, where each row is a strip of boxes."""
        if self._cells:
            spacing = self.CELL_ROW_SPACING
        else:
            spacing = 1.0
        return spacing

    def _fit(self, count, longest, usable_w, usable_h):
        """The largest font size at which `count` words -- the longest of them
        `longest` characters -- fit the region in top-to-bottom columns, with the
        (font_size, rows_per_column, column_width) that go with it.

        Walks sizes down from MAX_FONT_FRACTION: at each size the rows per column
        follow from the height, the column count from the rows, and the fit test is
        whether the longest word still fits its column's width. The smallest size is
        returned whether or not it fits, so a pathological list still draws (just
        tight) rather than vanishing."""
        best = None
        size = math.floor(self._region_size * self.MAX_FONT_FRACTION)
        floor_size = max(6, math.floor(self._region_size * self.MIN_FONT_FRACTION))
        while size >= floor_size and best is None:
            row_height = math.floor(size * self.LINE_SPACING)
            rows = max(1, math.floor(usable_h / row_height))
            columns = max(1, math.ceil(count / rows))
            col_width = math.floor(usable_w / columns)
            text_width = longest * size * self.CHAR_WIDTH
            if text_width <= col_width * (1 - self.COLUMN_GAP) and rows * columns >= count:
                best = (size, rows, col_width)
            else:
                size -= 1
        if best is None:
            row_height = math.floor(floor_size * self.LINE_SPACING)
            rows = max(1, math.floor(usable_h / row_height))
            columns = max(1, math.ceil(count / rows))
            best = (floor_size, rows, math.floor(usable_w / columns))
        return best

    def refresh(self, targets):
        """After a word was typed: done words turn green (text) or fill green (cell
        rows), so the page fills in as the player works through it."""
        for target, view in zip(targets, self._views):
            view.set_target(target)
            view.restyle()

    def update(self, dt):
        """Nothing moves on a page."""
        return None

    def draw(self):
        self._batch.draw()
        if self._cells:
            for view in self._views:
                view.draw()


class _WordView:
    """One word on screen, drawn EITHER as plain text or as the cells it was cleared
    with (endgame.render) -- the one place that choice is made, so all three displays
    get it from the same code.

    In cell mode the word re-renders as the row of pieces the player actually built
    it from, exactly as the dictionary screen re-renders a collected word: the same
    grid shape, the same obstacle / mission fills, the wild-vowel emblem. That is the
    point of the mode -- the player types what they see themselves having made,
    rather than a plain word. A word already typed is filled green instead.

    Reused frame to frame: set_target only rebuilds when the word CHANGES (a scrolling
    slot rolls onto a new ring word), and place() then just moves what is already
    built. Rebuilding a cell row every frame would churn the batch at 60fps."""

    def __init__(self, cells, font_size, batch):
        self._cells = cells
        self._word = None
        self._color = get_color("endgame.target_text")
        self._left = 0.0
        self._center = 0.0
        if cells:
            # No backing rect: the cells ARE the word here, with nothing underneath
            # to hide (the dictionary screen's preview pops up over a text label).
            self._label = None
            self._preview = GramPreview(
                cell_size=font_size * 1.25, row_height=font_size * 1.6, backing=False)
            self._done_preview = GramPreview(
                cell_size=font_size * 1.25, row_height=font_size * 1.6, backing=False,
                fill_override=get_color("endgame.cell_done_fill"))
            self._active = self._preview
        else:
            self._preview = None
            self._done_preview = None
            self._active = None
            self._label = pyglet.text.Label(
                "", font_size=font_size, x=0, y=0,
                anchor_x="left", anchor_y="center",
                color=self._color, batch=batch,
            )

    def set_target(self, target):
        """Show `target` (a blank ring slot shows nothing). Cheap when the word and
        its typed state are unchanged."""
        word = target["word"]
        state = (word, target["done"])
        if state != self._word:
            self._word = state
            self._color = _target_color(target)
            if self._cells:
                self._set_cells(target)
            else:
                self._label.text = word

    def _set_cells(self, target):
        """(Re)build the cell row: the done row is a separate preview so the two
        fills never fight over one batch. A word with no recorded grouping (or a
        blank slot) falls back to showing nothing rather than an empty box."""
        if target["done"]:
            self._active = self._done_preview
        else:
            self._active = self._preview
        self._preview.hide()
        self._done_preview.hide()
        if target["word"] and target["variation"]:
            self._active.show(target["variation"], self._left, self._center,
                              cover_width=0)
        else:
            self._active = None

    def width(self):
        """How wide the drawn word is, so a caller can center it in a column."""
        if self._cells:
            drawn = self._active.row_width if self._active is not None else 0
        else:
            drawn = self._label.content_width
        return drawn

    def place(self, left_x, center_y, alpha=255):
        """Move the word so its left edge sits at left_x, vertically centered on
        center_y, at the given opacity (the moving displays' edge fade)."""
        if self._cells:
            if self._active is not None:
                self._active.move_by(left_x - self._left, center_y - self._center)
        else:
            self._label.x = left_x
            self._label.y = center_y
            self._label.color = (self._color[0], self._color[1], self._color[2], alpha)
        self._left = left_x
        self._center = center_y

    def restyle(self, alpha=255):
        """Re-apply the current target's color where the word already sits -- what a
        static display needs after a word is typed and turns green."""
        self.place(self._left, self._center, alpha)

    def draw(self):
        """Cell rows own their own batch, so they draw here; a text word is already
        in the display's shared batch and draws with it."""
        if self._cells and self._active is not None:
            self._active.draw()


# A gap on the belt: a ring slot carrying no word. Drawn as empty text and never
# typeable, it exists only to space the real words out (see _build_ring).
_BLANK = {"word": "", "variation": "", "points": 0, "done": False}


class _MovingWords:
    """Shared machinery for the two MOVING displays: a looping ring of word labels
    that drifts through the board region, modelled on the idea belt (one ring, seen
    through sliding windows) so the two behave the same way on screen.

    A word that scrolls out of view is NOT lost -- the ring loops, so it comes back
    around, and in the meantime it can still be typed: the typing field never cares
    what is currently visible. A player who remembers a word can type it before it
    has ever appeared, which is fine (and rewarded).

    Subclasses provide the columns: where each one sits, which way it travels, and
    how far along the ring it looks (`_columns`)."""

    # Vertical space one word occupies, as a share of the region height, follows
    # from the configured visible count. These shape the label inside that band.
    FONT_OF_BAND = 0.5
    CHAR_WIDTH = 0.62
    # Words fade out over the outermost share of the region, so they arrive and
    # leave rather than popping at the edge.
    FADE_ZONE = 0.18
    # A cell row takes more room than the same word in text (a box per letter), so
    # cell mode starts from a smaller font (see PageDisplay.CELL_FONT_SCALE).
    CELL_FONT_SCALE = 0.7

    def __init__(self, region_size, window_height, visible, speed, offset=0,
                 min_ring=0, cells=False):
        self._cells = cells
        self._region_size = region_size
        self._window_height = window_height
        self._visible = max(1, visible)
        self._speed = speed
        self._offset = max(0, offset)
        # Shortest the ring may be, in slots; 0 means "work it out" (_min_ring).
        # Short games clear few words, and a ring shorter than what is on screen
        # shows the SAME word two or three times at once -- distracting, and in the
        # two-column belt it reads as the columns being in lockstep. Padding the
        # ring with BLANK slots spaces the words out instead. See _build_ring.
        self._min_ring = max(0, min_ring)
        self._targets = []
        self._ring = []
        # How far the ring has travelled, in WORDS (fractional); only increases.
        self._scroll = 0.0
        self._band = window_height / self._visible
        # One spare slot at each end for the words part-way in and out of view.
        self._slot_count = self._visible + 2
        self._batch = pyglet.graphics.Batch()
        self._slots = []

    def show(self, targets):
        """(Re)build the slots for `targets` and rewind the ring to its start."""
        self._targets = targets
        self._ring = self._build_ring(targets)
        self._scroll = 0.0
        self._batch = pyglet.graphics.Batch()
        self._slots = []
        if targets:
            font_size = self._font_size(targets)
            if self._cells:
                font_size = math.floor(font_size * self.CELL_FONT_SCALE)
            for _column in self._columns():
                for _slot in range(self._slot_count):
                    self._slots.append(_WordView(self._cells, font_size, self._batch))
            self._layout()

    def _build_ring(self, targets):
        """The looping sequence the windows read: the words, spaced out with BLANK
        slots until the ring is at least _ring_minimum() long. The blanks are gaps on
        the belt, nothing more -- they draw as empty and can't be typed (a blank never
        matches, since a submit needs a typed word).

        Blanks are spread as evenly as the count allows rather than appended in a
        lump, so a short list reads as words with gaps between them instead of a
        cluster of words followed by a long empty stretch."""
        words = list(targets)
        wanted = self._ring_minimum()
        if not words or len(words) >= wanted:
            ring = words
        else:
            blanks = wanted - len(words)
            ring = []
            placed = 0
            for i, target in enumerate(words):
                ring.append(target)
                # Blanks owed after this word: the running share, so the remainder
                # is spread across the ring rather than all landing at the end.
                owed = math.floor(blanks * (i + 1) / len(words)) - placed
                for _b in range(owed):
                    ring.append(_BLANK)
                placed += owed
        return ring

    def _ring_minimum(self):
        """How many slots the ring must span before it may repeat. Default: enough
        that no word is on screen twice. Configurable per display (see the build_*
        helpers); a subclass with two windows widens it (see BeltDisplay)."""
        if self._min_ring:
            minimum = self._min_ring
        else:
            minimum = self._slot_count
        return minimum

    def _font_size(self, targets):
        """Text sized to the band, then shrunk if the longest word would overrun its
        column -- so a long word stays inside its lane instead of colliding with the
        neighbouring one."""
        longest = 0
        for target in targets:
            if len(target["word"]) > longest:
                longest = len(target["word"])
        by_band = self._band * self.FONT_OF_BAND
        column_width = self._region_size / len(self._columns())
        by_width = column_width * 0.9 / max(1, longest * self.CHAR_WIDTH)
        return max(8, math.floor(min(by_band, by_width)))

    def update(self, dt):
        """Advance the ring and re-place every slot."""
        if self._slots:
            self._scroll += self._speed * dt
            self._layout()

    def refresh(self, targets):
        """A word was typed: re-place so its slot picks up the done color. The ring
        holds the very same target dicts, so their `done` flags are already current
        -- only the drawing needs redoing."""
        self._targets = targets
        self._layout()

    def positions(self):
        """Where every slot sits this frame, as (slot_index, ring_index, cx, cy) --
        pure geometry, no drawing, so the motion can be checked without a GL context.

        Word `n` of the ring is at travel distance (scroll - n) from a column's
        entry edge, one band per word. A DOWN column measures that same distance
        from the top instead of the bottom, and looks `offset` words back along the
        ring, which is what makes it the same conveyor seen later."""
        placed = []
        base = math.floor(self._scroll) + 1
        slot = 0
        for cx, direction, lag in self._columns():
            for k in range(self._slot_count):
                n = base - k
                travel = self._scroll - n
                if direction > 0:
                    cy = travel * self._band
                else:
                    cy = self._window_height - travel * self._band
                placed.append((slot, n - lag, cx, cy))
                slot += 1
        return placed

    def _layout(self):
        for slot, ring_index, cx, cy in self.positions():
            self._place(self._slots[slot], ring_index, cx, cy)

    def _place(self, view, ring_index, cx, cy):
        """Move one slot to (cx, cy) and show the ring word it now carries, CENTERED
        on the column (the view places from its left edge, so subtract half its
        width). A slot whose band has run off either end of the region is drawn fully
        transparent rather than outside the region. A blank ring slot draws as
        nothing -- a deliberate gap on the belt (see _build_ring)."""
        target = self._ring[ring_index % len(self._ring)]
        view.set_target(target)
        view.place(cx - view.width() / 2, cy, self._edge_alpha(cy))

    def _edge_alpha(self, cy):
        """Full opacity through the middle of the region, ramping to nothing across
        the outer FADE_ZONE, and zero outside it."""
        fade = self._window_height * self.FADE_ZONE
        if cy < 0 or cy > self._window_height:
            share = 0.0
        elif cy < fade:
            share = cy / fade
        elif cy > self._window_height - fade:
            share = (self._window_height - cy) / fade
        else:
            share = 1.0
        return math.floor(255 * share)

    def draw(self):
        self._batch.draw()
        if self._cells:
            for view in self._slots:
                view.draw()


class ScrollDisplay(_MovingWords):
    """One slow column of LARGE words drifting up the middle of the region, looping
    forever. Fewer words on screen than the page shows, in much bigger text, and the
    player has to catch each one as it comes round -- a little pressure without a
    clock, since nothing is ever lost (see _MovingWords)."""

    def _columns(self):
        """A single centered column travelling up."""
        return [(self._region_size / 2, 1, 0)]


class BeltDisplay(_MovingWords):
    """The two-column conveyor, mirroring the idea belt: the LEFT column drifts up
    and the RIGHT column drifts down, both windows onto ONE looping ring. The right
    window trails the left by `endgame.belt_window_offset` words, so a word leaving
    the top of the left column comes back into view on the right column that many
    words later, like one conveyor looping out of sight through a kitchen."""

    def __init__(self, *args, **kwargs):
        _MovingWords.__init__(self, *args, **kwargs)
        # The two windows must not overlap ON THE RING, or the same word is on screen
        # in both columns at once -- one copy drifting up the left while the other
        # drifts down the right, which reads as a bug, not a conveyor. The right
        # window trails the left by `offset` words and each window spans _slot_count
        # words, so a lag SHORTER than a window guarantees overlap no matter how long
        # the ring is. Raise it to a full window; a bigger configured offset stands.
        if self._offset < self._slot_count:
            self._offset = self._slot_count

    def _columns(self):
        """Left column up, right column down and lagging by the window offset."""
        quarter = self._region_size / 4
        return [(quarter, 1, 0), (quarter * 3, -1, self._offset)]

    def _ring_minimum(self):
        """Wider than the single-column default: the ring must span the lag between
        the windows PLUS a window, or it wraps around and the two windows meet from
        the other side -- the same clash the offset clamp above prevents head-on. On
        a short word list the shortfall is made up with blank gaps (see _build_ring),
        which is what keeps a 3-word game from running the columns in lockstep."""
        if self._min_ring:
            minimum = self._min_ring
        else:
            minimum = self._offset + self._slot_count
        return minimum


def _rule_int(key, default):
    """One endgame display knob, read from the LIVE config at call time (never at
    import, which would freeze the base value before a game mode is applied)."""
    return int(CONFIG.get("rules", {}).get(key, default))


def _rule_float(key, default):
    return float(CONFIG.get("rules", {}).get(key, default))


def render_cells_rule():
    """Whether words draw as their cleared CELLS rather than as plain text
    (endgame.render). Read from the live config at call time, like every knob here,
    so the active game mode's choice applies. Unknown values fall back to text."""
    return CONFIG.get("rules", {}).get(
        "endgame.render", "rule_endgame_render_text") == "rule_endgame_render_cells"


def build_page_display(region_size, window_height):
    """A PageDisplay in the configured render mode (see endgame.display)."""
    return PageDisplay(region_size, window_height, cells=render_cells_rule())


def build_scroll_display(region_size, window_height):
    """A ScrollDisplay configured from endgame.scroll_* (see endgame.display)."""
    return ScrollDisplay(region_size, window_height,
                         visible=_rule_int("endgame.scroll_visible_words", 5),
                         speed=_rule_float("endgame.scroll_speed", 0.25),
                         min_ring=_rule_int("endgame.scroll_min_ring", 0),
                         cells=render_cells_rule())


def build_belt_display(region_size, window_height):
    """A BeltDisplay configured from endgame.belt_* (see endgame.display)."""
    return BeltDisplay(region_size, window_height,
                       visible=_rule_int("endgame.belt_visible_words", 7),
                       speed=_rule_float("endgame.belt_speed", 0.3),
                       offset=_rule_int("endgame.belt_window_offset", 5),
                       min_ring=_rule_int("endgame.belt_min_ring", 0),
                       cells=render_cells_rule())


def _target_color(target):
    """A target word's color: green once typed, the normal text color before."""
    if target["done"]:
        color = get_color("endgame.target_done_text")
    else:
        color = get_color("endgame.target_text")
    return color
