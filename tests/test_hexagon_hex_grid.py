"""The hexagon-silhouette hex board (game_screen.grid: rule_use_hexagon_hex_grid):
which cells exist and where they land. The grid builds real outlines, so the shape
tests stub those out rather than needing a GL window."""

import math

import pytest

from models.hex_domino import hex_neighbor
from models.hexagon_hex_grid import HexagonHexGrid, hexagon_board_hex_size

_AREA = 1000.0


@pytest.fixture(autouse=True)
def _no_outlines(monkeypatch):
    monkeypatch.setattr(HexagonHexGrid, "_create_outlines", lambda self, batch: None)


def _board(diameter):
    size = hexagon_board_hex_size(diameter, _AREA)
    return HexagonHexGrid(diameter, size, _AREA, None)


def _cells(board):
    return [(x, y) for y in range(board.height) for x in range(board.width)
            if board.is_valid(x, y)]


def _column_lengths(board):
    return [sum(board.is_valid(x, y) for y in range(board.height))
            for x in range(board.width)]


@pytest.mark.parametrize("diameter, count", [(3, 7), (5, 19), (7, 37), (9, 61), (11, 91)])
def test_cell_count_is_the_hexagonal_number(diameter, count):
    assert len(_cells(_board(diameter))) == count


def test_diameter_7_column_lengths():
    assert _column_lengths(_board(7)) == [4, 5, 6, 7, 6, 5, 4]


def test_diameter_9_column_lengths():
    assert _column_lengths(_board(9)) == [5, 6, 7, 8, 9, 8, 7, 6, 5]


@pytest.mark.parametrize("diameter", [0, 1, 2, 4, 8])
def test_even_or_tiny_diameter_is_refused(diameter):
    with pytest.raises(ValueError):
        HexagonHexGrid(diameter, 10.0, _AREA, None)


@pytest.mark.parametrize("diameter", [3, 5, 7, 9, 11])
def test_board_fits_and_centers_in_the_grid_area(diameter):
    board = _board(diameter)
    size = board.hex_size
    half_height = math.sqrt(3) * size / 2
    centers = [board.cell_center(x, y) for x, y in _cells(board)]
    left = min(c[0] for c in centers) - size
    right = max(c[0] for c in centers) + size
    bottom = min(c[1] for c in centers) - half_height
    top = max(c[1] for c in centers) + half_height
    assert left >= -1e-6 and right <= _AREA + 1e-6
    assert bottom >= -1e-6 and top <= _AREA + 1e-6
    assert (left + right) / 2 == pytest.approx(_AREA / 2)
    assert (bottom + top) / 2 == pytest.approx(_AREA / 2)
    # The tall axis fills the area edge to edge.
    assert top - bottom == pytest.approx(_AREA)


@pytest.mark.parametrize("diameter", [7, 9])
def test_silhouette_is_left_right_and_top_bottom_symmetric(diameter):
    board = _board(diameter)
    centers = {(round(cx, 3), round(cy, 3))
               for cx, cy in (board.cell_center(x, y) for x, y in _cells(board))}
    mirrored_x = {(round(_AREA - cx, 3), cy) for cx, cy in centers}
    mirrored_y = {(cx, round(_AREA - cy, 3)) for cx, cy in centers}
    assert mirrored_x == centers
    assert mirrored_y == centers


def test_masked_corners_are_not_cells():
    board = _board(7)
    assert not board.is_valid(0, 0)
    assert board.get_cell(0, 0) is None
    assert board.gram_at(0, 0) is None
    assert not board.is_cell_occupied(0, 0)


def test_neighbors_never_leave_the_hexagon():
    board = _board(7)
    valid = set(_cells(board))
    for x, y in valid:
        assert set(board.neighbors(x, y)) <= valid
    # The center keeps all six; a point of the hexagon keeps only three.
    assert len(board.neighbors(*board.center_cell())) == 6
    assert len(board.neighbors(3, 6)) == 3


def test_click_on_a_corner_gap_misses_and_a_cell_center_hits():
    board = _board(7)
    assert board.cell_at(1, 1) is None
    assert board.cell_at(_AREA - 1, _AREA - 1) is None
    for x, y in _cells(board):
        assert board.cell_at(*board.cell_center(x, y)) == (x, y)


def test_center_cell_lands_in_the_middle_of_the_area():
    board = _board(7)
    cx, cy = board.cell_center(*board.center_cell())
    assert (cx, cy) == pytest.approx((_AREA / 2, _AREA / 2))


def test_top_center_spawn_is_on_the_board():
    # rule_muncher_spawn_top_center's formula: (floor((w-1)/2), h-1).
    board = _board(7)
    assert board.is_valid(math.floor((board.width - 1) / 2), board.height - 1)
    assert hex_neighbor(3, 6, 1) not in set(_cells(board))
