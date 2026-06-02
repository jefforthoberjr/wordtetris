import math
import pyglet
from models.grid_cell import GridCell
from models.hex_domino import hex_neighbor, HEX_UP_RIGHT, HEX_DOWN, HEX_DOWN_RIGHT
from views.shaders import get_shape_shader
from config import select_rule

SQRT3 = math.sqrt(3)

# Flat-top geometry as free functions so HexPiece can share the exact same
# mapping as HexGrid (they must agree to the pixel, or pieces drift off cells).
def flattop_cell_center(hex_size, col, row):
    hex_height = SQRT3 * hex_size
    cx = hex_size + col * (1.5 * hex_size)
    odd_offset = (col % 2) * (hex_height / 2)
    cy = (hex_height / 2) + row * hex_height + odd_offset
    return cx, cy


def flattop_vertices(hex_size, cx, cy):
    # Flat-top corners sit at 0, 60, 120, ... degrees around the center.
    verts = []
    for i in range(6):
        angle = math.radians(60 * i)
        vx = cx + hex_size * math.cos(angle)
        vy = cy + hex_size * math.sin(angle)
        verts.append((vx, vy))
    return verts

_SNAKE_DIRS_DOWNANDRIGHT = (HEX_UP_RIGHT, HEX_DOWN, HEX_DOWN_RIGHT)

# Allow 60 deg turns; forbid 120 degree turns
_SHARP_TWISTS_DOWNANDRIGHT = {
    (HEX_UP_RIGHT, HEX_DOWN),
    (HEX_DOWN, HEX_UP_RIGHT),
}

# Snaking allow for turns and twists and zigzags; maybe more than just a straight line 

def rule_snake_rightanddown(prev_direction):
    return _SNAKE_DIRS_DOWNANDRIGHT

def rule_snake_rightanddown_nosharptwist(prev_direction):
    return tuple(
        d for d in _SNAKE_DIRS_DOWNANDRIGHT if (prev_direction, d) not in _SHARP_TWISTS_DOWNANDRIGHT
    )

def rule_snake_straightline(prev_direction):
    if prev_direction is None:
        return _SNAKE_DIRS_DOWNANDRIGHT
    return (prev_direction,)

# Which snake-direction rule a word can take, chosen by the YAML key hex_grid.snake.
_SNAKE_RULES = {
    "rule_snake_rightanddown": rule_snake_rightanddown,
    "rule_snake_rightanddown_nosharptwist": rule_snake_rightanddown_nosharptwist,
    "rule_snake_straightline": rule_snake_straightline,
}

class HexGrid:
    def __init__(self, hex_size, window_width, window_height, batch):
        self._hex_size = hex_size
        # flat-top hexagons
        self._hex_height = SQRT3 * hex_size
        self._hex_width = 2 * hex_size
        # adjacent columns step 3/4 of the full width horizontally
        self._col_spacing = 1.5 * hex_size

        self._cols = self._rule_flattop_col_count(window_width)
        self._rows = self._rule_flattop_row_count(window_height)

        self._cells = []
        #each col has the same number of cells
        #top and bottom "edges" of the grid are thus jagged
        #(the second col is a 1/2 step up from the first, then alternates up/down)
        #(if there is an even number of cols, the final col end up 1/2 step up from the first col)
        #   /-\_/-\_/-\_/-\  
        # /-\_/-\_/-\_/-\-/-\
        # ...
        #(the bottom edge has the opposite up/down jaggedness)
        
        for _ in range(self._rows):
            row = []
            for _ in range(self._cols):
                row.append(GridCell())
            self._cells.append(row)

        # Rule for which directions a word can take (see _SNAKE_RULES).
        self._snake_rule = select_rule("hex_grid.snake", _SNAKE_RULES)

        self._lines = []
        self._create_outlines(batch)

    # --- geometry rules (flat-top) -------------------------------------

    def _rule_flattop_col_count(self, window_width):
        # First column center sits one size in; each adds _col_spacing.
        usable = window_width - self._hex_width
        count = math.floor(usable / self._col_spacing) + 1
        return count

    def _rule_flattop_row_count(self, window_height):
        # Odd columns are nudged up half a hex, so reserve that half up top.
        usable = window_height - (self._hex_height / 2)
        count = math.floor(usable / self._hex_height)
        return count

    def _rule_flattop_cell_center(self, col, row):
        return flattop_cell_center(self._hex_size, col, row)

    def _rule_flattop_vertices(self, cx, cy):
        return flattop_vertices(self._hex_size, cx, cy)

    # --- rendering -----------------------------------------------------

    def _create_outlines(self, batch):
        # One full outline per cell. Shared edges are drawn twice; if the line
        # count ever bites us, dedupe shared edges here.
        line_color = (200, 200, 200)
        shape_shader = get_shape_shader()
        for row in range(self._rows):
            for col in range(self._cols):
                cx, cy = self._rule_flattop_cell_center(col, row)
                verts = self._rule_flattop_vertices(cx, cy)
                for i in range(6):
                    x1, y1 = verts[i]
                    x2, y2 = verts[(i + 1) % 6]
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
    def hex_size(self):
        return self._hex_size

    def cell_center(self, col, row):
        # Pixel center of a cell
        return self._rule_flattop_cell_center(col, row)

    def is_valid(self, x, y):
        return 0 <= x < self._cols and 0 <= y < self._rows

    def get_cell(self, x, y):
        cell = None
        if self.is_valid(x, y):
            cell = self._cells[y][x]
        return cell

    def is_cell_occupied(self, x, y):
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

    def neighbors(self, x, y):
        """On-board coordinates of the six cells adjacent to (x, y)."""
        result = []
        for direction in range(6):
            nx, ny = hex_neighbor(x, y, direction)
            if self.is_valid(nx, ny):
                result.append((nx, ny))
        return result

    def letter_at(self, x, y):
        """Letter shown in a cell, or None if empty / off-board."""
        cell = self.get_cell(x, y)
        letter = None
        if cell is not None and cell.is_occupied() and cell.label is not None:
            letter = cell.label.text
        return letter

    def forward_neighbors(self, x, y, prev_direction=None):
        result = []
        for direction in self._snake_rule(prev_direction):
            nx, ny = hex_neighbor(x, y, direction)
            if self.is_valid(nx, ny):
                result.append(((nx, ny), direction))
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
