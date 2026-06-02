import math
import pyglet
from models.grid_cell import GridCell
from views.shaders import get_shape_shader


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
        line_color = (200, 200, 200)
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

    def neighbors(self, x, y):
        """On-board coordinates adjacent to (x, y) on this square grid."""
        candidates = [(x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)]
        return [(nx, ny) for (nx, ny) in candidates if self.is_valid(nx, ny)]

    def letter_at(self, x, y):
        """Letter shown in a cell, or None if empty / off-board."""
        cell = self.get_cell(x, y)
        if cell is None or not cell.is_occupied() or cell.label is None:
            return None
        return cell.label.text

    def line_through(self, x, y, dx, dy):
        """Maximal run of occupied cells through (x, y) stepping by (dx, dy),
        returned in +(dx, dy) order. Empty if (x, y) is itself empty."""
        if self.letter_at(x, y) is None:
            return []
        sx, sy = x, y
        while self.letter_at(sx - dx, sy - dy) is not None:
            sx, sy = sx - dx, sy - dy
        cells = []
        while self.letter_at(sx, sy) is not None:
            cells.append((sx, sy))
            sx, sy = sx + dx, sy + dy
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
