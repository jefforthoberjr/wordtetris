import pyglet
from models.letter_picker import pick_letters
from models.tetrimino import TETRIMINO_ROTATIONS
from views.shaders import get_shape_shader, get_text_shader


class Block:
    def __init__(self, tetrimino_type, shapes_data, cell_size, batch, visible=False):
        self._tetrimino_type = tetrimino_type
        self._shapes_data = list(shapes_data)
        self._rotation_state = 0
        self._cell_size = cell_size
        self._batch = batch
        self._grid_x = 0
        self._grid_y = 0
        self._visible = visible
        self._placed = False
        
        self._letters = pick_letters(len(shapes_data))
        
        shape_shader = get_shape_shader()
        
        self._squares = []
        self._labels = []
        font_size = int(cell_size * 0.6)
        
        for i, _ in enumerate(shapes_data):
            square = pyglet.shapes.BorderedRectangle(
                0, 0, cell_size, cell_size,
                border=2,
                color=(255, 255, 255),
                border_color=(0, 0, 0),
                batch=batch,
                program=shape_shader
            )
            square.visible = visible
            self._squares.append(square)
            
            label = pyglet.text.Label(
                self._letters[i],
                font_size=font_size,
                weight='bold',
                color=(0, 0, 0, 255),
                anchor_x="center",
                anchor_y="center",
                batch=batch
            )
            label.visible = visible
            self._labels.append(label)
        
        self._update_positions()
    
    def _update_positions(self):
        for i, (dx, dy) in enumerate(self._shapes_data):
            px = (self._grid_x + dx) * self._cell_size
            py = (self._grid_y + dy) * self._cell_size
            self._squares[i].x = px
            self._squares[i].y = py
            self._labels[i].x = px + self._cell_size // 2
            self._labels[i].y = py + self._cell_size // 2
    
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
        for label in self._labels:
            label.visible = visible
    
    def rotate_cw(self):
        # rotate 90 degrees clockwise using predefined rotation states
        rotations = TETRIMINO_ROTATIONS[self._tetrimino_type]
        self._rotation_state = (self._rotation_state + 1) % 4
        self._shapes_data = list(rotations[self._rotation_state])
        self._update_positions()
    
    def rotate_ccw(self):
        # rotate 90 degrees counterclockwise using predefined rotation states
        rotations = TETRIMINO_ROTATIONS[self._tetrimino_type]
        self._rotation_state = (self._rotation_state - 1) % 4
        self._shapes_data = list(rotations[self._rotation_state])
        self._update_positions()
    
    @property
    def placed(self):
        return self._placed
    
    def place(self):
        self._placed = True
    
    def get_cell_positions(self):
        """Returns list of (grid_x, grid_y) for each cell in this block."""
        positions = []
        for dx, dy in self._shapes_data:
            positions.append((self._grid_x + dx, self._grid_y + dy))
        return positions
    
    def get_cell_data(self):
        """Returns list of (grid_x, grid_y, square, label) for each cell."""
        data = []
        for i, (dx, dy) in enumerate(self._shapes_data):
            gx = self._grid_x + dx
            gy = self._grid_y + dy
            data.append((gx, gy, self._squares[i], self._labels[i]))
        return data
