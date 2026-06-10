import math
import pyglet
from config import get_color
from models.gram import Gram, gram_font_size
from views.textures import wild_vowel_image

SQRT3 = math.sqrt(3)


def parse_variation(variation):
    """Split an encoded player-dictionary variation into (shape, grams).

    shape is "hex" when the variation used the "/" separator, else "square".
    grams is an ordered list of (text, is_obstacle, is_wild): each gram's
    letters uppercased for display, whether it was wrapped in "[ ]" as an
    obstacle, and whether it was wrapped in "?...?" as a wild vowel (the obstacle
    bracket sits outside the wild marker, e.g. "[?ea?]"). A wild gram renders as
    the emblem, so its text is not shown -- but it is still parsed out.
    e.g. "ge|[ar]" -> ("square", [("GE", False, False), ("AR", True, False)])."""
    if "/" in variation:
        shape = "hex"
        separator = "/"
    else:
        shape = "square"
        separator = "|"
    grams = []
    for part in variation.split(separator):
        is_obstacle = part.startswith("[") and part.endswith("]")
        if is_obstacle:
            inner = part[1:-1]
        else:
            inner = part
        is_wild = inner.startswith("?") and inner.endswith("?")
        if is_wild:
            inner = inner[1:-1]
        grams.append((inner.upper(), is_obstacle, is_wild))
    return shape, grams


class GramPreview:
    """A single, movable re-render of one collected word's gram grouping, shown
    over a word on the dictionary screen while it is hovered.

    Only one word is ever previewed at a time, so this is one reusable element:
    show() rebuilds it over a new word, hide() blanks it, and the word's text
    Label underneath is never touched (an opaque backing rect occludes it). A
    "|" variation draws as bordered square boxes; a "/" variation draws point-up
    hexagons, mirroring the in-game cells but smaller. Fills/borders/text reuse
    the board.* colors, so a preview cell looks like its in-game counterpart;
    obstacle grams take the obstacle fill."""

    def __init__(self, cell_size, row_height):
        self._cell_size = cell_size
        self._row_height = row_height
        # A fresh batch is built per show(); kept here so draw() before the first
        # hover is harmless.
        self._batch = pyglet.graphics.Batch()
        # Holds the live shapes/labels so they aren't garbage-collected (which
        # would drop their vertex lists out of the batch).
        self._shapes = []
        self._visible = False
        self._cell_fill = get_color("board.cell_fill")
        self._obstacle_fill = get_color("board.obstacle_fill")
        self._border_color = get_color("board.cell_border")
        self._text_color = get_color("board.cell_text")
        self._backing_color = get_color("dictionary.background")

    def hide(self):
        self._visible = False

    def is_visible(self):
        return self._visible

    def show(self, variation, left_x, center_y, cover_width):
        """Rebuild the preview for `variation`, its row of cells starting at
        left_x and vertically centered on center_y (the visual middle of the word
        it replaces). cover_width is the width of the word's text, so the backing
        rect spans at least far enough to hide it. A brand-new batch is built each
        call so the previous cells are released; _shapes keeps the new ones."""
        shape, grams = parse_variation(variation)
        self._batch = pyglet.graphics.Batch()
        self._shapes = []
        if shape == "hex":
            row_width = self._hex_row_width(len(grams))
        else:
            row_width = len(grams) * self._cell_size
        self._build_backing(left_x, center_y, max(cover_width, row_width))
        if shape == "hex":
            self._build_hex_row(grams, left_x, center_y)
        else:
            self._build_square_row(grams, left_x, center_y)
        self._visible = True

    def _fill_for(self, is_obstacle):
        if is_obstacle:
            color = self._obstacle_fill
        else:
            color = self._cell_fill
        return color

    def _build_backing(self, left_x, center_y, width):
        # Opaque rect in the screen's background color, so the word's Label is
        # hidden behind the preview without the screen having to touch it.
        pad = math.floor(self._cell_size / 4)
        rect = pyglet.shapes.Rectangle(
            left_x - pad, center_y - math.floor(self._row_height / 2),
            width + 2 * pad, self._row_height,
            color=self._backing_color, batch=self._batch,
        )
        self._shapes.append(rect)

    def _label_base(self):
        return math.floor(self._cell_size * 0.6)

    def _add_label(self, text, cx, cy, font_size):
        label = pyglet.text.Label(
            text,
            font_size=font_size,
            weight="bold",
            x=cx, y=cy, anchor_x="center", anchor_y="center",
            color=self._text_color, batch=self._batch,
        )
        self._shapes.append(label)

    def _add_wild_sprite(self, cx, cy, target_height):
        # A wild cell re-renders as the vowel emblem (centered over the fill),
        # exactly as it looked in the game -- not as the letters it resolved to.
        image = wild_vowel_image(math.floor(target_height))
        sprite = pyglet.sprite.Sprite(image, batch=self._batch)
        sprite.scale = target_height / image.height
        sprite.x = cx
        sprite.y = cy
        self._shapes.append(sprite)

    def _build_square_row(self, grams, left_x, center_y):
        cell = self._cell_size
        bottom = center_y - math.floor(cell / 2)
        for i, (text, is_obstacle, is_wild) in enumerate(grams):
            x = left_x + i * cell
            rect = pyglet.shapes.BorderedRectangle(
                x, bottom, cell, cell, border=2,
                color=self._fill_for(is_obstacle),
                border_color=self._border_color, batch=self._batch,
            )
            self._shapes.append(rect)
            cx = x + math.floor(cell / 2)
            if is_wild:
                self._add_wild_sprite(cx, center_y, cell * 0.9)
            else:
                font_size = gram_font_size(self._label_base(), Gram(text))
                self._add_label(text, cx, center_y, font_size)

    def _hex_size(self):
        # Point-up hex sized so its height (2*size) matches the square box.
        return self._cell_size / 2

    def _hex_row_width(self, count):
        # A point-up hex has vertical left/right edges, so stepping centers by
        # exactly the hex width puts neighbours edge-to-edge (no gap).
        return count * SQRT3 * self._hex_size()

    def _build_hex_row(self, grams, left_x, center_y):
        # Point-up hexagons (a vertex straight up), laid left to right and spaced
        # by their full width so adjacent cells touch along their vertical edges.
        # Each cell is a black outer hexagon behind a slightly smaller fill
        # hexagon, matching the in-game hex cell.
        size = self._hex_size()
        border = max(2.0, size * 0.16)
        inner_size = size - border
        width = SQRT3 * size
        step = width
        for i, (text, is_obstacle, is_wild) in enumerate(grams):
            cx = left_x + math.floor(width / 2) + i * step
            outer = pyglet.shapes.Polygon(
                *self._hex_verts(size, cx, center_y),
                color=self._border_color, batch=self._batch,
            )
            self._shapes.append(outer)
            inner = pyglet.shapes.Polygon(
                *self._hex_verts(inner_size, cx, center_y),
                color=self._fill_for(is_obstacle), batch=self._batch,
            )
            self._shapes.append(inner)
            if is_wild:
                self._add_wild_sprite(cx, center_y, size)
            else:
                # A lone letter has the hex's narrower middle to itself; the
                # square base font overfills it, so trim single-letter grams
                # (digrams and longer already fit). Hex-only -- boxes are wider.
                font_size = gram_font_size(self._label_base(), Gram(text))
                if len(text) == 1:
                    font_size = math.floor(font_size * 0.7)
                self._add_label(text, cx, center_y, font_size)

    def _hex_verts(self, size, cx, cy):
        # Point-up: corners at 30, 90, ... degrees, so one vertex sits straight
        # up (and one straight down) -- the 30-degree rotation of the in-game
        # flat-top hexagon.
        verts = []
        for i in range(6):
            angle = math.radians(60 * i + 30)
            vx = cx + size * math.cos(angle)
            vy = cy + size * math.sin(angle)
            verts.append((vx, vy))
        return verts

    def draw(self):
        if self._visible:
            self._batch.draw()
