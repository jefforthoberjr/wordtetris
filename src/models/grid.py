class GridCell:
    def __init__(self):
        self.square = None
        self.label = None
        self._hidden_by_hover = False
    
    def is_occupied(self):
        return self.square is not None
    
    def set_contents(self, square, label):
        self.square = square
        self.label = label
        self._hidden_by_hover = False
        if square:
            square.visible = True
        if label:
            label.visible = True
    
    def clear(self):
        if self.square:
            self.square.visible = False
        if self.label:
            self.label.visible = False
        self.square = None
        self.label = None
        self._hidden_by_hover = False
    
    def hide_for_hover(self):
        if self.is_occupied() and not self._hidden_by_hover:
            self._hidden_by_hover = True
            self.square.visible = False
            self.label.visible = False
    
    def restore_from_hover(self):
        if self.is_occupied() and self._hidden_by_hover:
            self._hidden_by_hover = False
            self.square.visible = True
            self.label.visible = True


class Grid:
    def __init__(self, width, height):
        self._width = width
        self._height = height
        self._cells = []
        for _ in range(height):
            row = []
            for _ in range(width):
                row.append(GridCell())
            self._cells.append(row)
    
    @property
    def width(self):
        return self._width
    
    @property
    def height(self):
        return self._height
    
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
