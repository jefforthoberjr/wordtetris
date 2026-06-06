import math
import pyglet
from models.grid_cell import GridCell
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
    
    def is_occupied(self, x, y):
        cell = self.get_cell(x, y)
        if cell is None:
            return False
        return cell.is_occupied()
    
    def place(self, x, y, square, label):
        cell = self.get_cell(x, y)
        if cell is None:
            return False
        if cell.is_occupied():
            cell.clear()
        cell.set_contents(square, label)
        return True
    
    def clear_cell(self, x, y):
        cell = self.get_cell(x, y)
        if cell:
            cell.clear()

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

    def occupied_cells(self):
        """Coordinates of every occupied cell on the board."""
        cells = []
        for y in range(self._height):
            for x in range(self._width):
                if self._cells[y][x].is_occupied():
                    cells.append((x, y))
        return cells

    def letter_at(self, x, y):
        """Letter shown in a cell, or None if empty / off-board."""
        cell = self.get_cell(x, y)
        if cell is None or not cell.is_occupied() or cell.label is None:
            return None
        return cell.label.text

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
