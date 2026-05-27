import pyglet


class Block:
    def __init__(self, tetrimino_type, shapes_data, cell_size, batch, visible=False):
        self._tetrimino_type = tetrimino_type
        self._shapes_data = shapes_data
        self._cell_size = cell_size
        self._batch = batch
        self._grid_x = 0
        self._grid_y = 0
        self._visible = visible
        self._placed = False
        
        self._squares = []
        for _ in shapes_data:
            square = pyglet.shapes.BorderedRectangle(
                0, 0, cell_size, cell_size,
                border=2,
                color=(255, 255, 255),
                border_color=(0, 0, 0),
                batch=batch
            )
            square.visible = visible
            self._squares.append(square)
        
        self._update_positions()
    
    def _update_positions(self):
        for i, (dx, dy) in enumerate(self._shapes_data):
            px = (self._grid_x + dx) * self._cell_size
            py = (self._grid_y + dy) * self._cell_size
            self._squares[i].x = px
            self._squares[i].y = py
    
    @property
    def tetrimino_type(self):
        return self._tetrimino_type
    
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
        for square in self._squares:
            square.visible = visible
    
    def rotate_cw(self):
        # rotate 90 degrees clockwise
        new_shapes_data = []
        for dx, dy in self._shapes_data:
            new_shapes_data.append((dy, -dx))
        self._shapes_data = new_shapes_data
        self._update_positions()
    
    def rotate_ccw(self):
        # rotate 90 degrees counterclockwise
        new_shapes_data = []
        for dx, dy in self._shapes_data:
            new_shapes_data.append((-dy, dx))
        self._shapes_data = new_shapes_data
        self._update_positions()
    
    @property
    def placed(self):
        return self._placed
    
    def place(self):
        self._placed = True
