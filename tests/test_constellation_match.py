"""Constellation matcher: a typed word is assembled from grams sitting anywhere
on the board, each cell used once, whole grams only (see ConstellationMixin)."""

from views import game_screen as gs


class _Gram:
    def __init__(self, text, is_wild=False):
        self.text = text
        self.is_wild = is_wild


class _Board:
    """Minimal board: a {(x, y): text} map, optional wild set. Enough surface for
    _constellation_match (occupied_cells / gram_at)."""

    def __init__(self, cells, wild=()):
        self.cells = dict(cells)
        self._wild = set(wild)

    def occupied_cells(self):
        return list(self.cells)

    def gram_at(self, x, y):
        if (x, y) not in self.cells:
            return None
        return _Gram(self.cells[(x, y)], is_wild=(x, y) in self._wild)


def _engine(board, fossils=()):
    g = gs.GameScreen.__new__(gs.GameScreen)
    g._board = board
    g._fossilized_cells = set(fossils)
    g._fossil_is_wall_rule = g._rule_fossil_block_is_wall
    g._fossil_word_ok_rule = g._rule_fossil_block_word_ok
    return g


def _cellsets(results):
    return {frozenset(fw.path) for fw in results}


def test_assembles_from_scattered_unigrams():
    g = _engine(_Board({(0, 0): "C", (5, 5): "A", (2, 7): "T", (9, 1): "X"}))
    res = g._constellation_match("CAT", limit=24)
    assert len(res) == 1
    fw = res[0]
    assert fw.word == "CAT"
    assert fw.segments == ["C", "A", "T"]
    assert fw.path == [(0, 0), (5, 5), (2, 7)]   # spelled order, not board order


def test_multigram_and_unigram_segmentations_both_found():
    # PLANET from [PL][A][NET] or [P][LA][NE][T] -- two distinct assemblies.
    g = _engine(_Board({
        (0, 0): "PL", (1, 0): "A", (2, 0): "NET",
        (0, 1): "P", (1, 1): "LA", (2, 1): "NE", (3, 1): "T",
    }))
    res = g._constellation_match("PLANET", limit=24)
    segs = {tuple(fw.segments) for fw in res}
    assert ("PL", "A", "NET") in segs
    assert ("P", "LA", "NE", "T") in segs
    # Longest-gram-first search surfaces the fewest-cell assembly first.
    assert len(res[0].path) <= len(res[-1].path)


def test_each_cell_used_once():
    # Only one "A" on the board, so "AAA" cannot be assembled.
    g = _engine(_Board({(0, 0): "A", (1, 0): "B"}))
    assert g._constellation_match("AAA", limit=24) == []


def test_distinct_cell_bindings_are_distinct_results():
    # Two "T" cells => two constellations for "AT".
    g = _engine(_Board({(0, 0): "A", (1, 0): "T", (2, 0): "T"}))
    res = g._constellation_match("AT", limit=24)
    assert _cellsets(res) == {frozenset({(0, 0), (1, 0)}),
                              frozenset({(0, 0), (2, 0)})}


def test_unspellable_word_returns_empty():
    g = _engine(_Board({(0, 0): "C", (1, 0): "A", (2, 0): "T"}))
    assert g._constellation_match("DOG", limit=24) == []


def test_fossil_block_cell_is_unusable():
    # (2, 0) "T" is fossilized and the block rule walls it off => no CAT.
    g = _engine(_Board({(0, 0): "C", (1, 0): "A", (2, 0): "T"}), fossils={(2, 0)})
    assert g._constellation_match("CAT", limit=24) == []


def test_limit_caps_results():
    # Four "A" cells, word "AA" => 4*3 = 12 ordered bindings; cap at 3.
    cells = {(i, 0): "A" for i in range(4)}
    g = _engine(_Board(cells))
    assert len(g._constellation_match("AA", limit=3)) == 3
