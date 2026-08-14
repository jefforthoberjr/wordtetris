"""GameScreen's numeric board knobs track the ACTIVE game mode.

The class body reads CONFIG at import, which happens before apply_game_mode
merges a mode's overrides in -- so the class attributes hold base config.yaml
values forever. GameScreen._read_config_knobs re-reads them per instance; these
tests pin that, since the failure mode is silent (the board just quietly uses the
base value and every mode override of the key is ignored).
"""
import pytest

import config
from views.game_screen import GameScreen

_MODE = "src/assets/game_modes/triangles_jumbo.yaml"


@pytest.fixture(autouse=True)
def _restore_config():
    """apply_game_mode replaces CONFIG's contents in place, and every other test
    module reads that same dict -- so put the base config back afterwards rather
    than leaving a mode applied for whatever runs next."""
    yield
    base = config.load_config()
    config.CONFIG.clear()
    config.CONFIG.update(base)


def _knobs_after(path):
    """The knobs a GameScreen built under game mode `path` would use. A bare
    __new__ instance is enough: _read_config_knobs is the first thing __init__
    does and touches nothing but CONFIG."""
    config.apply_game_mode(path)
    g = GameScreen.__new__(GameScreen)
    g._read_config_knobs()
    return g


def test_mode_override_of_obstacle_and_mission_counts_applies():
    # triangles_jumbo asks for 6 obstacles / 1 mission; the base config.yaml says
    # something else. Before the fix the board silently used the base values.
    base_obstacles = config.load_config()["rules"]["game_screen.obstacle_count"]
    g = _knobs_after(_MODE)
    assert g.OBSTACLE_COUNT == config.CONFIG["rules"]["game_screen.obstacle_count"]
    assert g.MISSION_COUNT == config.CONFIG["rules"]["game_screen.mission_count"]
    # The class attribute is still the frozen base value -- that is what the
    # instance read has to shadow, and what a bare instance falls back to.
    assert GameScreen.OBSTACLE_COUNT == base_obstacles


def test_every_numeric_knob_tracks_the_live_config():
    g = _knobs_after(_MODE)
    for name, key in (
        ("GRID_WIDTH", "game_screen.grid_width"),
        ("PIECE_POOL_SIZE", "game_screen.piece_pool_size"),
        ("OBSTACLE_COUNT", "game_screen.obstacle_count"),
        ("MISSION_COUNT", "game_screen.mission_count"),
    ):
        assert getattr(g, name) == config.CONFIG["rules"][key], name
