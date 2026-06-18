import math
import pyglet
from models.gram import gram_font_size
from models.gram_picker import rule_random_letters
from models.gram_picker import rule_scrabble_distribution
from models.gram_picker import rule_englishcorpus_random_unigram
from models.gram_picker import rule_englishcorpus_random_digram
from models.gram_picker import rule_grams_greater_than_47
from models.gram_picker import rule_mixed_scrabble_digram52
from models.gram_picker import rule_digram52_distribution
from models.gram_picker import rule_trigram_equalweight
from models.gram_picker import rule_scrabble_with_allvowelswild
from models.square_tetrimino import SquareTetriminoType, SQUARE_TETRIMINO_ROTATIONS
from models.square_domino import SquareDominoType, SQUARE_DOMINO_ROTATIONS
from models.square_unimo import SquareUnimoType, SQUARE_UNIMO_ROTATIONS
from views.shaders import get_shape_shader, get_text_shader
from views.textures import wild_vowel_image
from config import select_rule, get_color

def _rule_use_tetriminos():
    return SquareTetriminoType, SQUARE_TETRIMINO_ROTATIONS


def _rule_use_dominos():
    return SquareDominoType, SQUARE_DOMINO_ROTATIONS


def _rule_use_unimos():
    return SquareUnimoType, SQUARE_UNIMO_ROTATIONS


# Which piece set to use. The main (player) pieces follow square_player.piece_set;
# the starting obstacles follow their own square_obstacle.piece_set, so obstacles
# can be (say) unimos while the playable pieces are tetriminos.
_PIECE_SET_RULES = {
    "rule_use_tetriminos": _rule_use_tetriminos,
    "rule_use_dominos": _rule_use_dominos,
    "rule_use_unimos": _rule_use_unimos,
}
PLAYER_PIECE_TYPES, PLAYER_PIECE_ROTATIONS = select_rule("square_player.piece_set", _PIECE_SET_RULES)()
OBSTACLE_PIECE_TYPES, _OBSTACLE_PIECE_ROTATIONS = select_rule("square_obstacle.piece_set", _PIECE_SET_RULES)()
# Mission pieces (the light-red goal pieces) get their own piece set too, the
# direct parallel of the obstacles above.
MISSION_PIECE_TYPES, _MISSION_PIECE_ROTATIONS = select_rule("square_mission.piece_set", _PIECE_SET_RULES)()

# A piece looks up its rotations by piece_type alone. Merging every set's table
# (the type enums are distinct, so keys never collide) means one SquarePiece
# class serves both the main set and a differently-configured obstacle set.
ALL_PIECE_ROTATIONS = {}
ALL_PIECE_ROTATIONS.update(SQUARE_TETRIMINO_ROTATIONS)
ALL_PIECE_ROTATIONS.update(SQUARE_DOMINO_ROTATIONS)
ALL_PIECE_ROTATIONS.update(SQUARE_UNIMO_ROTATIONS)

# How each piece's grams are picked. The main (player) pieces follow square_player.gram_pick;
# the starting obstacles follow their own square_obstacle.gram_pick.
_GRAM_PICK_RULES = {
    "rule_random_letters": rule_random_letters,
    "rule_scrabble_distribution": rule_scrabble_distribution,
    "rule_englishcorpus_random_unigram": rule_englishcorpus_random_unigram,
    "rule_englishcorpus_random_digram": rule_englishcorpus_random_digram,
    "rule_grams_greater_than_47": rule_grams_greater_than_47,
    "rule_mixed_scrabble_digram52": rule_mixed_scrabble_digram52,
    "rule_digram52_distribution": rule_digram52_distribution,
    "rule_trigram_equalweight": rule_trigram_equalweight,
    "rule_scrabble_with_allvowelswild": rule_scrabble_with_allvowelswild,
}
_gram_pick_rule = select_rule("square_player.gram_pick", _GRAM_PICK_RULES)
OBSTACLE_GRAM_PICK_RULE = select_rule("square_obstacle.gram_pick", _GRAM_PICK_RULES)
MISSION_GRAM_PICK_RULE = select_rule("square_mission.gram_pick", _GRAM_PICK_RULES)


class SquarePiece:
    def __init__(self, piece_type, cell_size, batch, visible=False, gram_pick_rule=None, cell_color=None):
        self._piece_type = piece_type
        self._rotations = ALL_PIECE_ROTATIONS[piece_type]
        self._rotation_state = 0
        self._shapes_data = list(self._rotations[self._rotation_state])
        self._cell_size = cell_size
        self._batch = batch
        self._grid_x = 0
        self._grid_y = 0
        self._visible = visible
        self._placed = False

        # Pools inject a gram-pick rule so obstacles can pick grams differently
        # from the main pieces; falling back to the configured default.
        if gram_pick_rule is None:
            gram_pick_rule = _gram_pick_rule
        self._grams = gram_pick_rule(len(self._shapes_data))

        # Cell fill color; pools tint obstacles differently from the default
        # playable pieces. None falls back to the configured cell fill.
        if cell_color is None:
            cell_color = get_color("board.settled_cell_fill")
        border_color = get_color("board.cell_border")
        text_color = get_color("board.cell_text")
        
        shape_shader = get_shape_shader()
        
        self._cells = []
        self._labels = []
        # Base font for a single letter; multi-letter grams shrink to fit.
        base_font_size = int(cell_size * 0.6)
        
        for i, _ in enumerate(self._shapes_data):
            cell = pyglet.shapes.BorderedRectangle(
                0, 0, cell_size, cell_size,
                border=2,
                color=cell_color,
                border_color=border_color,
                batch=batch,
                program=shape_shader
            )
            cell.visible = visible
            self._cells.append(cell)

            # A wild-vowel gram renders as the vowel emblem sprite instead of a
            # letter label; everything downstream (positioning, visibility,
            # hover) treats the sprite and label alike via the _labels slot.
            gram = self._grams[i]
            if gram.is_wild:
                image = wild_vowel_image(math.floor(cell_size * 0.9))
                label = pyglet.sprite.Sprite(image, batch=batch)
                label.scale = (cell_size * 0.9) / image.height
            else:
                label = pyglet.text.Label(
                    gram.text,
                    font_size=gram_font_size(base_font_size, gram),
                    weight='bold',
                    color=text_color,
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
    def rotation_count(self):
        """Number of distinct rotation states (so a spawn rule can pick one)."""
        return len(self._rotations)

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
        """Returns list of (grid_x, grid_y, cell, label, gram) for each cell.
        The gram travels with the render objects so the board can record what a
        placed cell holds (its letters, or that it is a wild vowel)."""
        data = []
        for i, (dx, dy) in enumerate(self._shapes_data):
            gx = self._grid_x + dx
            gy = self._grid_y + dy
            data.append((gx, gy, self._cells[i], self._labels[i], self._grams[i]))
        return data
