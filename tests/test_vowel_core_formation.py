"""rule_formation_fill_vowel_core_consonant_shell: the zone geometry (multigrams to the
corners, vowel disc at center, consonant rim around it) and the picker's unigram
vowel/consonant class pin that fills those zones."""
from collections import Counter

import models.gram_picker as gp
from config import CONFIG
from models.wild_vowel import is_vowel
from views.game_screen_setup import BoardSetupMixin


class FakeBoard:
    """A W x H square board, all cells valid, cell centers one unit apart (pyglet
    y-up). Enough for the zone splitters, which read geometry only."""

    def __init__(self, width=6, height=6):
        self.width = width
        self.height = height

    def is_valid(self, x, y):
        return 0 <= x < self.width and 0 <= y < self.height

    def cell_center(self, x, y):
        return (float(x), float(y))

    def center_cell(self):
        return (self.width // 2, self.height // 2)


class Setup(BoardSetupMixin):
    """The mixin alone, with just the board attribute its zone splitters touch."""

    def __init__(self, board):
        self._board = board


def _cells(board):
    return [(x, y) for y in range(board.height) for x in range(board.width)]


def test_corner_distance_ranks_the_four_corners_first():
    board = FakeBoard(6, 6)
    setup = Setup(board)
    ordered = setup._cells_by_corner_distance(_cells(board))
    assert set(ordered[:4]) == {(0, 0), (0, 5), (5, 0), (5, 5)}
    # ...and the dead-center cells rank last.
    assert set(ordered[-4:]) <= {(2, 2), (2, 3), (3, 2), (3, 3)}


def test_vowel_core_takes_the_center_share_and_rim_takes_the_rest():
    board = FakeBoard(6, 6)
    setup = Setup(board)
    cells = _cells(board)
    pct = CONFIG["rules"]["game_screen.vowel_core_percent"]
    core, rim = setup._split_vowel_core(cells)
    assert len(core) == round(len(cells) * pct / 100.0)
    assert len(core) + len(rim) == len(cells)
    assert not (set(core) & set(rim))
    # Every core cell is at least as close to center as every rim cell.
    cx, cy = board.cell_center(*board.center_cell())
    far_core = max((x - cx) ** 2 + (y - cy) ** 2 for x, y in core)
    near_rim = min((x - cx) ** 2 + (y - cy) ** 2 for x, y in rim)
    assert far_core <= near_rim


def test_left_right_split_sends_corners_to_their_own_fix_pool():
    board = FakeBoard(6, 6)
    setup = Setup(board)
    left, right = setup._split_left_right([(0, 0), (0, 5), (5, 0), (5, 5)])
    assert set(left) == {(0, 0), (0, 5)}
    assert set(right) == {(5, 0), (5, 5)}


def _draw_pinned(unigram_class, count):
    """Draw `count` unigrams through the real pick_grams choke point with the class
    pinned, exactly as _place_region_cells does per cell."""
    gp.reset_gram_dedup()
    gp.begin_formation_gram_run()
    grams = []
    for _ in range(count):
        gp.set_forced_formation_cell(1, None)
        gp.set_forced_unigram_class(unigram_class)
        try:
            grams += gp.pick_grams(gp.rule_grams_greater_than_47_lengthcontrolled, 1)
        finally:
            gp.clear_forced_formation_cell()
    gp.end_formation_gram_run()
    return grams


def test_vowel_pin_draws_only_vowels_consonant_pin_only_consonants():
    vowels = _draw_pinned("vowel", 40)
    assert len(vowels) == 40
    assert all(len(g.text) == 1 and is_vowel(g.text) for g in vowels), \
        Counter(g.text for g in vowels)
    consonants = _draw_pinned("consonant", 40)
    assert all(not is_vowel(g.text[0]) for g in consonants), \
        Counter(g.text for g in consonants)


def test_clearing_the_cell_pin_also_clears_the_class_pin():
    _draw_pinned("vowel", 1)
    assert gp._forced_unigram_class is None


class RecordingSetup(Setup):
    """The formation with its two side effects stubbed: records (cells, length, attr,
    class) per _place_region_cells call and every vowel-guarantee arming, so the
    orchestration can be checked without a GL window or a real piece."""

    def __init__(self, board):
        super().__init__(board)
        self.placed = []
        self.armed = []

    def _place_region_cells(self, cells, length, attr, unigram_class=None):
        self.placed.append((list(cells), length, attr, unigram_class))

    def _arm_vowel_guarantee(self, count):
        self.armed.append(count)


def test_formation_zones_cover_the_board_exactly_once():
    board = FakeBoard(6, 6)
    setup = RecordingSetup(board)
    setup._rule_formation_fill_vowel_core_consonant_shell()

    cells = _cells(board)
    placed = [c for group, _len, _attr, _cls in setup.placed for c in group]
    assert sorted(placed) == sorted(cells)       # every cell once, none twice

    by_zone = {(length, attr, cls): group
               for group, length, attr, cls in setup.placed}
    n_uni, n_di, n_tri = setup._region_length_counts(len(cells))
    tri = by_zone[(3, "prefix", None)] + by_zone[(3, "midsuf", None)]
    assert len(tri) == n_tri
    assert len(by_zone[(2, None, None)]) == n_di
    core = by_zone[(1, None, "vowel")]
    rim = by_zone[(1, None, "consonant")]
    assert len(core) + len(rim) == n_uni

    # Multigrams are the most-cornered cells; the vowel core is the innermost.
    ordered = setup._cells_by_corner_distance(cells)
    assert set(tri) == set(ordered[:n_tri])
    assert set(by_zone[(2, None, None)]) == set(ordered[n_tri:n_tri + n_di])
    cx, cy = board.cell_center(*board.center_cell())
    dist = lambda c: (c[0] - cx) ** 2 + (c[1] - cy) ** 2
    assert max(map(dist, core)) <= min(map(dist, rim))


def test_formation_disarms_the_vowel_guarantee_before_the_consonant_rim():
    setup = RecordingSetup(FakeBoard(6, 6))
    setup._rule_formation_fill_vowel_core_consonant_shell()
    # Armed for the core's cell count, then disarmed (0) before the rim is filled.
    assert setup.armed[0] > 0
    assert setup.armed[-1] == 0
    rim_index = [i for i, (_c, length, _a, cls) in enumerate(setup.placed)
                 if length == 1 and cls == "consonant"][0]
    core_index = [i for i, (_c, length, _a, cls) in enumerate(setup.placed)
                  if length == 1 and cls == "vowel"][0]
    assert core_index < rim_index
