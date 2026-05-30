import math
import pyglet
from models.grid import GridCell
from views.shaders import get_shape_shader


# Flat-top hexagon grid. Mirrors the public interface of models.grid.Grid
# (duck typing) so GameScreen can use either board by swapping one line.
#
# Geometry lives in the _rule_flat_top_* methods below. To add a pointy-top
# variant later, write sibling _rule_pointy_top_* methods and repoint the
# calls in __init__ / _create_outlines -- that is the single swap point.
SQRT3 = math.sqrt(3)


# Flat-top geometry as free functions so HexPiece can share the exact same
# mapping as HexGrid (they must agree to the pixel, or pieces drift off cells).
def flat_top_cell_center(hex_size, col, row):
    hex_height = SQRT3 * hex_size
    cx = hex_size + col * (1.5 * hex_size)
    odd_offset = (col % 2) * (hex_height / 2)
    cy = (hex_height / 2) + row * hex_height + odd_offset
    return cx, cy


def flat_top_vertices(hex_size, cx, cy):
    # Flat-top corners sit at 0, 60, 120, ... degrees around the center.
    verts = []
    for i in range(6):
        angle = math.radians(60 * i)
        vx = cx + hex_size * math.cos(angle)
        vy = cy + hex_size * math.sin(angle)
        verts.append((vx, vy))
    return verts


class HexGrid:
    def __init__(self, hex_size, window_width, window_height, batch):
        self._hex_size = hex_size
        # flat-top: corner-to-corner height is sqrt(3)*size, width is 2*size
        self._hex_height = SQRT3 * hex_size
        self._hex_width = 2 * hex_size
        # adjacent columns step 3/4 of the full width horizontally
        self._col_spacing = 1.5 * hex_size

        self._cols = self._rule_flat_top_col_count(window_width)
        self._rows = self._rule_flat_top_row_count(window_height)

        self._cells = []
        for _ in range(self._rows):
            row = []
            for _ in range(self._cols):
                row.append(GridCell())
            self._cells.append(row)

        self._lines = []
        self._create_outlines(batch)

    # --- geometry rules (flat-top) -------------------------------------

    def _rule_flat_top_col_count(self, window_width):
        # First column center sits one size in; each adds _col_spacing.
        usable = window_width - self._hex_width
        count = math.floor(usable / self._col_spacing) + 1
        return count

    def _rule_flat_top_row_count(self, window_height):
        # Odd columns are nudged up half a hex, so reserve that half up top.
        usable = window_height - (self._hex_height / 2)
        count = math.floor(usable / self._hex_height)
        return count

    def _rule_flat_top_cell_center(self, col, row):
        return flat_top_cell_center(self._hex_size, col, row)

    def _rule_flat_top_vertices(self, cx, cy):
        return flat_top_vertices(self._hex_size, cx, cy)

    # --- rendering -----------------------------------------------------

    def _create_outlines(self, batch):
        # One full outline per cell. Shared edges are drawn twice; if the line
        # count ever bites us, dedupe shared edges here.
        line_color = (200, 200, 200)
        shape_shader = get_shape_shader()
        for row in range(self._rows):
            for col in range(self._cols):
                cx, cy = self._rule_flat_top_cell_center(col, row)
                verts = self._rule_flat_top_vertices(cx, cy)
                for i in range(6):
                    x1, y1 = verts[i]
                    x2, y2 = verts[(i + 1) % 6]
                    line = pyglet.shapes.Line(
                        x1, y1, x2, y2,
                        thickness=1, color=line_color, batch=batch,
                        program=shape_shader
                    )
                    self._lines.append(line)

    # --- public interface (mirrors Grid) -------------------------------

    @property
    def width(self):
        return self._cols

    @property
    def height(self):
        return self._rows

    @property
    def hex_size(self):
        return self._hex_size

    def cell_center(self, col, row):
        # Pixel center of a cell; HexPiece will need this in Task 2.
        return self._rule_flat_top_cell_center(col, row)

    def is_valid(self, x, y):
        return 0 <= x < self._cols and 0 <= y < self._rows

    def get_cell(self, x, y):
        cell = None
        if self.is_valid(x, y):
            cell = self._cells[y][x]
        return cell

    def is_occupied(self, x, y):
        cell = self.get_cell(x, y)
        result = False
        if cell is not None:
            result = cell.is_occupied()
        return result

    def place(self, x, y, square, label):
        cell = self.get_cell(x, y)
        result = False
        if cell is not None:
            if cell.is_occupied():
                cell.clear()
            cell.set_contents(square, label)
            result = True
        return result

    def clear_cell(self, x, y):
        cell = self.get_cell(x, y)
        if cell:
            cell.clear()

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
