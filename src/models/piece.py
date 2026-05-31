import math
import pyglet
from models.gram import gram_font_size
from models.gram_picker import rule_random_letters
from models.gram_picker import rule_scrabble_distribution
from models.gram_picker import rule_englishcorpus_random_unigram
from models.gram_picker import rule_englishcorpus_random_digram
from models.gram_picker import rule_gramcorpus_distribution
from models.tetrimino import TetriminoType, TETRIMINO_ROTATIONS
from models.domino import DominoType, DOMINO_ROTATIONS
from views.shaders import get_shape_shader, get_text_shader

def _rule_use_tetriminos():
    return TetriminoType, TETRIMINO_ROTATIONS


def _rule_use_dominos():
    return DominoType, DOMINO_ROTATIONS


# Configuration: which piece set to use
PIECE_TYPES, PIECE_ROTATIONS = _rule_use_tetriminos()
# PIECE_TYPES, PIECE_ROTATIONS = _rule_use_dominos()


class Piece:
    def __init__(self, piece_type, cell_size, batch, visible=False):
        self._piece_type = piece_type
        self._rotations = PIECE_ROTATIONS[piece_type]
        self._rotation_state = 0
        self._shapes_data = list(self._rotations[self._rotation_state])
        self._cell_size = cell_size
        self._batch = batch
        self._grid_x = 0
        self._grid_y = 0
        self._visible = visible
        self._placed = False
        
        # self._grams = rule_random_letters(len(self._shapes_data))
        self._grams = rule_scrabble_distribution(len(self._shapes_data))
        # self._grams = rule_englishcorpus_random_unigram(len(self._shapes_data))
        # self._grams = rule_englishcorpus_random_digram(len(self._shapes_data))
        # self._grams = rule_gramcorpus_distribution(len(self._shapes_data))
        
        shape_shader = get_shape_shader()
        
        self._cells = []
        self._labels = []
        # Base font for a single letter; multi-letter grams shrink to fit.
        base_font_size = int(cell_size * 0.6)
        
        for i, _ in enumerate(self._shapes_data):
            cell = pyglet.shapes.BorderedRectangle(
                0, 0, cell_size, cell_size,
                border=2,
                color=(255, 255, 255),
                border_color=(0, 0, 0),
                batch=batch,
                program=shape_shader
            )
            cell.visible = visible
            self._cells.append(cell)
            
            label = pyglet.text.Label(
                self._grams[i].text,
                font_size=gram_font_size(base_font_size, self._grams[i]),
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
            self._cells[i].x = px
            self._cells[i].y = py
            self._labels[i].x = px + math.floor(self._cell_size / 2)
            self._labels[i].y = py + math.floor(self._cell_size / 2)
    
    @property
    def piece_type(self):
        return self._piece_type
    
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
        for cell in self._cells:
            cell.visible = visible
        for label in self._labels:
            label.visible = visible
    
    def rotate_cw(self):
        self._rotation_state = (self._rotation_state + 1) % len(self._rotations)
        self._shapes_data = list(self._rotations[self._rotation_state])
        self._update_positions()
    
    def rotate_ccw(self):
        self._rotation_state = (self._rotation_state - 1) % len(self._rotations)
        self._shapes_data = list(self._rotations[self._rotation_state])
        self._update_positions()
    
    @property
    def placed(self):
        return self._placed
    
    def place(self):
        self._placed = True
    
    def get_cell_positions(self):
        """Returns list of (grid_x, grid_y) for each cell in this piece."""
        positions = []
        for dx, dy in self._shapes_data:
            positions.append((self._grid_x + dx, self._grid_y + dy))
        return positions
    
    def get_cell_data(self):
        """Returns list of (grid_x, grid_y, cell, label) for each cell."""
        data = []
        for i, (dx, dy) in enumerate(self._shapes_data):
            gx = self._grid_x + dx
            gy = self._grid_y + dy
            data.append((gx, gy, self._cells[i], self._labels[i]))
        return data
