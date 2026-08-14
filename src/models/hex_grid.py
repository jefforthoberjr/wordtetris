import math
import pyglet
from models.grid_cell import GridCell
from models.gram import Gram, gram_font_size
from models.gram_text_color import cell_text_color
from models.hex_domino import hex_neighbor, HEX_UP_RIGHT, HEX_DOWN, HEX_DOWN_RIGHT
from models.hex_domino import HEX_UP, HEX_UP_LEFT, HEX_DOWN_LEFT
from views.shaders import get_shape_shader
from config import select_rule, get_color

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
_SNAKE_DIRS_ALL = (HEX_UP_RIGHT, HEX_UP, HEX_UP_LEFT, HEX_DOWN_LEFT, HEX_DOWN, HEX_DOWN_RIGHT)

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

def rule_snake_anydirection(prev_direction):
    """Snake in any of the six hex directions with no angle restriction: no
    left/right or up/down bias, any turn (60 or 120 deg) allowed. The only
    limit, no snaking backwards onto a cell already in the word path, can't be
    seen from a direction set alone, so it's enforced by the path-visited guard
    in the caller's word walk (game_screen._collect_hex_words)."""
    return _SNAKE_DIRS_ALL

# Which snake-direction the pathfinding walk may take, chosen by the YAML key
# hex_grid.word_pathfinding.
_SNAKE_RULES = {
    "rule_snake_rightanddown": rule_snake_rightanddown,
    "rule_snake_rightanddown_nosharptwist": rule_snake_rightanddown_nosharptwist,
    "rule_snake_straightline": rule_snake_straightline,
    "rule_snake_anydirection": rule_snake_anydirection,
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

        # Rule for which directions the pathfinding walk can take (_SNAKE_RULES).
        self._snake_rule = select_rule("hex_grid.word_pathfinding", _SNAKE_RULES)

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
        line_color = get_color("board.grid_line")
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

    def center_cell(self):
        """Center cell by cell count: as-equal-as-possible open cells left/right
        and above/below, off by one when a dimension is even. Every column holds
        the same number of cells, so the row count centers vertically too. The
        center spawn rule uses this so it adapts to any grid size."""
        cx = math.floor((self._cols - 1) / 2)
        cy = math.floor((self._rows - 1) / 2)
        return cx, cy

    @property
    def hex_size(self):
        return self._hex_size

    def cell_center(self, col, row):
        # Pixel center of a cell
        return self._rule_flattop_cell_center(col, row)

    def cell_vertices(self, col, row):
        """The corners of the SHAPE drawn at (col, row), in order -- the outline a
        bottom-up fill overlay clips against (see views/rising_fill.py). Every
        grid offers it; here it is the flat-top hexagon, through the same
        vertices rule the outlines and pieces use."""
        cx, cy = self.cell_visual_center(col, row)
        return self._rule_flattop_vertices(cx, cy)

    def cell_visual_center(self, col, row):
        """Center of the SHAPE drawn at (col, row) -- the same as cell_center
        here, since every hex cell is one coordinate. Overlays that must meet a
        cell in its visual middle (the word trail) use this instead of
        cell_center, so the triangle board's jumbo cells can differ. Every grid
        offers it."""
        return self.cell_center(col, row)

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
        """The (col, row) of the hex nearest pixel (px, py), or None if the point
        lies outside every cell. The offset hex layout has no tidy inverse, so
        this just keeps the closest cell center within one hex radius -- a click
        in a gap or off the board misses. The mouse controls use it to map a
        click to a grid cell."""
        best = None
        best_dist_sq = None
        limit_sq = self._hex_size * self._hex_size
        for row in range(self._rows):
            for col in range(self._cols):
                cx, cy = self.cell_center(col, row)
                offset_x = px - cx
                offset_y = py - cy
                dist_sq = offset_x * offset_x + offset_y * offset_y
                if dist_sq <= limit_sq:
                    if best_dist_sq is None or dist_sq < best_dist_sq:
                        best_dist_sq = dist_sq
                        best = (col, row)
        return best

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
        font as HexPiece (int(hex_size * SQRT3 * 0.5)), so the cell matches a
        freshly placed gram of that length. The cell stays on the board."""
        cell = self.get_cell(x, y)
        if cell is None or not cell.is_occupied():
            return
        gram = Gram(text)
        cell.gram = gram
        font_size = gram_font_size(int(self._hex_size * SQRT3 * 0.5), gram)
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
            nx, ny = hex_neighbor(x, y, direction)
            if self.is_valid(nx, ny):
                result.append(((nx, ny), direction))
        return result

    def neighbors(self, x, y):
        """Every on-board cell adjacent to (x, y): all six hex neighbors,
        independent of the word-walk snake rule (this is physical adjacency)."""
        result = []
        for direction in _SNAKE_DIRS_ALL:
            nx, ny = hex_neighbor(x, y, direction)
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
