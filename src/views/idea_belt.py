"""The right-pane idea belt: a sushi-bar conveyor of picture prompts.

For young players who know few words, cannot yet spell many, or have simply run
out of ideas, the pane's lower half becomes two slow columns of little pictures --
the left column drifting UP, the right column drifting DOWN. Clicking a picture
types its word into the field above (replacing whatever was there), and every
normal text rule then applies (word hunting, submitting, ...). Nothing about the
belt says whether a word is actually formable on the board.

The two columns are NOT two independent lists: both are sliding WINDOWS onto one
pre-picked ring of items (models/idea_pool.IdeaPool), like one conveyor looping
through a kitchen out of sight. The right window trails the left by
`idea_belt.window_offset` items, so a picture that scrolls off the top of the up
column comes back into view on the down column that many items later, and back
around to the up column one full lap later.

This view owns motion, layout and hit-testing only; the pool owns which items and
in what order. The host pane owns the typed field the picks land in.
"""
import math
import pyglet

from views.shaders import get_shape_shader
from config import CONFIG, get_color
from models.idea_pool import IdeaPool, images_dir
import log_codes as L


# Emoji art is drawn as text, so it needs a font that HAS the emoji. The first
# name that resolves on this machine wins (mac / Windows / Linux). Drawn at full
# white: pyglet multiplies a label's color into the glyph, and any other tint
# would drain the color out of a color-emoji glyph.
EMOJI_FONTS = ("Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji")
EMOJI_COLOR = (255, 255, 255, 255)


class IdeaBelt:
    CIRCLE_FILL = get_color("idea_belt.circle_fill")
    CIRCLE_BORDER = get_color("idea_belt.circle_border")
    WORD_COLOR = get_color("idea_belt.word_text")
    # Fraction of the smaller of (column width, item band) the picture circle
    # fills. Under 0.5 so neighbouring circles never touch: when the belt is
    # configured to show few items the band grows and the gaps open up, which is
    # the "space between the icons" a sparse belt should read as.
    CIRCLE_FRACTION = 0.38
    # Art is inset inside its circle so the ring stays visible around it: a
    # picture fits the square inscribed in the disc. Emoji are drawn as TEXT, and
    # a glyph's em box is taller than the ink inside it, so they take their own
    # (larger) fraction to end up looking the same size as an image would.
    ART_FRACTION = 0.62
    EMOJI_FRACTION = 1.15

    def __init__(self, x, y, width, height, on_pick, pool=None):
        # (x, y, width, height): the pane region the belt owns -- in practice
        # everything below the typed field / controls, i.e. the space the score,
        # cleared-word list and dictionary count used before the belt took over.
        # on_pick(word): fires when a picture is clicked; the host pane fills its
        # typed field with `word`. pool: injected by tests; None builds one from
        # the configured deck.
        self._x = x
        self._y = y
        self._width = width
        self._height = height
        self._on_pick = on_pick
        # Read per instance, never in the class body -- class-level CONFIG reads
        # freeze at import, before a game mode's overrides are merged in.
        rules = CONFIG.get("rules", {})
        self._visible = max(1, int(rules.get("idea_belt.visible_items", 6)))
        self._offset = max(0, int(rules.get("idea_belt.window_offset", 15)))
        self._speed = float(rules.get("idea_belt.scroll_speed", 0.25))
        word_rules = {
            "rule_idea_word_hidden": False,
            "rule_idea_word_shown": True,
        }
        self._show_word = word_rules.get(
            rules.get("idea_belt.show_word", "rule_idea_word_hidden"), False)
        self._pool = pool if pool is not None else IdeaPool()

        # How far the belt has travelled, in ITEMS (fractional). Both windows read
        # it; it only ever increases.
        self._scroll = 0.0
        self._batch = pyglet.graphics.Batch()
        # Loaded picture files, keyed by filename (image art mode). Missing or
        # unreadable files land here as None so a broken name is retried once, not
        # every frame.
        self._images = {}

        # Geometry. One "band" is the vertical space one item occupies; the belt
        # shows `visible` of them per column, plus a spare slot at each end for the
        # items part-way in and part-way out of view.
        self._band = height / self._visible
        column_width = width / 2
        self._radius = min(self._band, column_width) * self.CIRCLE_FRACTION
        self._left_cx = x + column_width * 0.5
        self._right_cx = x + column_width * 1.5
        self._slot_count = self._visible + 2

        # Per-slot render objects, reused frame to frame: only their position and
        # (when the slot rolls onto a new ring item) their content change. Building
        # shapes every frame would churn the batch at 60fps for no gain.
        self._slots = []
        for _ in range(self._slot_count):
            self._slots.append(self._make_slot(self._left_cx))
            self._slots.append(self._make_slot(self._right_cx))
        self._layout()

    def _make_slot(self, cx):
        """One reusable belt position: the ring, its fill, the art and the optional
        word caption. `index` is the ring item currently shown (None = nothing yet),
        so _layout can skip re-setting art that has not changed."""
        circle = pyglet.shapes.Circle(
            cx, self._y, self._radius, color=self.CIRCLE_FILL,
            batch=self._batch, program=get_shape_shader())
        border = pyglet.shapes.Arc(
            cx, self._y, self._radius, thickness=max(1, self._radius * 0.06),
            color=self.CIRCLE_BORDER, batch=self._batch,
            program=get_shape_shader())
        emoji = pyglet.text.Label(
            "", font_name=EMOJI_FONTS, font_size=self._radius * self.EMOJI_FRACTION,
            x=cx, y=self._y, anchor_x="center", anchor_y="center",
            color=EMOJI_COLOR, batch=self._batch)
        word = pyglet.text.Label(
            "", font_size=max(8, self._radius * 0.34), x=cx, y=self._y,
            anchor_x="center", anchor_y="top",
            color=self.WORD_COLOR, batch=self._batch)
        return {"circle": circle, "border": border, "emoji": emoji,
                "word": word, "sprite": None, "index": None,
                "cx": cx, "cy": self._y, "shown": False}

    # --- motion ------------------------------------------------------------
    def update(self, dt):
        """Advance the belt by `idea_belt.scroll_speed` items per second and
        re-place every slot. Called from GameScreen's per-frame update while the
        pane that hosts the belt is on screen (and paused with the menu, like
        every other timed thing)."""
        self._scroll = self._scroll + self._speed * dt
        self._layout()

    def reset(self):
        """New game: deal a fresh ring and rewind the belt to its start."""
        self._pool = IdeaPool()
        self._scroll = 0.0
        self._layout()

    def _layout(self):
        """Place both windows for the current scroll position.

        Item `n` of the ring is at travel distance (scroll - n) from the bottom of
        the up column, one band per item. The down column reads the SAME distance
        but measures it from the top and looks `window_offset` items back along the
        ring -- which is what makes it the same conveyor, seen later."""
        for k, left_index, left_y, right_index, right_y in self.positions():
            self._place(self._slots[k * 2], left_index, left_y)
            self._place(self._slots[k * 2 + 1], right_index, right_y)

    def positions(self):
        """Where every slot sits this frame, as
        (slot, up_index, up_y, down_index, down_y) -- pure geometry, no drawing,
        so the belt's motion can be checked without a GL context."""
        placed = []
        base = math.floor(self._scroll) + 1
        for k in range(self._slot_count):
            n = base - k
            travel = self._scroll - n
            placed.append((k, n, self._y + travel * self._band,
                           n - self._offset,
                           self._y + self._height - travel * self._band))
        return placed

    def _place(self, slot, index, cy):
        """Move one slot to `cy`, showing ring item `index`. Slots whose band has
        run off either end of the region are hidden rather than drawn outside the
        pane (the spare slots at each end are always one of these)."""
        shown = (cy >= self._y and cy <= self._y + self._height
                 and self._pool.size() > 0)
        if shown != slot["shown"]:
            self._set_visible(slot, shown)
        if shown:
            self._set_opacity(slot, self._edge_opacity(cy))
            ring_index = index % self._pool.size()
            if ring_index != slot["index"]:
                slot["index"] = ring_index
                self._set_art(slot, self._pool.item_at(ring_index))
            slot["cy"] = cy
            slot["circle"].y = cy
            slot["border"].y = cy
            slot["emoji"].y = cy
            slot["word"].y = cy - self._radius * 1.05
            if slot["sprite"] is not None:
                slot["sprite"].y = cy

    def _edge_opacity(self, cy):
        """How solid an item at `cy` is: full inside the belt, fading to nothing at
        the region's two edges. The fade does two jobs -- it reads as the conveyor
        running away out of sight, and it means the half of a circle that hangs
        past an edge (over the buttons above, or the pane's bottom) is too faint to
        read as overlap. The alternative, culling on containment, would pop whole
        pictures in and out at full size."""
        edge = min(cy - self._y, self._y + self._height - cy)
        fade = self._radius * 2
        share = 1.0
        if edge < fade:
            share = max(0.0, edge / fade)
        return int(255 * share)

    def _set_opacity(self, slot, opacity):
        slot["circle"].opacity = opacity
        slot["border"].opacity = opacity
        slot["emoji"].opacity = opacity
        slot["word"].opacity = opacity
        if slot["sprite"] is not None:
            slot["sprite"].opacity = opacity

    def _set_visible(self, slot, shown):
        slot["shown"] = shown
        slot["circle"].visible = shown
        slot["border"].visible = shown
        slot["emoji"].visible = shown
        slot["word"].visible = shown
        if slot["sprite"] is not None:
            slot["sprite"].visible = shown

    def _set_art(self, slot, item):
        """Load the picture (and caption) for the item a slot just rolled onto.
        An item whose art is an image file draws as a sprite; everything else
        draws its emoji as text. A named image that will not load falls back to
        the emoji, so a bad filename costs one picture, not the belt."""
        image = None
        if item.image and item.art == item.image:
            image = self._load_image(item.image)
        if image is None:
            self._drop_sprite(slot)
            slot["emoji"].text = item.emoji
            slot["emoji"].visible = slot["shown"]
        else:
            slot["emoji"].text = ""
            self._set_sprite(slot, image)
        if self._show_word:
            slot["word"].text = item.word
        else:
            slot["word"].text = ""

    def _set_sprite(self, slot, image):
        if slot["sprite"] is None:
            slot["sprite"] = pyglet.sprite.Sprite(
                image, x=slot["cx"], y=slot["cy"], batch=self._batch)
            slot["sprite"].visible = slot["shown"]
        else:
            slot["sprite"].image = image
        sprite = slot["sprite"]
        # Fit the picture inside the circle, keeping its aspect ratio, and center
        # it on the slot (sprites anchor bottom-left).
        box = self._radius * 2 * self.ART_FRACTION
        sprite.scale = min(box / image.width, box / image.height)
        sprite.image.anchor_x = math.floor(image.width / 2)
        sprite.image.anchor_y = math.floor(image.height / 2)

    def _drop_sprite(self, slot):
        if slot["sprite"] is not None:
            slot["sprite"].delete()
            slot["sprite"] = None

    def _load_image(self, name):
        """Load (and cache) one picture file from assets/idea_belt/images/.
        Unreadable names cache as None so the failure is not retried per frame."""
        if name not in self._images:
            path = images_dir() / name
            try:
                self._images[name] = pyglet.image.load(str(path))
            except Exception:
                self._images[name] = None
        return self._images[name]

    # --- input -------------------------------------------------------------
    def item_at(self, x, y):
        """The belt item whose circle contains pixel (x, y), or None. Only visible
        slots are tested, so the spare off-region slots are never clickable."""
        hit = None
        for slot in self._slots:
            # Items still fading in/out at an edge are too faint to aim at, so they
            # are not clickable either -- a click there falls through to whatever is
            # behind the belt rather than typing a word the player could barely see.
            if (slot["shown"] and hit is None
                    and self._edge_opacity(slot["cy"]) > 60):
                dx = x - slot["cx"]
                dy = y - slot["cy"]
                if dx * dx + dy * dy <= self._radius * self._radius:
                    hit = self._pool.item_at(slot["index"])
        return hit

    def on_mouse_press(self, x, y):
        """Route a click at (x, y). Returns True when a picture was hit (the host
        pane then consumes the click), after handing its word to on_pick."""
        item = self.item_at(x, y)
        consumed = False
        if item is not None:
            L.log_20008(item.word, item.art)
            self._on_pick(item.word)
            consumed = True
        return consumed

    def draw(self):
        self._batch.draw()
