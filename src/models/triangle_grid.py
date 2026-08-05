import math
import pyglet
from models.grid_cell import GridCell
from models.gram import Gram, gram_font_size
from models.gram_text_color import cell_text_color
from models.triangle_domino import (
    triangle_neighbor,
    triangle_points_up,
    TRIANGLE_ALL_DIRECTIONS,
)
from views.shaders import get_shape_shader
from config import select_rule, get_color

SQRT3 = math.sqrt(3)

# Equilateral-triangle geometry as free functions so TrianglePiece can share the
# exact same mapping as TriangleGrid (they must agree to the pixel, or pieces
# drift off cells) -- the same split hex_grid uses for its flat-top helpers.
#
# `side` is the triangle's edge length; all three edges are equal. Row `row`
# occupies the horizontal band [row * height, (row + 1) * height], and every cell
# in it spans x from col * (side / 2) to col * (side / 2) + side, so consecutive
# columns overlap by half a triangle and share a slanted edge.

def triangle_row_height(side):
    return side * SQRT3 / 2


def triangle_cell_center(side, col, row):
    """The triangle's CENTROID (the point its label sits on). An up-pointing
    triangle's centroid is a third of the way up from its base; a down-pointing
    one's is a third down from its top edge, i.e. two thirds up the band."""
    height = triangle_row_height(side)
    cx = col * (side / 2) + (side / 2)
    if triangle_points_up(col, row):
        cy = row * height + height / 3
    else:
        cy = row * height + 2 * height / 3
    return cx, cy


def triangle_corner_offsets(side, points_up):
    """The three corners of a triangle relative to its centroid. Used both for
    the grid outlines (offset from the cell center) and for the piece's polygons,
    which are built around the origin and then repositioned per cell."""
    height = triangle_row_height(side)
    half = side / 2
    if points_up:
        # Apex up: centroid sits height/3 above the base.
        return [
            (-half, -height / 3),
            (half, -height / 3),
            (0.0, 2 * height / 3),
        ]
    # Apex down: centroid sits height/3 below the top edge.
    return [
        (-half, height / 3),
        (half, height / 3),
        (0.0, -2 * height / 3),
    ]


def triangle_vertices(side, col, row):
    """Absolute pixel corners of cell (col, row)."""
    cx, cy = triangle_cell_center(side, col, row)
    offsets = triangle_corner_offsets(side, triangle_points_up(col, row))
    return [(cx + dx, cy + dy) for dx, dy in offsets]


def triangle_inradius(side):
    """Radius of the inscribed circle -- the usable room for a cell's glyph, and
    the basis for converting a pixel border width into a smaller inner triangle."""
    return side / (2 * SQRT3)


def rule_snake_edges_anydirection(prev_direction):
    """Snake through a triangle's three edge-neighbors with no turn restriction.
    A triangle has only three edges, so this is the full physical-adjacency set:
    left, right, and the cell across the horizontal edge. Vertex-adjacency (the
    twelve cells touching a corner) is deliberately NOT offered -- word paths stay
    edge-connected. The only limit, no snaking backwards onto a cell already in
    the word path, can't be seen from a direction set alone, so it's enforced by
    the path-visited guard in the caller's word walk."""
    return TRIANGLE_ALL_DIRECTIONS


# Which snake-direction the pathfinding walk may take, chosen by the YAML key
# triangle_grid.word_pathfinding.
_SNAKE_RULES = {
    "rule_snake_edges_anydirection": rule_snake_edges_anydirection,
}


class TriangleGrid:
    def __init__(self, side, window_width, window_height, batch):
        self._side = side
        self._row_height = triangle_row_height(side)

        self._cols = self._rule_triangle_col_count(window_width)
        self._rows = self._rule_triangle_row_count(window_height)

        self._cells = []
        # Every row holds the same number of cells. Within a row the triangles
        # alternate point-up / point-down, and each row starts with the opposite
        # orientation from the one below it, so the whole board is a checkerboard
        # keyed by (col + row) parity:
        #   \/\/\/\/\/
        #   /\/\/\/\/\
        # The left and right edges are thus jagged (half a triangle of unused
        # space alternating down the side), like the hex board's jagged top.
        for _ in range(self._rows):
            row = []
            for _ in range(self._cols):
                row.append(GridCell())
            self._cells.append(row)

        # Rule for which directions the pathfinding walk can take (_SNAKE_RULES).
        self._snake_rule = select_rule("triangle_grid.word_pathfinding", _SNAKE_RULES)

        self._lines = []
        self._create_outlines(batch)

    # --- geometry rules -------------------------------------------------

    def _rule_triangle_col_count(self, window_width):
        # Cell `col` ends at col * (side/2) + side, so the last column that fits
        # is floor((width - side) / (side/2)).
        usable = window_width - self._side
        count = math.floor(usable / (self._side / 2)) + 1
        return max(count, 1)

    def _rule_triangle_row_count(self, window_height):
        return max(math.floor(window_height / self._row_height), 1)

    def _rule_triangle_cell_center(self, col, row):
        return triangle_cell_center(self._side, col, row)

    def _rule_triangle_vertices(self, col, row):
        return triangle_vertices(self._side, col, row)

    # --- rendering -----------------------------------------------------

    def _create_outlines(self, batch):
        # One full outline per cell. Shared edges are drawn twice; if the line
        # count ever bites us, dedupe shared edges here (same note as HexGrid).
        line_color = get_color("board.grid_line")
        shape_shader = get_shape_shader()
        for row in range(self._rows):
            for col in range(self._cols):
                verts = self._rule_triangle_vertices(col, row)
                for i in range(3):
                    x1, y1 = verts[i]
                    x2, y2 = verts[(i + 1) % 3]
                    line = pyglet.shapes.Line(
                        x1, y1, x2, y2,
                        thickness=1, color=line_color, batch=batch,
                        program=shape_shader
                    )
                    self._lines.append(line)

    @property
    def width(self):
        return self._cols

    @property
    def height(self):
        return self._rows

    @property
    def side(self):
        """The triangle edge length this board was built from. TrianglePiece must
        be constructed with the same value or pieces drift off the cells."""
        return self._side

    def center_cell(self):
        """Center cell by cell count: as-equal-as-possible open cells left/right
        and above/below, off by one when a dimension is even. Every row holds the
        same number of cells, so the row count centers vertically too. The center
        spawn rule uses this so it adapts to any grid size."""
        cx = math.floor((self._cols - 1) / 2)
        cy = math.floor((self._rows - 1) / 2)
        return cx, cy

    def cell_center(self, col, row):
        # Pixel center (centroid) of a cell.
        return self._rule_triangle_cell_center(col, row)

    def is_valid(self, x, y):
        return 0 <= x < self._cols and 0 <= y < self._rows

    def get_cell(self, x, y):
        cell = None
        if self.is_valid(x, y):
            cell = self._cells[y][x]
        return cell

    def line_shapes(self):
        """The grid-outline shapes, so callers can restyle them as a group (e.g.
        the LOADING fade-in ramps their .opacity)."""
        return self._lines

    def is_cell_occupied(self, x, y):
        cell = self.get_cell(x, y)
        result = False
        if cell is not None:
            result = cell.is_occupied()
        return result

    def cell_at(self, px, py):
        """The (col, row) of the triangle containing pixel (px, py), or None if
        the point lies off the board. Rows tile exactly, so the row is a
        floor-divide; within the row only two columns can overlap the point, so
        this tests those candidates with a point-in-triangle check. The mouse
        controls use it to map a click to a grid cell."""
        row = math.floor(py / self._row_height)
        # px sits in the half-triangle strip `strip`; only the columns whose span
        # covers that strip can contain the point.
        strip = math.floor(px / (self._side / 2))
        result = None
        for col in (strip - 1, strip):
            if self.is_valid(col, row) and self._point_in_cell(px, py, col, row):
                result = (col, row)
                break
        return result

    def _point_in_cell(self, px, py, col, row):
        """Point-in-triangle by edge sign: the point is inside when it lies on the
        same side of all three edges (walked in a consistent winding)."""
        verts = self._rule_triangle_vertices(col, row)
        negative = False
        positive = False
        for i in range(3):
            x1, y1 = verts[i]
            x2, y2 = verts[(i + 1) % 3]
            cross = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)
            if cross < 0:
                negative = True
            elif cross > 0:
                positive = True
        return not (negative and positive)

    def place(self, x, y, square, label, gram=None, overlay=None):
        cell = self.get_cell(x, y)
        result = False
        if cell is not None:
            if cell.is_occupied():
                cell.clear()
            cell.set_contents(square, label, gram, overlay)
            result = True
        return result

    def clear_cell(self, x, y):
        cell = self.get_cell(x, y)
        if cell:
            cell.clear()

    def relabel_cell(self, x, y, text):
        """Replace an occupied cell's gram with `text` (its leftover letters after
        a partial-gram clear), re-fitting the label to the new length. Same base
        font as TrianglePiece (the inradius-derived size), so the cell matches a
        freshly placed gram of that length. The cell stays on the board."""
        cell = self.get_cell(x, y)
        if cell is None or not cell.is_occupied():
            return
        gram = Gram(text)
        cell.gram = gram
        font_size = gram_font_size(triangle_base_font_size(self._side), gram)
        if cell.label is not None:
            cell.label.text = text
            cell.label.font_size = font_size
            # Recolor for the NEW gram: the board.cell_text_color score-gradient
            # keys off gram length, so a relabel/swap that changes the letters
            # must re-derive the glyph color or the old color stays on the cell
            # while its letters move away.
            cell.label.color = cell_text_color(gram)
        # Keep the hunt overlay's baked text in sync with the relabeled gram, else
        # a highlight would paint the OLD letters. GameScreen re-lights after.
        if cell.overlay is not None:
            cell.overlay.set_text(text, font_size)

    def gram_at(self, x, y):
        """The Gram a cell holds (its letters, or a wild vowel), or None if the
        cell is empty / off-board. Word-finding uses this to expand wild cells,
        which letter_at hides, and presence checks use it to count wild cells as
        occupied."""
        cell = self.get_cell(x, y)
        result = None
        if cell is not None and cell.is_occupied():
            result = cell.gram
        return result

    def letter_at(self, x, y):
        """Letters a cell contributes when spelling a word, or None if empty,
        off-board, or a wild vowel (whose 1-3 letter run is resolved separately;
        the plain-letter walk treats it as having no fixed letters)."""
        cell = self.get_cell(x, y)
        letter = None
        if cell is not None and cell.is_occupied() and cell.gram is not None:
            if not cell.gram.is_wild:
                letter = cell.gram.text
        return letter

    def forward_neighbors(self, x, y, prev_direction=None):
        result = []
        for direction in self._snake_rule(prev_direction):
            nx, ny = triangle_neighbor(x, y, direction)
            if self.is_valid(nx, ny):
                result.append(((nx, ny), direction))
        return result

    def neighbors(self, x, y):
        """Every on-board cell adjacent to (x, y): the three edge-neighbors,
        independent of the word-walk snake rule (this is physical adjacency).
        Cells that only touch at a corner are NOT neighbors."""
        result = []
        for direction in TRIANGLE_ALL_DIRECTIONS:
            nx, ny = triangle_neighbor(x, y, direction)
            if self.is_valid(nx, ny):
                result.append((nx, ny))
        return result

    def occupied_cells(self):
        """Coordinates of every occupied cell on the board."""
        cells = []
        for y in range(self._rows):
            for x in range(self._cols):
                if self._cells[y][x].is_occupied():
                    cells.append((x, y))
        return cells

    def hide_cells_for_hover(self, positions):
        for x, y in positions:
            cell = self.get_cell(x, y)
            if cell:
                cell.hide_for_hover()

    def restore_cells_from_hover(self, positions):
        for x, y in positions:
            cell = self.get_cell(x, y)
            if cell:
                cell.restore_from_hover()


def triangle_base_font_size(side):
    """Font size a SINGLE letter uses in a triangle cell. A triangle's usable room
    is its inscribed circle, much smaller than a hex's, so the base is derived
    from the inradius rather than the cell height; multi-letter grams then shrink
    from here via the active gram.font_size rule. Shared by TriangleGrid.relabel
    and TrianglePiece so a relabeled cell matches a freshly placed one.

    The factor is the tuning knob for how full a cell its letter sits: a glyph is
    taller than it is wide, and only the inscribed circle is clear of all three
    edges, so 1.6x (the value a hex-sized guess suggested) had letters touching
    the slanted sides. 1.25x leaves a visible margin at every edge."""
    return int(triangle_inradius(side) * 1.25)
