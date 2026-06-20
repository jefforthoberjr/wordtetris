import math
import pyglet
from models.grid_cell import GridCell
from models.gram import Gram, gram_font_size
from views.shaders import get_shape_shader
from config import get_color


class SquareGrid:
    def __init__(self, width, height, cell_size, window_width, window_height, batch):
        self._width = width
        self._height = height
        self._cell_size = cell_size
        self._cells = []
        for _ in range(height):
            row = []
            for _ in range(width):
                row.append(GridCell())
            self._cells.append(row)
        
        self._lines = []
        self._create_lines(window_width, window_height, batch)
    
    def _create_lines(self, window_width, window_height, batch):
        line_color = get_color("board.grid_line")
        shape_shader = get_shape_shader()
        
        for x in range(self._width + 1):
            px = x * self._cell_size
            line = pyglet.shapes.Line(
                px, 0, px, window_height,
                thickness=1, color=line_color, batch=batch,
                program=shape_shader
            )
            self._lines.append(line)
        
        for y in range(self._height + 1):
            py = y * self._cell_size
            line = pyglet.shapes.Line(
                0, py, window_width, py,
                thickness=1, color=line_color, batch=batch,
                program=shape_shader
            )
            self._lines.append(line)
    
    @property
    def width(self):
        return self._width
    
    @property
    def height(self):
        return self._height

    def center_cell(self):
        """Center cell by cell count: as-equal-as-possible open cells on each
        side, off by one when a dimension is even. The center spawn rule uses
        this so it adapts to any grid size."""
        cx = math.floor((self._width - 1) / 2)
        cy = math.floor((self._height - 1) / 2)
        return cx, cy

    def is_valid(self, x, y):
        return 0 <= x < self._width and 0 <= y < self._height
    
    def get_cell(self, x, y):
        if not self.is_valid(x, y):
            return None
        return self._cells[y][x]

    def line_shapes(self):
        """The grid-line shapes, so callers can restyle them as a group (e.g. the
        LOADING fade-in ramps their .opacity)."""
        return self._lines

    def cell_center(self, x, y):
        """Pixel center of cell (x, y) -- parallels HexGrid.cell_center, so the
        word trail can ask either grid for centers the same way."""
        return (x * self._cell_size + self._cell_size / 2,
                y * self._cell_size + self._cell_size / 2)

    def is_cell_occupied(self, x, y):
        cell = self.get_cell(x, y)
        if cell is None:
            return False
        return cell.is_occupied()

    def cell_at(self, px, py):
        """The (x, y) of the cell containing pixel (px, py), or None if the point
        is off the board. Cells tile from the origin, so this is a floor-divide;
        the mouse controls use it to map a click to a grid cell."""
        gx = math.floor(px / self._cell_size)
        gy = math.floor(py / self._cell_size)
        result = None
        if self.is_valid(gx, gy):
            result = (gx, gy)
        return result
    
    def place(self, x, y, square, label, gram=None):
        cell = self.get_cell(x, y)
        if cell is None:
            return False
        if cell.is_occupied():
            cell.clear()
        cell.set_contents(square, label, gram)
        return True
    
    def clear_cell(self, x, y):
        cell = self.get_cell(x, y)
        if cell:
            cell.clear()

    def relabel_cell(self, x, y, text):
        """Replace an occupied cell's gram with `text` (its leftover letters after
        a partial-gram clear), re-fitting the label to the new length. Same base
        font as SquarePiece (int(cell_size * 0.6)), so the cell looks identical to
        a freshly placed gram of that length. The cell stays on the board."""
        cell = self.get_cell(x, y)
        if cell is None or not cell.is_occupied():
            return
        gram = Gram(text)
        cell.gram = gram
        if cell.label is not None:
            cell.label.text = text
            cell.label.font_size = gram_font_size(int(self._cell_size * 0.6), gram)

    def forward_neighbors(self, x, y, prev_direction=None):
        """Cardinal neighbors of (x, y) for snaking words in any direction, with
        no diagonals. Matches the hex grid's forward_neighbors call shape so the
        same snaking word-walk serves both boards. prev_direction is accepted but
        ignored: the square grid imposes no turn restriction, so a word may bend
        any way; the walk's own path-visited guard is what stops it from snaking
        backwards onto a cell it already used."""
        steps = ((1, 0), (-1, 0), (0, 1), (0, -1))
        result = []
        for direction, (dx, dy) in enumerate(steps):
            nx, ny = x + dx, y + dy
            if self.is_valid(nx, ny):
                result.append(((nx, ny), direction))
        return result

    def neighbors(self, x, y):
        """Every on-board cell edge-adjacent to (x, y): the four cardinals (no
        diagonals), i.e. physical adjacency."""
        result = []
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if self.is_valid(nx, ny):
                result.append((nx, ny))
        return result

    def occupied_cells(self):
        """Coordinates of every occupied cell on the board."""
        cells = []
        for y in range(self._height):
            for x in range(self._width):
                if self._cells[y][x].is_occupied():
                    cells.append((x, y))
        return cells

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
        if cell is None or not cell.is_occupied() or cell.gram is None:
            return None
        if cell.gram.is_wild:
            return None
        return cell.gram.text

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
