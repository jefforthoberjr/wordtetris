import math
import pyglet
from models.gram import gram_font_size
from models.gram_picker import rule_random_letters
from models.gram_picker import rule_scrabble_distribution
from models.gram_picker import rule_englishcorpus_random_unigram
from models.gram_picker import rule_englishcorpus_random_digram
from models.gram_picker import rule_gramcorpus_distribution
from models.gram_picker import rule_mixed_scrabble_digram52
from models.gram_picker import rule_digram52_distribution
from models.gram_picker import rule_scrabble_with_allvowelswild
from models.hex_domino import HexDominoType, HEX_DOMINO_DIRECTIONS, hex_neighbor
from models.hex_unimo import HexUnimoType, HEX_UNIMO_DIRECTIONS
from models.hex_grid import SQRT3, flattop_cell_center, flattop_vertices
from views.shaders import get_shape_shader
from views.textures import wild_vowel_image
from config import select_rule, get_color


def _rule_use_hex_dominos():
    return HexDominoType, HEX_DOMINO_DIRECTIONS


def _rule_use_hex_unimos():
    return HexUnimoType, HEX_UNIMO_DIRECTIONS


# Which hex piece set to use (mirrors square_piece's pattern). The main pieces
# follow hex_piece.piece_set; the starting obstacles follow their own
# hex_obstacle.piece_set, so obstacles can be (say) unimos while the playable
# pieces are dominos.
_PIECE_SET_RULES = {
    "rule_use_hex_dominos": _rule_use_hex_dominos,
    "rule_use_hex_unimos": _rule_use_hex_unimos,
}
PIECE_TYPES, PIECE_DIRECTIONS = select_rule("hex_piece.piece_set", _PIECE_SET_RULES)()
OBSTACLE_PIECE_TYPES, _OBSTACLE_PIECE_DIRECTIONS = select_rule("hex_obstacle.piece_set", _PIECE_SET_RULES)()

# A piece looks up its satellite directions by piece_type alone. Merging every
# set's table (the type enums are distinct, so keys never collide) means one
# HexPiece class serves both the main set and a differently-configured obstacle set.
ALL_PIECE_DIRECTIONS = {}
ALL_PIECE_DIRECTIONS.update(HEX_DOMINO_DIRECTIONS)
ALL_PIECE_DIRECTIONS.update(HEX_UNIMO_DIRECTIONS)

# How each piece's grams are picked. The main pieces follow hex_piece.gram_pick;
# the starting obstacles follow their own hex_obstacle.gram_pick.
_GRAM_PICK_RULES = {
    "rule_random_letters": rule_random_letters,
    "rule_scrabble_distribution": rule_scrabble_distribution,
    "rule_englishcorpus_random_unigram": rule_englishcorpus_random_unigram,
    "rule_englishcorpus_random_digram": rule_englishcorpus_random_digram,
    "rule_gramcorpus_distribution": rule_gramcorpus_distribution,
    "rule_mixed_scrabble_digram52": rule_mixed_scrabble_digram52,
    "rule_digram52_distribution": rule_digram52_distribution,
    "rule_scrabble_with_allvowelswild": rule_scrabble_with_allvowelswild,
}
_gram_pick_rule = select_rule("hex_piece.gram_pick", _GRAM_PICK_RULES)
OBSTACLE_GRAM_PICK_RULE = select_rule("hex_obstacle.gram_pick", _GRAM_PICK_RULES)


class HexCellShape:
    """One bordered hex cell = a black outer hexagon behind a white inner one.

    The grid stores a single "shape" per cell and toggles its .visible (for
    hover/clear), so this wraps both polygons behind one .visible property,
    duck-typing as the cell's square. Setting border to 0 in HexPiece would
    recover the old borderless white-fill look.
    """
    def __init__(self, outer, inner):
        self._outer = outer
        self._inner = inner

    def _get_visible(self):
        return self._inner.visible

    def _set_visible(self, value):
        self._outer.visible = value
        self._inner.visible = value

    visible = property(_get_visible, _set_visible)

    def _get_color(self):
        return self._inner.color

    def _set_color(self, value):
        # The fill is the inner hexagon; the outer stays the border color. Lets
        # callers retint a cell via .color, matching the square BorderedRectangle.
        self._inner.color = value

    color = property(_get_color, _set_color)


class HexPiece:
    def __init__(self, piece_type, cell_size, batch, visible=False, gram_pick_rule=None, cell_color=None):
        self._piece_type = piece_type
        # 'cell_size' carries the hex size (float) so the piece aligns exactly
        # with HexGrid, which is built from the same value.
        self._hex_size = cell_size
        self._sat_dirs = list(ALL_PIECE_DIRECTIONS[piece_type])
        self._rotation_state = 0
        self._batch = batch
        self._grid_x = 0
        self._grid_y = 0
        self._visible = visible
        self._placed = False

        cell_count = 1 + len(self._sat_dirs)
        # Pools inject a gram-pick rule so obstacles can pick grams differently
        # from the main pieces; falling back to the configured default.
        if gram_pick_rule is None:
            gram_pick_rule = _gram_pick_rule
        self._grams = gram_pick_rule(cell_count)

        # Inner-hexagon fill color; pools tint obstacles differently from the
        # default playable pieces. None falls back to the configured cell fill.
        if cell_color is None:
            cell_color = get_color("board.cell_fill")
        border_color = get_color("board.cell_border")
        text_color = get_color("board.cell_text")

        shape_shader = get_shape_shader()
        # Base font for a single letter, sized to the hex height (sqrt(3)*size)
        # so the glyph clears the top/bottom hex edges; multi-letter grams shrink
        # to fit. The recenter nudge is per-label (below) since it scales with
        # each gram's font size.
        base_font_size = int(self._hex_size * SQRT3 * 0.5)

        # White fill + black border, like the square piece's BorderedRectangle.
        # The border is a black hexagon behind a slightly smaller white one.
        self._border = max(2.0, self._hex_size * 0.08)
        self._inner_size = self._hex_size - self._border

        # Hexagon vertices built around the origin; repositioned per cell in
        # _update_positions. A Polygon anchors at its first vertex (angle 0,
        # i.e. +radius on x), so centering a cell adds that radius to x.
        outer_verts = flattop_vertices(self._hex_size, 0, 0)
        inner_verts = flattop_vertices(self._inner_size, 0, 0)

        self._outers = []
        self._inners = []
        self._cell_shapes = []
        self._labels = []
        self._label_dys = []
        for i in range(cell_count):
            outer = pyglet.shapes.Polygon(
                *outer_verts,
                color=border_color,
                batch=batch,
                program=shape_shader
            )
            outer.visible = visible
            self._outers.append(outer)

            inner = pyglet.shapes.Polygon(
                *inner_verts,
                color=cell_color,
                batch=batch,
                program=shape_shader
            )
            inner.visible = visible
            self._inners.append(inner)

            self._cell_shapes.append(HexCellShape(outer, inner))

            # A wild-vowel gram renders as the vowel emblem sprite instead of a
            # letter label, sized to sit inside the hex; the _labels slot and the
            # per-label recenter nudge carry the sprite alongside text labels.
            gram = self._grams[i]
            if gram.is_wild:
                image = wild_vowel_image(math.floor(self._hex_size))
                label = pyglet.sprite.Sprite(image, batch=batch)
                label.scale = self._hex_size / image.height
                self._labels.append(label)
                self._label_dys.append(0)
            else:
                gram_font = gram_font_size(base_font_size, gram)
                label = pyglet.text.Label(
                    gram.text,
                    font_size=gram_font,
                    weight='bold',
                    color=text_color,
                    anchor_x="center",
                    anchor_y="center",
                    batch=batch
                )
                self._labels.append(label)
                # pyglet's anchor_y="center" centers the line box, not the glyph,
                # so capitals sit high (white space at the bottom). Nudge down to
                # recenter, scaled to this gram's own font size.
                self._label_dys.append(-math.floor(gram_font * 0.12))
            label.visible = visible

        self._update_positions()

    def _cell_grid_positions(self):
        positions = [(self._grid_x, self._grid_y)]
        for d in self._sat_dirs:
            positions.append(hex_neighbor(self._grid_x, self._grid_y, d))
        return positions

    def _update_positions(self):
        positions = self._cell_grid_positions()
        for i, (col, row) in enumerate(positions):
            cx, cy = flattop_cell_center(self._hex_size, col, row)
            # Each polygon anchors at its own first vertex (+radius on x).
            self._outers[i].position = (cx + self._hex_size, cy)
            self._inners[i].position = (cx + self._inner_size, cy)
            self._labels[i].x = cx
            self._labels[i].y = cy + self._label_dys[i]

    @property
    def piece_type(self):
        return self._piece_type

    @property
    def rotation_count(self):
        """Distinct rotation states: a hex piece cycles every 6 60-deg turns."""
        return 6

    @property
    def grid_x(self):
        return self._grid_x

    @property
    def grid_y(self):
        return self._grid_y

    def set_position(self, grid_x, grid_y):
        self._grid_x = grid_x
        self._grid_y = grid_y
        self._update_positions()

    def move(self, dx, dy):
        self._grid_x += dx
        self._grid_y += dy
        self._update_positions()

    def set_visible(self, visible):
        self._visible = visible
        for outer in self._outers:
            outer.visible = visible
        for inner in self._inners:
            inner.visible = visible
        for label in self._labels:
            label.visible = visible

    def rotate_cw(self):
        self._rotation_state = (self._rotation_state + 1) % 6
        rotated = []
        for d in self._sat_dirs:
            rotated.append((d + 1) % 6)
        self._sat_dirs = rotated
        self._update_positions()

    def rotate_ccw(self):
        self._rotation_state = (self._rotation_state - 1) % 6
        rotated = []
        for d in self._sat_dirs:
            rotated.append((d - 1) % 6)
        self._sat_dirs = rotated
        self._update_positions()

    @property
    def placed(self):
        return self._placed

    def place(self):
        self._placed = True

    def get_cell_positions(self):
        """Returns list of (grid_x, grid_y) for each cell in this piece."""
        return self._cell_grid_positions()

    def get_cell_data(self):
        """Returns list of (grid_x, grid_y, cell_shape, label, gram) for each
        cell.

        The cell_shape is the HexCellShape wrapper so the grid can toggle both
        the border and fill via one .visible (hover hide / clear). The gram
        travels along so the board can record what the placed cell holds.
        """
        data = []
        positions = self._cell_grid_positions()
        for i, (gx, gy) in enumerate(positions):
            data.append((gx, gy, self._cell_shapes[i], self._labels[i], self._grams[i]))
        return data
