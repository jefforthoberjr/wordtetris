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
from models.hex_domino import HexDominoType, HEX_DOMINO_DIRECTIONS, hex_neighbor
from models.hex_unimo import HexUnimoType, HEX_UNIMO_DIRECTIONS
from models.hex_grid import SQRT3, flattop_cell_center, flattop_vertices
from views.shaders import get_shape_shader
from views.textures import wild_vowel_image
from views.hunt_highlight import make_hunt_overlay
from models.gram_text_color import cell_text_color
from config import select_rule, get_color


def _rule_use_hex_dominos():
    return HexDominoType, HEX_DOMINO_DIRECTIONS


def _rule_use_hex_unimos():
    return HexUnimoType, HEX_UNIMO_DIRECTIONS


# Which hex piece set to use (mirrors square_player's pattern). The main (player)
# pieces follow hex_player.piece_set; the starting obstacles follow their own
# hex_obstacle.piece_set, so obstacles can be (say) unimos while the playable
# pieces are dominos.
_PIECE_SET_RULES = {
    "rule_use_hex_dominos": _rule_use_hex_dominos,
    "rule_use_hex_unimos": _rule_use_hex_unimos,
}
# Resolved per call (not cached at import) so a game mode's *.piece_set override
# takes effect: this module is imported before apply_game_mode swaps CONFIG, so an
# import-time binding would freeze the base config's rule (see apply_game_mode).
# Only the type enum is used downstream (directions come from ALL_PIECE_DIRECTIONS
# below), so each accessor returns just the [0] type table.
def player_piece_types():
    """Player piece-type enum for the active hex_player.piece_set."""
    return select_rule("hex_player.piece_set", _PIECE_SET_RULES)()[0]


def obstacle_piece_types():
    """Obstacle piece-type enum for the active hex_obstacle.piece_set."""
    return select_rule("hex_obstacle.piece_set", _PIECE_SET_RULES)()[0]


def mission_piece_types():
    """Mission piece-type enum (the light-red goal pieces) for the active
    hex_mission.piece_set -- the direct parallel of the obstacles above."""
    return select_rule("hex_mission.piece_set", _PIECE_SET_RULES)()[0]

# A piece looks up its satellite directions by piece_type alone. Merging every
# set's table (the type enums are distinct, so keys never collide) means one
# HexPiece class serves both the main set and a differently-configured obstacle set.
ALL_PIECE_DIRECTIONS = {}
ALL_PIECE_DIRECTIONS.update(HEX_DOMINO_DIRECTIONS)
ALL_PIECE_DIRECTIONS.update(HEX_UNIMO_DIRECTIONS)

# How each piece's grams are picked. The main (player) pieces follow hex_player.gram_pick;
# the starting obstacles follow their own hex_obstacle.gram_pick.
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
    """Active hex_player.gram_pick rule function (the HexPiece default)."""
    return select_rule("hex_player.gram_pick", _GRAM_PICK_RULES)


def obstacle_gram_pick_rule():
    """Active hex_obstacle.gram_pick rule function."""
    return select_rule("hex_obstacle.gram_pick", _GRAM_PICK_RULES)


def mission_gram_pick_rule():
    """Active hex_mission.gram_pick rule function."""
    return select_rule("hex_mission.gram_pick", _GRAM_PICK_RULES)


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

    def _get_opacity(self):
        return self._inner.opacity

    def _set_opacity(self, value):
        # Fade both hexagons together (0 = transparent, 255 = opaque) so a cell
        # dims/reveals as one, matching the square BorderedRectangle's .opacity.
        # The original LOADING fade used this (alpha both halves); it caused the
        # black outer to bleed through the half-transparent inner as a gray cell
        # interior mid-fade. The reveal now white-fades the inner and alpha-fades
        # the outer separately (see .inner / .outer); kept for restore.
        self._outer.opacity = value
        self._inner.opacity = value

    opacity = property(_get_opacity, _set_opacity)

    @property
    def inner(self):
        """The white/colored fill hexagon. The LOADING reveal white-fades this
        (held opaque, color lerped from white) so it masks the outer -- no gray
        interior. See views.loading_animation.WhiteFade."""
        return self._inner

    @property
    def outer(self):
        """The black border hexagon. The LOADING reveal alpha-fades just its rim."""
        return self._outer


class HexPiece:
    def __init__(self, piece_type, cell_size, batch, visible=False, gram_pick_rule=None, cell_color=None, dedup_grams=True):
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
            gram_pick_rule = player_gram_pick_rule()
        # Through pick_grams so the active gram.dedup rule (no-duplicate-multigram
        # toggle) applies to every piece, here and in the pools/formation.
        # dedup_grams=False bypasses it for player-chosen pieces (the word-piece
        # swap), whose gram is a deliberate fixed word.
        if dedup_grams:
            self._grams = pick_grams(gram_pick_rule, cell_count)
        else:
            self._grams = gram_pick_rule(cell_count)

        # Inner-hexagon fill color; pools tint obstacles differently from the
        # default playable pieces. None falls back to the configured cell fill.
        if cell_color is None:
            cell_color = get_color("board.settled_cell_fill")
        border_color = get_color("board.cell_border")

        shape_shader = get_shape_shader()
        # Base font for a single letter, sized to the hex height (sqrt(3)*size)
        # so the glyph clears the top/bottom hex edges; multi-letter grams shrink
        # to fit. The recenter nudge is per-label (below) since it scales with
        # each gram's font size.
        base_font_size = int(self._hex_size * SQRT3 * 0.5)
        # Kept so a LIVE (unplaced) cell can be re-fitted after its gram changes
        # under a right-click (see relabel_gram_at), exactly as it was sized here.
        self._base_font_size = base_font_size

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
        # Optional hunt-highlight overlay per cell (None for wild); parallel to
        # _labels. See views/hunt_highlight.py.
        self._overlays = []
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
            # Overlay tracks the base label's resolved position (incl. the nudge).
            if self._overlays[i] is not None:
                self._overlays[i].set_position(self._labels[i].x, self._labels[i].y)

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
        # A hidden (queued) piece shows no highlight; a shown piece leaves its
        # overlays to the hunt logic.
        if not visible:
            for overlay in self._overlays:
                if overlay is not None:
                    overlay.clear()

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

    def cell_index_at(self, gx, gy):
        """Which of this piece's GRAMS sits at board coordinate (gx, gy), or None
        when the piece doesn't cover it. One gram per coordinate on this board
        (no jumbo cells here), so it is a plain position lookup."""
        positions = self._cell_grid_positions()
        if (gx, gy) not in positions:
            return None
        return positions.index((gx, gy))

    def relabel_gram_at(self, gx, gy, text):
        """Replace the gram of the cell at (gx, gy) with `text` -- the LIVE
        (unplaced) piece's counterpart to HexGrid.relabel_cell, so right-click
        gram-manipulation can reach a piece before it is placed
        (game_screen.rightclicks_on_active_piece). Re-fits the label, its
        recenter nudge and its hunt overlay to the new length, from the same base
        font the constructor used. Returns True when a cell matched and was
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
        # length, so a length change must re-derive the glyph color.
        label.color = cell_text_color(gram)
        # The recenter nudge scales with the gram's own font size.
        self._label_dys[i] = -math.floor(gram_font * 0.12)
        if self._overlays[i] is not None:
            self._overlays[i].set_text(text, gram_font)
        self._update_positions()
        return True

    def get_cell_data(self):
        """Returns list of (grid_x, grid_y, cell_shape, label, gram, overlay) for
        each cell.

        The cell_shape is the HexCellShape wrapper so the grid can toggle both
        the border and fill via one .visible (hover hide / clear). The gram
        travels along so the board can record what the placed cell holds; the hunt
        overlay travels too so a settled cell stays highlightable (None if wild).
        """
        data = []
        positions = self._cell_grid_positions()
        for i, (gx, gy) in enumerate(positions):
            data.append((gx, gy, self._cell_shapes[i], self._labels[i],
                         self._grams[i], self._overlays[i]))
        return data
