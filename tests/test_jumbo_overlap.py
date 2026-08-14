"""Cell-overlap rules against JUMBO cells (game_screen.cell_overlap_obstacle /
_mission / _fossilized).

A jumbo cell -- the triangle board's JUMBO_HEX -- spans six coordinates but is
recorded ONCE, at its primary, in _obstacle_cells / _mission_cells. The block
rules therefore have to resolve the coordinates a piece covers to their owning
CELL before testing membership; matching raw coordinates only blocked a piece
sitting on the anchor triangle, and let it move over (and place on) the other
five -- where hover, which resolves, hid the whole jumbo and made it look like
the big hexagon had vanished.

See views/game_screen_boardrules._owning_cells and models/triangle_grid.
"""
from views import game_screen as gs


PRIMARY = (7, 4)
# The five further coordinates a jumbo anchored at PRIMARY covers.
COVERED = [(8, 4), (9, 4), (8, 3), (8, 5), (9, 5)]


class _JumboBoard:
    """Board holding ONE jumbo cell: `PRIMARY` plus `COVERED` all resolve to
    PRIMARY, every other coordinate owns itself. Only the two methods the
    overlap gate calls are needed."""

    def __init__(self):
        self._footprint = {c: PRIMARY for c in [PRIMARY] + COVERED}

    def resolve(self, x, y):
        return self._footprint.get((x, y), (x, y))

    def is_cell_occupied(self, x, y):
        return (x, y) in self._footprint


def _overlap_game(obstacles=(), missions=(), fossils=()):
    """A bare GameScreen with a one-jumbo board and the three tracking sets, so
    the overlap rules can be called directly."""
    g = gs.GameScreen.__new__(gs.GameScreen)
    g._board = _JumboBoard()
    g._obstacle_cells = set(obstacles)
    g._mission_cells = set(missions)
    g._fossilized_cells = set(fossils)
    return g


def test_block_obstacle_covers_whole_jumbo_footprint():
    # The obstacle is tracked at its primary only; covering ANY coordinate of it
    # must be refused, not just the anchor.
    g = _overlap_game(obstacles=[PRIMARY])
    assert not g._rule_block_moveandplace_over_obstacle_cell({PRIMARY})
    for coord in COVERED:
        assert not g._rule_block_moveandplace_over_obstacle_cell({coord}), coord
    # A coordinate outside the jumbo is still free.
    assert g._rule_block_moveandplace_over_obstacle_cell({(0, 0)})


def test_block_mission_and_fossil_cover_whole_jumbo_footprint():
    g = _overlap_game(missions=[PRIMARY], fossils=[PRIMARY])
    for coord in COVERED:
        assert not g._rule_block_moveandplace_over_mission_cell({coord}), coord
        assert not g._rule_block_moveandplace_over_fossilized_cell({coord}), coord


def test_covered_jumbo_coordinate_is_not_a_player_cell():
    # _players_covered is "covered cells in neither track"; a non-anchor
    # coordinate of a tracked jumbo belongs to the obstacle, so a player-blocking
    # config must not mistake it for a player cell (and an obstacle-blocking one
    # must not double-count it).
    g = _overlap_game(obstacles=[PRIMARY])
    assert g._players_covered(set(COVERED)) == set()
    assert g._players_covered({(0, 0)}) == {(0, 0)}


def test_overlap_action_forgets_jumbo_covered_by_any_coordinate():
    # The allow-overlap configs bury the jumbo whole (TriangleGrid.place), so the
    # tracking sets must drop it whole -- otherwise a buried mission still counts
    # as outstanding and the victory rule waits forever.
    g = _overlap_game(obstacles=[PRIMARY], missions=[PRIMARY])
    forgotten = []
    g._forget_cell_health = forgotten.extend
    g._rule_old_cells_get_delete({COVERED[0]})
    assert g._obstacle_cells == set()
    assert g._mission_cells == set()
    assert forgotten == [PRIMARY]
