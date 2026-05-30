import math
import pyglet
from models.letter_picker import rule_scrabble_distribution
from models.hex_domino import HexDominoType, HEX_DOMINO_DIRECTIONS, hex_neighbor
from models.hex_grid import SQRT3, flat_top_cell_center, flat_top_vertices
from views.shaders import get_shape_shader


# Configuration: which hex piece set to use (mirrors piece.py's pattern).
PIECE_TYPES = HexDominoType
PIECE_DIRECTIONS = HEX_DOMINO_DIRECTIONS


class HexPiece:
    def __init__(self, piece_type, cell_size, batch, visible=False):
        self._piece_type = piece_type
        # 'cell_size' carries the hex size (float) so the piece aligns exactly
        # with HexGrid, which is built from the same value.
        self._hex_size = cell_size
        self._sat_dirs = list(PIECE_DIRECTIONS[piece_type])
        self._rotation_state = 0
        self._batch = batch
        self._grid_x = 0
        self._grid_y = 0
        self._visible = visible
        self._placed = False

        cell_count = 1 + len(self._sat_dirs)
        self._letters = rule_scrabble_distribution(cell_count)

        shape_shader = get_shape_shader()
        # Sized to the hex height (sqrt(3)*size); a bit smaller than the cell so
        # the glyph clears the top/bottom hex edges.
        font_size = int(self._hex_size * SQRT3 * 0.5)
        # pyglet's anchor_y="center" centers the line box, not the glyph, so
        # capitals sit high (white space at the bottom). Nudge down to recenter.
        self._label_dy = -math.floor(font_size * 0.12)

        # Hexagon vertices built around the origin; repositioned per cell in
        # _update_positions. A Polygon anchors at its first vertex (angle 0,
        # i.e. +size on x), so centering a cell adds +size to the x position.
        base_verts = flat_top_vertices(self._hex_size, 0, 0)

        self._fills = []
        self._labels = []
        for i in range(cell_count):
            fill = pyglet.shapes.Polygon(
                *base_verts,
                color=(255, 255, 255),
                batch=batch,
                program=shape_shader
            )
            fill.visible = visible
            self._fills.append(fill)

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

    def _cell_grid_positions(self):
        positions = [(self._grid_x, self._grid_y)]
        for d in self._sat_dirs:
            positions.append(hex_neighbor(self._grid_x, self._grid_y, d))
        return positions

    def _update_positions(self):
        positions = self._cell_grid_positions()
        for i, (col, row) in enumerate(positions):
            cx, cy = flat_top_cell_center(self._hex_size, col, row)
            self._fills[i].position = (cx + self._hex_size, cy)
            self._labels[i].x = cx
            self._labels[i].y = cy + self._label_dy

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
        for fill in self._fills:
            fill.visible = visible
        for label in self._labels:
            label.visible = visible

    def rotate_cw(self):
        self._rotation_state = (self._rotation_state + 1) % 6
        rotated = []
        for d in self._sat_dirs:
            rotated.append((d + 1) % 6)
        self._sat_dirs = rotated
        self._update_positions()

    def rotate_ccw(self):
        self._rotation_state = (self._rotation_state - 1) % 6
        rotated = []
        for d in self._sat_dirs:
            rotated.append((d - 1) % 6)
        self._sat_dirs = rotated
        self._update_positions()

    @property
    def placed(self):
        return self._placed

    def place(self):
        self._placed = True

    def get_cell_positions(self):
        """Returns list of (grid_x, grid_y) for each cell in this piece."""
        return self._cell_grid_positions()

    def get_cell_data(self):
        """Returns list of (grid_x, grid_y, fill_shape, label) for each cell."""
        data = []
        positions = self._cell_grid_positions()
        for i, (gx, gy) in enumerate(positions):
            data.append((gx, gy, self._fills[i], self._labels[i]))
        return data
