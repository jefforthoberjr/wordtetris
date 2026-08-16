import math
import pyglet
from models.gram import Gram, gram_font_size
from models.gram_picker import rule_random_letters
from models.gram_picker import rule_scrabble_distribution
from models.gram_picker import rule_englishcorpus_random_unigram
from models.gram_picker import rule_englishcorpus_random_digram
from models.gram_picker import rule_grams_greater_than_47
from models.gram_picker import rule_grams_greater_than_47_lengthcontrolled
from models.gram_picker import rule_mixed_scrabble_digram52
from models.gram_picker import rule_digram52_distribution
from models.gram_picker import rule_trigram_equalweight
from models.gram_picker import rule_scrabble_with_allvowelswild
from models.gram_picker import pick_grams
from models.triangle_domino import (
    TriangleDominoType, TRIANGLE_DOMINO_DIRECTIONS,
    triangle_neighbor, triangle_points_up,
)
from models.triangle_unimo import TriangleUnimoType, TRIANGLE_UNIMO_DIRECTIONS
from models.triangle_hexagon import (
    TriangleHexagonType, TRIANGLE_HEXAGON_DIRECTIONS, TRIANGLE_HEXAGON_ROTATIONS,
)
from models.triangle_jumbo import (
    TriangleJumboType, TRIANGLE_JUMBO_DIRECTIONS,
    TRIANGLE_JUMBO_ROTATIONS, JUMBO_CELL_TYPES,
)
from models.triangle_grid import (
    SQRT3, triangle_cell_center, triangle_corner_offsets,
    triangle_inradius, triangle_base_font_size,
    jumbo_hex_center, jumbo_hex_corner_offsets, jumbo_hex_apothem,
)
from views.shaders import get_shape_shader
from views.textures import wild_vowel_image
from views.hunt_highlight import make_hunt_overlay
from models.gram_text_color import cell_text_color
from config import select_rule, get_color


def _rule_use_triangle_dominos():
    return TriangleDominoType, TRIANGLE_DOMINO_DIRECTIONS


def _rule_use_triangle_unimos():
    return TriangleUnimoType, TRIANGLE_UNIMO_DIRECTIONS


def _rule_use_triangle_hexagons():
    return TriangleHexagonType, TRIANGLE_HEXAGON_DIRECTIONS


def _rule_use_triangle_jumbos():
    """The hexagon JUMBO cell: the same six-triangle area as the hexagon piece,
    but ONE cell holding ONE gram (see triangle_jumbo)."""
    return TriangleJumboType, TRIANGLE_JUMBO_DIRECTIONS


def _rule_use_triangle_unimos_dominos_jumbos():
    """Ordinary small pieces mixed with the oversized hexagon cell -- the set that
    puts the size contrast in one pool: 1-cell triangles, 2-cell rhombi, and the
    six-coordinate single cell."""
    directions = {}
    directions.update(TRIANGLE_UNIMO_DIRECTIONS)
    directions.update(TRIANGLE_DOMINO_DIRECTIONS)
    directions.update(TRIANGLE_JUMBO_DIRECTIONS)
    return (TriangleUnimoType.SINGLE, TriangleDominoType.DOUBLE,
            TriangleJumboType.JUMBO_HEX), directions


def _rule_use_triangle_unimos_dominos_hexagons():
    """All three shapes in one pool: 1-cell triangles, 2-cell rhombi and 6-cell
    hexagons, mixed by the active piece_pool.order rule. Same explicit-members
    form as the unimo+domino rule below."""
    directions = {}
    directions.update(TRIANGLE_UNIMO_DIRECTIONS)
    directions.update(TRIANGLE_DOMINO_DIRECTIONS)
    directions.update(TRIANGLE_HEXAGON_DIRECTIONS)
    return (TriangleUnimoType.SINGLE, TriangleDominoType.DOUBLE,
            TriangleHexagonType.HEXAGON), directions


def _rule_use_triangle_unimos_and_dominos():
    """Both shapes in one pool: 1-cell triangles AND 2-cell rhombi, mixed by the
    active piece_pool.order rule.

    The other set rules return a single Enum CLASS (iterating it yields that set's
    members); this returns an explicit tuple of members drawn from two enums,
    which is all the pool needs -- it only ever does list(piece_types). Directions
    resolve through the merged ALL_PIECE_DIRECTIONS below, so no piece cares which
    enum its type came from."""
    directions = {}
    directions.update(TRIANGLE_UNIMO_DIRECTIONS)
    directions.update(TRIANGLE_DOMINO_DIRECTIONS)
    return (TriangleUnimoType.SINGLE, TriangleDominoType.DOUBLE), directions


# Which triangle piece set to use (mirrors hex_piece's pattern). The main (player)
# pieces follow triangle_player.piece_set; the starting obstacles follow their own
# triangle_obstacle.piece_set, so obstacles can be (say) unimos while the playable
# pieces are dominos.
_PIECE_SET_RULES = {
    "rule_use_triangle_dominos": _rule_use_triangle_dominos,
    "rule_use_triangle_unimos": _rule_use_triangle_unimos,
    "rule_use_triangle_unimos_and_dominos": _rule_use_triangle_unimos_and_dominos,
    "rule_use_triangle_hexagons": _rule_use_triangle_hexagons,
    "rule_use_triangle_unimos_dominos_hexagons": _rule_use_triangle_unimos_dominos_hexagons,
    "rule_use_triangle_jumbos": _rule_use_triangle_jumbos,
    "rule_use_triangle_unimos_dominos_jumbos": _rule_use_triangle_unimos_dominos_jumbos,
}
# Resolved per call (not cached at import) so a game mode's *.piece_set override
# takes effect: this module is imported before apply_game_mode swaps CONFIG, so an
# import-time binding would freeze the base config's rule (see apply_game_mode).
# Only the type enum is used downstream (directions come from ALL_PIECE_DIRECTIONS
# below), so each accessor returns just the [0] type table.
def player_piece_types():
    """Player piece-type enum for the active triangle_player.piece_set."""
    return select_rule("triangle_player.piece_set", _PIECE_SET_RULES)()[0]


def obstacle_piece_types():
    """Obstacle piece-type enum for the active triangle_obstacle.piece_set."""
    return select_rule("triangle_obstacle.piece_set", _PIECE_SET_RULES)()[0]


def mission_piece_types():
    """Mission piece-type enum (the light-red goal pieces) for the active
    triangle_mission.piece_set -- the direct parallel of the obstacles above."""
    return select_rule("triangle_mission.piece_set", _PIECE_SET_RULES)()[0]

# A piece looks up its satellite directions by piece_type alone. Merging every
# set's table (the type enums are distinct, so keys never collide) means one
# TrianglePiece class serves both the main set and a differently-configured
# obstacle set.
ALL_PIECE_DIRECTIONS = {}
ALL_PIECE_DIRECTIONS.update(TRIANGLE_DOMINO_DIRECTIONS)
ALL_PIECE_DIRECTIONS.update(TRIANGLE_UNIMO_DIRECTIONS)
ALL_PIECE_DIRECTIONS.update(TRIANGLE_HEXAGON_DIRECTIONS)
ALL_PIECE_DIRECTIONS.update(TRIANGLE_JUMBO_DIRECTIONS)

# Shapes whose rotation states must be LISTED rather than derived by cycling each
# satellite's direction index. Multi-step paths break under that derivation (see
# triangle_hexagon), so any shape here supplies its own per-state satellite lists;
# a shape absent from this table keeps the derived rotation.
ALL_PIECE_ROTATIONS = {}
ALL_PIECE_ROTATIONS.update(TRIANGLE_HEXAGON_ROTATIONS)
ALL_PIECE_ROTATIONS.update(TRIANGLE_JUMBO_ROTATIONS)

# How each piece's grams are picked. The main (player) pieces follow
# triangle_player.gram_pick; the starting obstacles follow their own
# triangle_obstacle.gram_pick.
_GRAM_PICK_RULES = {
    "rule_random_letters": rule_random_letters,
    "rule_scrabble_distribution": rule_scrabble_distribution,
    "rule_englishcorpus_random_unigram": rule_englishcorpus_random_unigram,
    "rule_englishcorpus_random_digram": rule_englishcorpus_random_digram,
    "rule_grams_greater_than_47": rule_grams_greater_than_47,
    "rule_grams_greater_than_47_lengthcontrolled": rule_grams_greater_than_47_lengthcontrolled,
    "rule_mixed_scrabble_digram52": rule_mixed_scrabble_digram52,
    "rule_digram52_distribution": rule_digram52_distribution,
    "rule_trigram_equalweight": rule_trigram_equalweight,
    "rule_scrabble_with_allvowelswild": rule_scrabble_with_allvowelswild,
}
# Resolved per call, same reason as the piece-set accessors above.
def player_gram_pick_rule():
    """Active triangle_player.gram_pick rule function (the TrianglePiece default)."""
    return select_rule("triangle_player.gram_pick", _GRAM_PICK_RULES)


def obstacle_gram_pick_rule():
    """Active triangle_obstacle.gram_pick rule function."""
    return select_rule("triangle_obstacle.gram_pick", _GRAM_PICK_RULES)


def mission_gram_pick_rule():
    """Active triangle_mission.gram_pick rule function."""
    return select_rule("triangle_mission.gram_pick", _GRAM_PICK_RULES)


def _as_path(satellite):
    """A satellite entry as a tuple of direction steps. Single ints (the
    unimo/domino form) read as a one-step walk, so callers never branch."""
    if isinstance(satellite, int):
        return (satellite,)
    return tuple(satellite)


class TriangleCellShape:
    """One bordered triangle cell = a black outer triangle behind a white inner
    one.

    The grid stores a single "shape" per cell and toggles its .visible (for
    hover/clear), so this wraps both triangles behind one .visible property,
    duck-typing as the cell's square -- the exact same contract HexCellShape
    provides. Setting border to 0 in TrianglePiece would recover a borderless
    white-fill look.
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
        # The fill is the inner triangle; the outer stays the border color. Lets
        # callers retint a cell via .color, matching the square BorderedRectangle.
        self._inner.color = value

    color = property(_get_color, _set_color)

    def _get_opacity(self):
        return self._inner.opacity

    def _set_opacity(self, value):
        # Fade both triangles together (0 = transparent, 255 = opaque) so a cell
        # dims/reveals as one. As with the hex cell, the LOADING reveal prefers
        # white-fading .inner and alpha-fading .outer separately (else the black
        # outer bleeds through a half-transparent inner as a gray interior);
        # kept for restore.
        self._outer.opacity = value
        self._inner.opacity = value

    opacity = property(_get_opacity, _set_opacity)

    @property
    def inner(self):
        """The white/colored fill triangle. The LOADING reveal white-fades this
        (held opaque, color lerped from white) so it masks the outer -- no gray
        interior. See views.loading_animation.WhiteFade."""
        return self._inner

    @property
    def outer(self):
        """The black border triangle. The LOADING reveal alpha-fades just its rim."""
        return self._outer


class TrianglePiece:
    def __init__(self, piece_type, cell_size, batch, visible=False, gram_pick_rule=None, cell_color=None, dedup_grams=True):
        self._piece_type = piece_type
        # 'cell_size' carries the triangle SIDE length (float) so the piece aligns
        # exactly with TriangleGrid, which is built from the same value.
        self._side = cell_size
        self._sat_dirs = list(ALL_PIECE_DIRECTIONS[piece_type])
        # Listed rotation states for shapes whose satellites are multi-step paths
        # (None = derive rotation by cycling each direction index). See
        # ALL_PIECE_ROTATIONS.
        self._rotations = ALL_PIECE_ROTATIONS.get(piece_type)
        self._rotation_state = 0
        self._batch = batch
        self._grid_x = 0
        self._grid_y = 0
        self._visible = visible
        self._placed = False

        # A JUMBO-cell piece covers the same coordinates as its small-piece twin
        # but is ONE cell holding ONE gram (see triangle_jumbo), so it draws one
        # oversized shape and picks a single gram no matter how many coordinates
        # its footprint spans.
        self._jumbo_cell = piece_type in JUMBO_CELL_TYPES
        if self._jumbo_cell:
            cell_count = 1
        else:
            cell_count = 1 + len(self._sat_dirs)
        # Pools inject a gram-pick rule so obstacles can pick grams differently
        # from the main pieces; falling back to the configured default.
        if gram_pick_rule is None:
            gram_pick_rule = player_gram_pick_rule()
        # Through pick_grams so the active gram.dedup rule (no-duplicate-multigram
        # toggle) applies to every piece, here and in the pools/formation.
        # dedup_grams=False bypasses it for player-chosen pieces (the word-piece
        # swap), whose gram is a deliberate fixed word.
        if dedup_grams:
            self._grams = pick_grams(gram_pick_rule, cell_count)
        else:
            self._grams = gram_pick_rule(cell_count)

        # Inner-triangle fill color; pools tint obstacles differently from the
        # default playable pieces. None falls back to the configured cell fill.
        if cell_color is None:
            cell_color = get_color("board.settled_cell_fill")
        border_color = get_color("board.cell_border")

        shape_shader = get_shape_shader()
        # Base font for a single letter. A triangle's usable room is its inscribed
        # circle -- far tighter than a hex's -- so the base comes from the shared
        # inradius helper (TriangleGrid.relabel_cell uses the same one, so a
        # relabeled cell matches a freshly placed gram). Multi-letter grams shrink
        # from here via the active gram.font_size rule.
        if self._jumbo_cell:
            # A hexagon cell's room is its apothem -- about three times a
            # triangle's inradius -- so its gram starts far bigger, and a
            # multigram (the length this cell is really meant to carry) still has
            # space after the gram.font_size rule shrinks it.
            base_font_size = int(jumbo_hex_apothem(self._side) * 0.8)
        else:
            base_font_size = triangle_base_font_size(self._side)
        # Kept so a LIVE (unplaced) cell can be re-fitted after its gram changes
        # under a right-click (see relabel_gram_at), exactly as it was sized here.
        self._base_font_size = base_font_size

        # White fill + black border, like the square piece's BorderedRectangle.
        # The border is a black shape behind a slightly smaller filled one.
        # Shrinking a triangle's side by `d` pulls each edge inward by
        # d/(2*sqrt(3)) (the inradius scales with the side), so a border of `b`
        # pixels needs the inner side reduced by b * 2 * sqrt(3).
        # A triangle's inradius is small, so the hex's 0.16 factor drew a border
        # that read far heavier than the hex one; 0.09 matches it by eye.
        self._border = max(2.0, triangle_inradius(self._side) * 0.09)
        self._inner_side = self._side - self._border * 2 * SQRT3
        # Jumbo cell: the same border weight converted for hexagon geometry (its
        # apothem is radius*sqrt(3)/2, so inset the radius by b * 2 / sqrt(3)).
        self._inner_radius = self._side - self._border * 2 / SQRT3

        self._outers = []
        self._inners = []
        self._cell_shapes = []
        self._labels = []
        # Optional hunt-highlight overlay per cell (None for wild); parallel to
        # _labels. See views/hunt_highlight.py.
        self._overlays = []
        self._label_dys = []
        for i in range(cell_count):
            if self._jumbo_cell:
                # One flat-top hexagon, built around the origin and repositioned
                # per move. Unlike a triangle its outline never changes shape --
                # the hexagon around a lattice vertex looks the same wherever it
                # sits -- so a Polygon that only moves is enough.
                outer = pyglet.shapes.Polygon(
                    *jumbo_hex_corner_offsets(self._side),
                    color=border_color,
                    batch=batch,
                    program=shape_shader
                )
            else:
                # Corner coordinates are rewritten every move (_update_positions),
                # so the placeholder geometry here only has to exist.
                outer = pyglet.shapes.Triangle(
                    0, 0, 0, 0, 0, 0,
                    color=border_color,
                    batch=batch,
                    program=shape_shader
                )
            outer.visible = visible
            self._outers.append(outer)

            if self._jumbo_cell:
                inner = pyglet.shapes.Polygon(
                    *jumbo_hex_corner_offsets(self._inner_radius),
                    color=cell_color,
                    batch=batch,
                    program=shape_shader
                )
            else:
                inner = pyglet.shapes.Triangle(
                    0, 0, 0, 0, 0, 0,
                    color=cell_color,
                    batch=batch,
                    program=shape_shader
                )
            inner.visible = visible
            self._inners.append(inner)

            self._cell_shapes.append(TriangleCellShape(outer, inner))

            # A wild-vowel gram renders as the vowel emblem sprite instead of a
            # letter label, sized to sit inside the triangle's inscribed circle;
            # the _labels slot and the per-label recenter nudge carry the sprite
            # alongside text labels.
            gram = self._grams[i]
            if gram.is_wild:
                if self._jumbo_cell:
                    emblem_size = max(1, math.floor(jumbo_hex_apothem(self._side) * 1.6))
                else:
                    emblem_size = max(1, math.floor(triangle_inradius(self._side) * 2))
                image = wild_vowel_image(emblem_size)
                label = pyglet.sprite.Sprite(image, batch=batch)
                label.scale = emblem_size / image.height
                self._labels.append(label)
                self._overlays.append(None)  # wild: sprite, hunts ignore it
                self._label_dys.append(0)
            else:
                gram_font = gram_font_size(base_font_size, gram)
                label = pyglet.text.Label(
                    gram.text,
                    font_size=gram_font,
                    weight='bold',
                    color=cell_text_color(gram),
                    anchor_x="center",
                    anchor_y="center",
                    batch=batch
                )
                self._labels.append(label)
                # Pre-built hunt-highlight overlay drawn on top of this label; it
                # inherits the recenter nudge below via set_position (copies the
                # base label's final y).
                self._overlays.append(make_hunt_overlay(gram.text, gram_font))
                # pyglet's anchor_y="center" centers the line box, not the glyph,
                # so capitals sit high (white space at the bottom). Nudge down to
                # recenter, scaled to this gram's own font size.
                self._label_dys.append(-math.floor(gram_font * 0.12))
            label.visible = visible

        self._update_positions()

    def _cell_grid_positions(self):
        """The anchor cell plus one cell per satellite.

        A satellite is a WALK from the anchor: a single direction index for the
        1-step shapes (unimo/domino), or a list of indices for shapes whose cells
        are further off (the hexagon). Walking rather than adding a fixed offset
        is what makes one table right at both parities -- each step re-reads the
        current cell's orientation (see triangle_neighbor)."""
        positions = [(self._grid_x, self._grid_y)]
        for satellite in self._sat_dirs:
            x, y = self._grid_x, self._grid_y
            for d in _as_path(satellite):
                x, y = triangle_neighbor(x, y, d)
            positions.append((x, y))
        return positions

    def _update_positions(self):
        if self._jumbo_cell:
            self._update_jumbo_cell_position()
            return
        positions = self._cell_grid_positions()
        for i, (col, row) in enumerate(positions):
            cx, cy = triangle_cell_center(self._side, col, row)
            # The cell's orientation follows the board's (col + row) checkerboard,
            # so a piece that moves one column over FLIPS point-up/point-down.
            # That is why the corners are rewritten here rather than the shape
            # merely repositioned (as the hex piece can do).
            points_up = triangle_points_up(col, row)
            self._set_triangle(self._outers[i], cx, cy, self._side, points_up)
            self._set_triangle(self._inners[i], cx, cy, self._inner_side, points_up)
            self._labels[i].x = cx
            self._labels[i].y = cy + self._label_dys[i]
            # Overlay tracks the base label's resolved position (incl. the nudge).
            if self._overlays[i] is not None:
                self._overlays[i].set_position(self._labels[i].x, self._labels[i].y)

    def _update_jumbo_cell_position(self):
        """Put the one oversized shape and its one gram on the center of the
        footprint -- the lattice vertex its six triangles meet at. A pyglet
        Polygon anchors at its FIRST vertex, which for these corner offsets sits
        at +radius on x (the same convention HexPiece uses)."""
        cx, cy = jumbo_hex_center(self._side, self._grid_x, self._grid_y)
        self._outers[0].position = (cx + self._side, cy)
        self._inners[0].position = (cx + self._inner_radius, cy)
        self._labels[0].x = cx
        self._labels[0].y = cy + self._label_dys[0]
        if self._overlays[0] is not None:
            self._overlays[0].set_position(self._labels[0].x, self._labels[0].y)

    def _set_triangle(self, shape, cx, cy, side, points_up):
        """Point a pyglet Triangle at the three corners of a cell centered on its
        centroid (cx, cy). Both the outer border and the smaller inner fill share
        the centroid, so the border comes out even on all three edges."""
        corners = triangle_corner_offsets(side, points_up)
        (x1, y1), (x2, y2), (x3, y3) = corners
        shape.x = cx + x1
        shape.y = cy + y1
        shape.x2 = cx + x2
        shape.y2 = cy + y2
        shape.x3 = cx + x3
        shape.y3 = cy + y3

    @property
    def piece_type(self):
        return self._piece_type

    @property
    def visible(self):
        """Whether this piece is currently shown (see SquarePiece.visible -- the
        hunt highlight uses it to skip a non-floating current piece)."""
        return self._visible

    @property
    def rotation_count(self):
        """Distinct rotation states: a triangle cell has only three edges, so a
        piece cycles every 3 turns (not 4 like the square, or 6 like the hex)."""
        return 3

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
        # A hidden (queued) piece shows no highlight; a shown piece leaves its
        # overlays to the hunt logic.
        if not visible:
            for overlay in self._overlays:
                if overlay is not None:
                    overlay.clear()

    def rotate_cw(self):
        """Turn the piece one edge clockwise: each satellite steps to the next of
        the three directions (right -> base -> left -> right).

        NOTE: on a point-DOWN anchor cell that index cycle runs visually
        counter-clockwise -- the direction indices are parity-free while the
        triangle's actual edges are not. A domino still visits all three of its
        possible rhombus orientations either way, so the piece behaves; if the
        turn direction ever feels wrong under the hand, flip the sign here per
        triangle_points_up(self._grid_x, self._grid_y).

        Shapes with LISTED rotation states (multi-step paths -- the hexagon) take
        their satellites straight from that table instead; deriving them would
        collapse the shape."""
        self._rotation_state = (self._rotation_state + 1) % 3
        self._apply_rotation(1)

    def rotate_ccw(self):
        self._rotation_state = (self._rotation_state - 1) % 3
        self._apply_rotation(-1)

    def _apply_rotation(self, step):
        """Re-point the satellites for the current _rotation_state: from the
        shape's listed states when it has them, else by turning each single-step
        direction index by `step`."""
        if self._rotations is not None:
            self._sat_dirs = list(self._rotations[self._rotation_state])
        else:
            rotated = []
            for d in self._sat_dirs:
                rotated.append((d + step) % 3)
            self._sat_dirs = rotated
        self._update_positions()

    @property
    def placed(self):
        return self._placed

    def place(self):
        self._placed = True

    @property
    def jumbo_cell(self):
        """True when this piece is ONE oversized cell rather than one cell per
        coordinate. The settle path checks it to route through
        TriangleGrid.place_jumbo instead of placing a cell per coordinate; every
        other caller can ignore it, because get_cell_positions still reports the
        full footprint (so overlap, spawn and hover checks work unchanged)."""
        return self._jumbo_cell

    def get_cell_positions(self):
        """Every (grid_x, grid_y) this piece covers. For a jumbo cell that is its
        whole footprint -- all six coordinates -- even though only one of them
        holds the gram, so overlap and on-board checks see the true area."""
        return self._cell_grid_positions()

    def cell_index_at(self, gx, gy):
        """Which of this piece's GRAMS sits at board coordinate (gx, gy), or None
        when the piece doesn't cover it. A JUMBO cell covers six coordinates but
        holds one gram, so every coordinate of it maps to index 0 (mirroring
        get_cell_data, which reports the jumbo as a single entry)."""
        positions = self._cell_grid_positions()
        if (gx, gy) not in positions:
            return None
        if self._jumbo_cell:
            return 0
        return positions.index((gx, gy))

    def relabel_gram_at(self, gx, gy, text):
        """Replace the gram of the cell covering (gx, gy) with `text` -- the LIVE
        (unplaced) piece's counterpart to TriangleGrid.relabel_cell, so right-click
        gram-manipulation can reach a piece before it is placed
        (game_screen.rightclicks_on_active_piece). Re-fits the label, its
        recenter nudge and its hunt overlay to the new length, from the same base
        font the constructor used, so the cell reads exactly like a piece that
        spawned with this gram. Returns True when a cell matched and was
        relabeled; False for a coordinate this piece doesn't cover, or a WILD cell
        (rendered as a sprite, with no letters to rewrite)."""
        i = self.cell_index_at(gx, gy)
        if i is None or self._grams[i].is_wild:
            return False
        gram = Gram(text)
        self._grams[i] = gram
        gram_font = gram_font_size(self._base_font_size, gram)
        label = self._labels[i]
        label.text = text
        label.font_size = gram_font
        # Recolor for the NEW gram: cell_text_color's gradient keys off gram
        # length, so a length change must re-derive the glyph color (same reason
        # the grid's relabel_cell does it).
        label.color = cell_text_color(gram)
        # The recenter nudge scales with the gram's own font size, so it has to be
        # recomputed here and re-applied by _update_positions below.
        self._label_dys[i] = -math.floor(gram_font * 0.12)
        if self._overlays[i] is not None:
            self._overlays[i].set_text(text, gram_font)
        self._update_positions()
        return True

    def get_cell_data(self):
        """Returns list of (grid_x, grid_y, cell_shape, label, gram, overlay) for
        each cell.

        The cell_shape is the TriangleCellShape wrapper so the grid can toggle
        both the border and fill via one .visible (hover hide / clear). The gram
        travels along so the board can record what the placed cell holds; the hunt
        overlay travels too so a settled cell stays highlightable (None if wild).

        A JUMBO cell returns exactly ONE entry -- its primary coordinate and its
        single gram -- however many coordinates it covers. Callers that place it
        must use place_jumbo with get_cell_positions() (see `jumbo_cell`), so the
        board records one cell owning the whole footprint.
        """
        data = []
        positions = self._cell_grid_positions()
        for i in range(len(self._grams)):
            gx, gy = positions[i]
            data.append((gx, gy, self._cell_shapes[i], self._labels[i],
                         self._grams[i], self._overlays[i]))
        return data
