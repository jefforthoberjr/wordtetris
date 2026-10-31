from models.hex_domino import hex_neighbor
from models.hex_grid import HexGrid, SQRT3, flattop_cell_center

_ALL_DIRECTIONS = range(6)


def hexagon_board_hex_size(diameter, area_size):
    """Largest cell radius whose whole board fits the square grid area. The board
    is `diameter` cells tall through its center column and `diameter` columns wide;
    the longer of those two spans is the one that has to fit."""
    height_in_sizes = diameter * SQRT3
    width_in_sizes = 2 + (diameter - 1) * 1.5
    return area_size / max(height_in_sizes, width_in_sizes)


class HexagonHexGrid(HexGrid):
    """A hex board whose overall silhouette is itself a regular hexagon.

    The cells are the same flat-top cells as HexGrid, in the same offset (col, row)
    coordinates, so neighbors, pieces and word walks all carry over. The difference
    is a diameter x diameter rectangle with its corners masked off: is_valid says no
    to a masked cell, so it can't be drawn, entered, clicked or spelled through.

    The silhouette comes out point-up: flat-top cells stack into straight vertical
    columns, so the points of the big hexagon land at 12 and 6 o'clock and its
    left/right sides are straight columns. For diameter 7 the column lengths are:
        4 5 6 7 6 5 4
    """

    def __init__(self, diameter, hex_size, area_size, batch):
        if diameter < 3 or diameter % 2 == 0:
            raise ValueError(
                f"game_screen.hexagon_diameter must be odd and >= 3, got {diameter}")
        self._diameter = diameter
        self._radius = (diameter - 1) // 2
        self._on_board = self._rule_hexagon_cells()
        # Center the board in the grid area: shift so the center cell lands in the
        # middle. Set before the base __init__, which draws the outlines through
        # _rule_flattop_cell_center.
        cx, cy = flattop_cell_center(hex_size, self._radius, self._radius)
        self._origin = (area_size / 2 - cx, area_size / 2 - cy)
        super().__init__(hex_size, area_size, area_size, batch)

    def _rule_hexagon_cells(self):
        """Every cell within `radius` steps of the center. Walked with hex_neighbor
        rather than a distance formula, so it can't disagree with the movement and
        word-walk lattice about what is adjacent."""
        center = (self._radius, self._radius)
        cells = {center}
        frontier = [center]
        for _ in range(self._radius):
            next_frontier = []
            for x, y in frontier:
                for direction in _ALL_DIRECTIONS:
                    neighbor = hex_neighbor(x, y, direction)
                    if neighbor not in cells:
                        cells.add(neighbor)
                        next_frontier.append(neighbor)
            frontier = next_frontier
        return cells

    def _rule_flattop_col_count(self, window_width):
        return self._diameter

    def _rule_flattop_row_count(self, window_height):
        return self._diameter

    def _rule_flattop_cell_center(self, col, row):
        cx, cy = flattop_cell_center(self._hex_size, col, row)
        return cx + self._origin[0], cy + self._origin[1]

    def is_valid(self, x, y):
        return (x, y) in self._on_board

    @property
    def origin(self):
        """Pixel shift applied to every cell center; HexagonBoardPiece shares it so
        pieces land exactly on the cells."""
        return self._origin
