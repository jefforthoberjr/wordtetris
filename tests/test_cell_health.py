"""Cell health (game_screen.cell_health): obstacle / mission cells that survive
several words, and the fossilized attacker trail the words leave meanwhile.

Reuses the selection-pipeline fakes from test_word_selection (bare __new__
GameScreen + sparse FakeBoard), then wires the health rules on top -- the same
way GameScreen.__init__ does from config. See views/game_screen_health.py.
"""
from tests.test_word_selection import _game, FakeBoard


def _health_game(board, obstacles=(), health=3, missions=(), mission_health=3,
                 release_all=True, fossilize=True, allow_fossil_reuse=True):
    """A selection-pipeline game with cell health switched ON. `obstacles` /
    `missions` are the starting cells of each track, each given `health` /
    `mission_health`. The knobs mirror the config rules of the same name."""
    g = _game(board)
    g._obstacle_cells = set(obstacles)
    g._mission_cells = set(missions)
    g._cell_health_tracking = True
    g._obstacle_health_amount = health
    g._mission_health_amount = mission_health
    g._obstacle_health_rule = g._rule_obstacle_health_fixed
    g._mission_health_rule = g._rule_mission_health_fixed
    g._cell_health_rule = g._rule_cell_health_on
    g._health_word_action_rule = (
        g._rule_health_word_fossilize if fossilize else g._rule_health_word_clear)
    g._attacker_release_rule = (
        g._rule_attacker_release_when_all_dead if release_all
        else g._rule_attacker_release_when_any_dead)
    if allow_fossil_reuse:
        # A held fossil stays walkable, so the next word can chain onto it.
        g._fossil_is_wall_rule = g._rule_fossil_allow_is_wall
        g._fossil_word_ok_rule = g._rule_fossil_allow_word_ok
    g._assign_cell_health()
    return g


def test_init_cell_health_wires_every_rule_from_config():
    # _init_cell_health is GameScreen.__init__'s whole health setup, moved into
    # the mixin. Exercised directly because the other tests hand-wire the rules
    # and so would not notice it failing to run at all (e.g. a name it uses not
    # being imported in the mixin's module).
    from views.game_screen import GameScreen
    g = GameScreen.__new__(GameScreen)
    g._init_cell_health()
    for attr in ("_cell_health_rule", "_health_word_action_rule",
                 "_attacker_release_rule", "_damage_display_rule",
                 "_obstacle_health_rule", "_mission_health_rule"):
        assert callable(getattr(g, attr)), attr
    assert g._cell_health == {} and g._cell_attackers == {}
    # The per-game overlays wait for a board to take their geometry from.
    assert g._damage_fill is None
    assert g._damage_border_gap is None


class _FakeTrail:
    """Stand-in for views.word_trail.WordTrail (real Lines need a GL context).
    Records the tagged paths so a test can assert a word's line was drawn and
    later dropped."""

    def __init__(self):
        self.paths = []
        # Fade time each path was recorded with (None = never fades), so a test can
        # assert which trails the fade rule marked for expiry.
        self.fades = []

    def add_path(self, points, cells=None, fade_seconds=None):
        self.paths.append(set(cells or ()))
        self.fades.append(fade_seconds)

    def remove_paths_touching(self, cells):
        gone = set(cells)
        self.paths = [p for p in self.paths if not (p & gone)]


def _trail_game(*args, **kwargs):
    """A health game with the word-trail overlay switched on, both halves of the
    knob wired as GameScreen.__init__ pairs them."""
    g = _health_game(*args, **kwargs)
    g._word_trail = _FakeTrail()
    g._word_trail_rule = g._rule_word_trail_on
    g._drop_trails_rule = g._rule_drop_trails_on_release
    # The trail asks the grid for a cell's VISUAL center (which differs from
    # cell_center only for a triangle board's jumbo cells).
    g._board.cell_visual_center = g._board.cell_center
    return g


def test_attacking_words_line_is_drawn_then_dropped_with_its_target():
    g = _trail_game(
        FakeBoard({(0, 0): "S", (1, 0): "P", (2, 0): "I", (3, 0): "N",
                   (4, 0): "E"}),
        obstacles=[(3, 0)], health=2)
    _clear(g, "pine", [(1, 0)])
    # The attacking word left a line through its own cells.
    assert g._word_trail.paths == [{(1, 0), (2, 0), (3, 0), (4, 0)}]
    _clear(g, "spine", [(0, 0)])
    # The target fell, so its attackers withdrew -- and their lines went too,
    # rather than outliving the obstacle they were drawn against.
    assert g._word_trail.paths == []


def test_line_survives_while_the_target_does():
    g = _trail_game(
        FakeBoard({(0, 0): "S", (1, 0): "P", (2, 0): "I", (3, 0): "N",
                   (4, 0): "E"}),
        obstacles=[(3, 0)], health=3)
    _clear(g, "pine", [(1, 0)])
    _clear(g, "spine", [(0, 0)])
    # Two hits on a 3-health target: it is still standing, so both lines remain.
    assert g._cell_health[(3, 0)] == 1
    assert len(g._word_trail.paths) == 2


def test_fade_nonattacker_marks_only_the_lines_away_from_a_target():
    # game_screen.word_trail_fade = rule_word_trail_fade_nonattacker: a word that
    # runs through a health-carrying cell keeps its line (it shows a commitment,
    # and it is dropped when the target falls); a word cleared elsewhere on the
    # board gets a fade time so its line does not sit there for the rest of the
    # game.
    g = _trail_game(
        FakeBoard({(0, 0): "S", (1, 0): "P", (2, 0): "I", (3, 0): "N",
                   (4, 0): "E", (0, 1): "T", (1, 1): "I", (2, 1): "N"}),
        obstacles=[(3, 0)], health=3)
    g._word_trail_fade_seconds = 4.0
    g._trail_fade_rule = g._rule_word_trail_fade_nonattacker
    _clear(g, "pine", [(1, 0)])          # through the obstacle at (3, 0)
    _clear(g, "tin", [(0, 1)])           # nowhere near it
    assert g._word_trail.fades == [None, 4.0]


def test_fade_all_marks_every_line_and_fade_off_marks_none():
    board = FakeBoard({(0, 0): "S", (1, 0): "P", (2, 0): "I", (3, 0): "N",
                       (4, 0): "E"})
    g = _trail_game(board, obstacles=[(3, 0)], health=3)
    g._word_trail_fade_seconds = 2.5
    g._trail_fade_rule = g._rule_word_trail_fade_all
    _clear(g, "pine", [(1, 0)])
    assert g._word_trail.fades == [2.5]
    # The default rule leaves every trail up for the whole game (the behavior
    # before the fade existed).
    g2 = _trail_game(
        FakeBoard({(0, 0): "S", (1, 0): "P", (2, 0): "I", (3, 0): "N",
                   (4, 0): "E"}),
        obstacles=[(3, 0)], health=3)
    _clear(g2, "pine", [(1, 0)])
    assert g2._word_trail.fades == [None]


class _FakeFill:
    """Stand-in for views.rising_fill.RisingFill (real Polygons need a GL
    context). Records the last fraction set per cell."""

    def __init__(self):
        self.fractions = {}

    def set_fraction(self, cell, fraction):
        if fraction is None or fraction <= 0.0:
            self.fractions.pop(cell, None)
        else:
            self.fractions[cell] = fraction


def test_rising_fill_tracks_damage_and_clears_when_the_target_falls():
    g = _health_game(
        FakeBoard({(0, 0): "S", (1, 0): "P", (2, 0): "I", (3, 0): "N",
                   (4, 0): "E"}),
        obstacles=[(3, 0)], health=2)
    g._damage_fill = _FakeFill()
    g._damage_display_rule = g._rule_damage_fill_rising
    # Undamaged: nothing drawn.
    assert g._damage_fill.fractions == {}
    _clear(g, "pine", [(1, 0)])
    # One of two hits taken -> the cell is half filled.
    assert g._damage_fill.fractions == {(3, 0): 0.5}
    _clear(g, "spine", [(0, 0)])
    # Destroyed: the indicator goes with the cell rather than being left behind.
    assert g._damage_fill.fractions == {}


class _FakeBorder:
    """Stand-in for views.border_dashes.BorderDashes. Records the (marked, total)
    slot run last painted per cell."""

    def __init__(self):
        self.marked = {}

    def set_marked(self, cell, marked, total):
        if not marked or not total:
            self.marked.pop(cell, None)
        else:
            self.marked[cell] = (marked, total)

    def remove(self, cell):
        self.marked.pop(cell, None)


def test_border_damage_counts_whole_hits_and_clears_on_death():
    g = _health_game(
        FakeBoard({(0, 0): "S", (1, 0): "P", (2, 0): "I", (3, 0): "N",
                   (4, 0): "E"}),
        obstacles=[(3, 0)], health=3)
    g._damage_border_gap = _FakeBorder()
    g._damage_display_rule = g._rule_damage_border_dashed
    assert g._damage_border_gap.marked == {}      # undamaged: outline untouched
    _clear(g, "pine", [(1, 0)])
    assert g._damage_border_gap.marked == {(3, 0): (1, 3)}   # 1 slot of 3
    _clear(g, "spine", [(0, 0)])
    assert g._damage_border_gap.marked == {(3, 0): (2, 3)}   # 2 slots of 3


def test_border_fill_uses_its_own_overlay():
    # The fill rule paints the damage-colored overlay, leaving the gap overlay
    # (which blanks the outline) untouched -- they are never both drawn.
    g = _health_game(
        FakeBoard({(0, 0): "P", (1, 0): "I", (2, 0): "N", (3, 0): "E"}),
        obstacles=[(2, 0)], health=2)
    g._damage_border_gap = _FakeBorder()
    g._damage_border_mark = _FakeBorder()
    g._damage_display_rule = g._rule_damage_border_fill
    _clear(g, "pine", [(0, 0)])
    assert g._damage_border_mark.marked == {(2, 0): (1, 2)}
    assert g._damage_border_gap.marked == {}


def test_damage_display_none_draws_nothing():
    g = _health_game(
        FakeBoard({(0, 0): "P", (1, 0): "I", (2, 0): "N", (3, 0): "E"}),
        obstacles=[(2, 0)], health=3)
    g._damage_fill = _FakeFill()
    g._damage_display_rule = g._rule_damage_display_none
    _clear(g, "pine", [(0, 0)])
    assert g._cell_health[(2, 0)] == 2      # damage still tracked...
    assert g._damage_fill.fractions == {}   # ...just not shown


def _clear(g, word, placed):
    """Run one word through the pipeline the way a submit does."""
    g._begin_selection(list(placed))
    g._on_submit_word(word)


def test_health_survives_the_first_word_and_holds_its_cells():
    # P + INE spells PINE through an obstacle cell (2,0) carrying 3 health.
    g = _health_game(
        FakeBoard({(0, 0): "P", (1, 0): "I", (2, 0): "N", (3, 0): "E"}),
        obstacles=[(2, 0)], health=3)
    _clear(g, "pine", [(0, 0)])
    # The obstacle survived with one point taken, gram intact so it can be
    # spelled through again, and still counts for the victory rules.
    assert g._cell_health[(2, 0)] == 2
    assert g._board.gram_at(2, 0) is not None
    assert g._obstacle_cells == {(2, 0)}
    # The word's PLAYER cells are held: still on the board, fossilized.
    assert set(g._board.cells) == {(0, 0), (1, 0), (2, 0), (3, 0)}
    assert g._fossilized_cells == {(0, 0), (1, 0), (3, 0)}
    # The obstacle cell itself is never fossilized while it lives.
    assert (2, 0) not in g._fossilized_cells
    assert g._attacker_targets[(0, 0)] == {(2, 0)}


def test_attacker_trail_can_be_chained_onto():
    # The point of holding the cells: PINE fossilizes P-I-E, then SPINE chains
    # onto that same trail and damages the obstacle a second time.
    g = _health_game(
        FakeBoard({(0, 0): "S", (1, 0): "P", (2, 0): "I", (3, 0): "N",
                   (4, 0): "E"}),
        obstacles=[(3, 0)], health=3)
    _clear(g, "pine", [(1, 0)])
    assert g._cell_health[(3, 0)] == 2
    _clear(g, "spine", [(0, 0)])
    assert g._cell_health[(3, 0)] == 1
    assert g._fossilized_cells == {(0, 0), (1, 0), (2, 0), (4, 0)}


def test_last_hit_destroys_the_target_and_releases_the_trail():
    g = _health_game(
        FakeBoard({(0, 0): "S", (1, 0): "P", (2, 0): "I", (3, 0): "N",
                   (4, 0): "E"}),
        obstacles=[(3, 0)], health=2)
    _clear(g, "pine", [(1, 0)])
    assert g._board.cells      # still held
    _clear(g, "spine", [(0, 0)])
    # The obstacle hit 0: it left the board with every cell it was holding, and
    # it no longer counts toward the obstacle victory rule.
    assert g._board.cells == {}
    assert g._obstacle_cells == set()
    assert g._fossilized_cells == set()
    assert g._cell_health == {}


def _rang_era_game(held):
    """The session-log case: RANG attacks the obstacle NG and fossilizes R + A,
    then ERA reuses that R + A but misses the obstacle entirely, so it is an
    ordinary word heading for the remove clear-action. `held` picks the
    game_screen.attacker_cell_clear rule."""
    g = _health_game(
        FakeBoard({(0, 0): "E", (1, 0): "R", (2, 0): "A", (3, 0): "NG"}),
        obstacles=[(3, 0)], health=3)
    g._attacker_hold_rule = (g._rule_attacker_cells_held if held
                             else g._rule_attacker_cells_consumable)
    _clear(g, "rang", [(1, 0)])
    assert g._cell_health[(3, 0)] == 2
    assert g._attacker_targets[(1, 0)] == {(3, 0)}
    assert g._attacker_targets[(2, 0)] == {(3, 0)}
    _clear(g, "era", [(0, 0)])
    return g


def test_held_attacker_cells_survive_a_later_nonattacking_word():
    g = _rang_era_game(held=True)
    # ERA cleared its own fresh cell, but the two cells committed to the still-live
    # obstacle stayed put -- with their grams, their fossil state and their
    # commitment intact, so the attack RANG paid for is not withdrawn.
    assert set(g._board.cells) == {(1, 0), (2, 0), (3, 0)}
    assert g._fossilized_cells == {(1, 0), (2, 0)}
    assert g._attacker_targets[(1, 0)] == {(3, 0)}
    assert g._cell_health[(3, 0)] == 2
    # And they still leave the normal way, with the target they attack. (The
    # repeat history is cleared between the two hits only because this small board
    # spells exactly one word through the obstacle.)
    for _ in range(2):
        g._cleared_word_history.clear()
        _clear(g, "rang", [(1, 0)])
    assert g._board.cells == {}
    assert g._obstacle_cells == set()
    assert g._fossilized_cells == set()


def test_consumable_attacker_cells_keep_the_original_behavior():
    g = _rang_era_game(held=False)
    # The original path: ERA took the attacker cells with it, leaving the damaged
    # obstacle alone on the board with no trail recording the hit.
    assert set(g._board.cells) == {(3, 0)}
    assert g._cell_health[(3, 0)] == 2
    # Known wart of this rule: the cells are gone from the board but still listed
    # as fossils / committed attackers, since the remove clear-action does not know
    # about the health bookkeeping. rule_attacker_cells_held sidesteps it by never
    # letting those cells be removed out from under the target.
    assert g._fossilized_cells == {(1, 0), (2, 0)}


def test_one_word_damages_every_target_on_its_path():
    # PINE threaded through TWO obstacle cells takes a point off each.
    g = _health_game(
        FakeBoard({(0, 0): "P", (1, 0): "I", (2, 0): "N", (3, 0): "E"}),
        obstacles=[(1, 0), (2, 0)], health=3)
    _clear(g, "pine", [(0, 0)])
    assert g._cell_health == {(1, 0): 2, (2, 0): 2}


def test_release_when_all_dead_keeps_the_trail_for_the_surviving_target():
    # The word crosses a 1-health obstacle (dies now) and a 3-health one. Under
    # the default rule the fossils stay, still held by the survivor.
    g = _health_game(
        FakeBoard({(0, 0): "P", (1, 0): "I", (2, 0): "N", (3, 0): "E"}),
        obstacles=[(1, 0)], health=3, missions=[(2, 0)], mission_health=1)
    _clear(g, "pine", [(0, 0)])
    assert g._cell_health == {(1, 0): 2}          # the mission cell died
    assert (2, 0) not in g._board.cells
    assert g._mission_cells == set()
    # P and E are still held by the surviving obstacle at (1,0).
    assert g._fossilized_cells == {(0, 0), (3, 0)}
    assert set(g._board.cells) == {(0, 0), (1, 0), (3, 0)}


def test_release_when_any_dead_frees_the_trail_immediately():
    g = _health_game(
        FakeBoard({(0, 0): "P", (1, 0): "I", (2, 0): "N", (3, 0): "E"}),
        obstacles=[(1, 0)], health=3, missions=[(2, 0)], mission_health=1,
        release_all=False)
    _clear(g, "pine", [(0, 0)])
    # Same damage, but the fossils leave with the first target to die.
    assert g._cell_health == {(1, 0): 2}
    assert g._fossilized_cells == set()
    assert set(g._board.cells) == {(1, 0)}


def test_health_word_clear_takes_damage_without_a_trail():
    # The no-trail variant: the word clears normally, the target just loses a
    # point of health (and so stays on the board).
    g = _health_game(
        FakeBoard({(0, 0): "P", (1, 0): "I", (2, 0): "N", (3, 0): "E"}),
        obstacles=[(2, 0)], health=3, fossilize=False)
    _clear(g, "pine", [(0, 0)])
    assert g._cell_health[(2, 0)] == 2
    assert g._fossilized_cells == set()
    # Every cell the word used left, the damaged obstacle among them -- it is
    # only its HEALTH that survives, which is what this variant trades away.
    assert g._board.cells == {}


def test_health_off_is_the_original_behavior():
    # The default config: an obstacle cell clears on the first word through it
    # and nothing is held.
    g = _game(FakeBoard({(0, 0): "P", (1, 0): "I", (2, 0): "N", (3, 0): "E"}))
    g._obstacle_cells = {(2, 0)}
    g._assign_cell_health()
    _clear(g, "pine", [(0, 0)])
    assert g._cell_health == {}
    assert g._board.cells == {}
    assert g._obstacle_cells == set()
    assert g._fossilized_cells == set()
