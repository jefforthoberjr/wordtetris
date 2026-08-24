"""Stocking the idea belt's ring AT the board (idea_belt.stock_category_weight.*).

The belt used to deal blind: a random slice of the deck, knowing nothing about
what the player could actually make. Stocking scans the board once per game per
weighted CATEGORY -- after the opening formation is down, which is the only moment
there IS a board -- and fills each category's share of the ring from the deck words
that scan matched.

What has to stay true: the ring is always FULL and never all-one-picture (a board
that can make three deck words must not deal those three forty times), targeted
pictures are SPREAD around the loop rather than dealt in one block, and a board
that matches nothing still gets a normal blind belt instead of a blank pane.
"""
import config
from models import idea_pool
from views.idea_belt import IdeaBelt
from views import game_screen as gs


DECK = [
    {"image": "", "emoji": "1", "word1": "ant", "word2": ""},
    {"image": "", "emoji": "2", "word1": "bee", "word2": ""},
    {"image": "", "emoji": "3", "word1": "cat", "word2": ""},
    {"image": "", "emoji": "4", "word1": "dog", "word2": ""},
    {"image": "", "emoji": "5", "word1": "elk", "word2": ""},
    {"image": "", "emoji": "6", "word1": "fox", "word2": ""},
]


def _with_rules(**overrides):
    rules = config.CONFIG.setdefault("rules", {})
    for key, value in overrides.items():
        rules[key.replace("__", ".")] = value


def _restore():
    base = config.load_config()
    config.CONFIG.clear()
    config.CONFIG.update(base)


def _pool(size, targets, share=0.7, category="spellable_any_gram"):
    """A ring stocked from ONE category holding `share` of the weight, the rest
    blind -- the shape most of these tests care about."""
    _with_rules(**{
        "idea_belt__order": "rule_idea_order_deck",
        "idea_belt__stock_category_weight__spellable_multigram": 0,
        "idea_belt__stock_category_weight__spellable_by_path": 0,
        "idea_belt__stock_category_weight__spellable_any_gram": 0,
        "idea_belt__stock_category_weight__blind": round((1.0 - share) * 100),
        "idea_belt__stock_category_weight__" + category: round(share * 100),
    })
    return idea_pool.IdeaPool(size=size, deck=DECK, stock={category: targets})


# --- the blend (idea_belt.stock_category_weight.*) ------------------------
def test_the_ring_is_full_and_mixes_targeted_with_blind_picks():
    try:
        pool = _pool(10, ["ANT", "BEE", "CAT", "DOG"], share=0.5)
        assert pool.size() == 10
        # Half the ring targeted (5 wanted, 4 distinct exist -> 4), the blind side
        # fills the rest, so un-makeable pictures still ride the belt.
        assert pool.targeted_count() == 4
        assert pool.active_count() == 10
    finally:
        _restore()


def test_targeted_pictures_are_spread_around_the_ring_not_dealt_in_one_block():
    """The belt is a conveyor showing a few items at a time: one block of makeable
    pictures followed by a block of impossible ones would read as two different
    belts. Interleaving keeps every window of the loop mixed."""
    try:
        pool = _pool(12, ["ANT", "BEE"], share=0.5)
        spots = [i for i, w in enumerate(pool.words()) if w in ("ANT", "BEE")]
        # Two targets in a 12-slot ring land apart, not side by side.
        assert len(spots) == 2
        assert spots[1] - spots[0] > 1
    finally:
        _restore()


def test_a_board_with_few_matches_does_not_deal_the_same_picture_over_and_over():
    """The targeted side is capped at the DISTINCT pictures that matched -- it is
    never cycled to fill its quota, or a three-word board would deal a ring of the
    same three pictures on repeat. The blind side takes the slack."""
    try:
        pool = _pool(12, ["ANT"], share=1.0)
        assert pool.size() == 12
        assert pool.targeted_count() == 1
        assert len(set(pool.words())) > 1
    finally:
        _restore()


def test_a_board_that_matches_nothing_still_deals_a_full_blind_ring():
    """The belt must never go blank: no matches means an ordinary belt, not an
    empty pane."""
    try:
        pool = _pool(8, [], share=1.0)
        assert pool.size() == 8
        assert pool.targeted_count() == 0
    finally:
        _restore()


def test_no_stock_at_all_deals_exactly_as_it_did_before():
    """stock=None is the all-blind ring: the original deal path, untouched."""
    try:
        _with_rules(idea_belt__order="rule_idea_order_deck")
        blind = idea_pool.IdeaPool(size=6, deck=DECK)
        explicit = idea_pool.IdeaPool(size=6, deck=DECK, stock=None)
        assert blind.words() == explicit.words()
        assert explicit.targeted_count() == 0
    finally:
        _restore()


# --- the belt's side of it -------------------------------------------------
def _belt(targeted):
    """A bare belt (no GL context) with just the fields the dealing path reads --
    and no slots, so _rewind's re-layout has nothing to place."""
    belt = IdeaBelt.__new__(IdeaBelt)
    belt._deck = DECK
    belt._targeted = targeted
    belt._unused_ring = True
    belt._slots = []
    belt._slot_count = 0
    belt._scroll = 0.0
    belt._visible, belt._offset, belt._y, belt._height, belt._band = 4, 15, 0, 400, 100
    belt._pool = idea_pool.IdeaPool(deck=[], reason="awaiting board")
    return belt


def test_a_targeted_belt_opens_empty_and_is_filled_by_the_deal():
    """The panes build the belt long before the board exists, so a targeted belt
    has nothing to deal from yet. It opens on an empty ring (which draws nothing)
    and GameScreen fills it once the formation is down."""
    try:
        _with_rules(**{
            "idea_belt__order": "rule_idea_order_deck",
            "idea_belt__pool_size": 6,
            "idea_belt__stock_category_weight__spellable_multigram": 0,
            "idea_belt__stock_category_weight__spellable_by_path": 0,
            "idea_belt__stock_category_weight__spellable_any_gram": 50,
            "idea_belt__stock_category_weight__blind": 50,
        })
        belt = _belt(targeted=True)
        assert belt._pool.size() == 0
        # Three slots wanted (half of six), two distinct pictures matched -- the
        # cap holds and the blind side fills the other four.
        assert belt.restock({"spellable_any_gram": ["ANT", "BEE"]}) == {
            "spellable_any_gram": 2}
        assert belt._pool.size() == 6
    finally:
        _restore()


def test_a_targeted_belt_deals_no_blind_ring_on_a_new_game():
    """reset() runs before the new game's board is built, so for a targeted belt it
    must only rewind -- the ring comes from the deal after the formation. A blind
    belt still re-deals there, as it always did."""
    try:
        _with_rules(idea_belt__order="rule_idea_order_deck", idea_belt__pool_size=6)
        targeted = _belt(targeted=True)
        targeted._unused_ring = False
        empty = targeted._pool
        targeted.reset()
        assert targeted._pool is empty        # untouched, awaiting the deal
        blind = _belt(targeted=False)
        blind._unused_ring = False
        old = blind._pool
        blind.reset()
        assert blind._pool is not old
        assert blind._pool.size() == 6
    finally:
        _restore()


def test_deck_words_are_uppercased_and_deduplicated():
    """What the board scan filters. Two deck rows naming the same word offer it
    once."""
    belt = _belt(targeted=True)
    belt._deck = DECK + [{"image": "", "emoji": "7", "word1": "Ant", "word2": "bee"}]
    assert belt.deck_words() == ["ANT", "BEE", "CAT", "DOG", "ELK", "FOX"]


# --- the board scans (idea_belt.stock_category_weight.*) ------------------
class _FakeGram:
    def __init__(self, text):
        self.text = text
        self.is_wild = False


class _GramBoard:
    """A board that only answers the two questions the gram-supply scan asks:
    which cells are occupied, and what gram each carries. No geometry -- the
    supply scan deliberately ignores where the cells sit."""

    def __init__(self, grams):
        self._grams = dict(grams)

    def occupied_cells(self):
        return list(self._grams.keys())

    def gram_at(self, x, y):
        text = self._grams.get((x, y))
        return None if text is None else _FakeGram(text)


def _screen(grams):
    g = gs.GameScreen.__new__(gs.GameScreen)
    g._board = _GramBoard(grams)
    g._fossil_is_wall_rule = lambda cell: False
    g._word_length_rule = lambda word, path: len(word) >= 3
    return g


def test_the_supply_scan_targets_only_the_deck_words_the_board_can_make():
    """A/N/T and C/A/T share the A cell, so only one of them can be made at a
    time -- the scan reports what the gram supply covers, and BEE (no B, no E) is
    never targeted."""
    screen = _screen({(0, 0): "A", (1, 0): "N", (2, 0): "T", (3, 0): "C"})
    words = ["ANT", "BEE", "CAT", "DOG"]
    targets = screen._rule_idea_stock_category_spellable_any_gram(words)
    assert "BEE" not in targets and "DOG" not in targets
    assert "ANT" in targets or "CAT" in targets


def test_an_empty_board_targets_nothing_rather_than_everything():
    screen = _screen({})
    assert screen._rule_idea_stock_category_spellable_any_gram(["ANT", "BEE"]) == []


def test_the_multigram_scan_only_targets_words_that_use_the_fat_cells():
    """SH + ARK is exactly the cut a new player never invents, so SHARK is stocked;
    ASK spells out of three single letters on the same board and is NOT -- even
    though the plain gram-supply scan takes it."""
    screen = _screen({(0, 0): "SH", (1, 0): "ARK", (2, 0): "A",
                      (3, 0): "S", (4, 0): "K"})
    words = ["SHARK", "ASK"]
    assert screen._rule_idea_stock_category_spellable_multigram(words) == ["SHARK"]
    assert set(screen._rule_idea_stock_category_spellable_any_gram(words)) == {
        "SHARK", "ASK"}


def test_two_digrams_count_as_multigram_use_but_one_does_not():
    """The rule is 1+ trigram OR 2+ digrams: SH + AR + K leans on the board twice
    over, while a lone digram is the sort of cut players already reach for."""
    screen = _screen({(0, 0): "SH", (1, 0): "AR", (2, 0): "K",
                      (3, 0): "AS", (4, 0): "K"})
    assert "SHARK" in screen._rule_idea_stock_category_spellable_multigram(["SHARK"])
    # ASK = AS + K is a single digram -- one multigram is not enough.
    assert screen._rule_idea_stock_category_spellable_multigram(["ASK"]) == []


def test_an_empty_board_targets_nothing_in_the_multigram_scan_either():
    assert _screen({})._rule_idea_stock_category_spellable_multigram(["ANT"]) == []


def test_stocking_hands_each_weighted_category_scan_to_the_belt():
    """The wiring: deck words in, one scan per weighted category, ring out. With no
    category weighted, nothing is scanned and the belt keeps the blind ring it
    already dealt itself."""
    class _Belt:
        def __init__(self):
            self.given = None

        def deck_words(self):
            return ["ANT", "BEE"]

        def restock(self, stock):
            self.given = stock
            return {c: len(w) for c, w in stock.items()}

    try:
        _with_rules(**{
            "idea_belt__stock_category_weight__spellable_multigram": 30,
            "idea_belt__stock_category_weight__spellable_by_path": 0,
            "idea_belt__stock_category_weight__spellable_any_gram": 70,
            "idea_belt__stock_category_weight__blind": 0,
        })
        screen = _screen({})
        screen._idea_belt = _Belt()
        screen._idea_stock_category_rules = {
            "spellable_multigram": lambda words: ["ANT"],
            "spellable_by_path": lambda words: ["BEE"],
            "spellable_any_gram": lambda words: ["ANT", "BEE"],
        }
        screen._stock_idea_belt()
        # The zero-weight category is never even scanned.
        assert screen._idea_belt.given == {"spellable_multigram": ["ANT"],
                                           "spellable_any_gram": ["ANT", "BEE"]}

        _with_rules(**{
            "idea_belt__stock_category_weight__spellable_multigram": 0,
            "idea_belt__stock_category_weight__spellable_any_gram": 0,
        })
        screen._idea_belt = _Belt()
        screen._stock_idea_belt()
        assert screen._idea_belt.given is None

        # Belt off: nothing to stock, and nothing to crash on.
        screen._idea_belt = None
        screen._stock_idea_belt()
    finally:
        _restore()


def test_a_word_is_spent_on_the_narrowest_category_that_claimed_it():
    """Categories overlap -- every multigram word is also gram-supplied -- so the
    multigram quota must be paid from words the broad category then does NOT count
    again, or a narrow category's slots vanish into a broad one's."""
    try:
        _with_rules(**{
            "idea_belt__order": "rule_idea_order_deck",
            "idea_belt__stock_category_weight__spellable_multigram": 50,
            "idea_belt__stock_category_weight__spellable_by_path": 0,
            "idea_belt__stock_category_weight__spellable_any_gram": 50,
            "idea_belt__stock_category_weight__blind": 0,
        })
        pool = idea_pool.IdeaPool(size=4, deck=DECK, stock={
            "spellable_multigram": ["ANT", "BEE"],
            "spellable_any_gram": ["ANT", "BEE", "CAT", "DOG"],
        })
        assert pool.stock_counts() == {"spellable_multigram": 2,
                                       "spellable_any_gram": 2}
        assert set(pool.words()) == {"ANT", "BEE", "CAT", "DOG"}
    finally:
        _restore()


def test_the_weights_split_the_ring_into_whole_slots():
    """Relative weights, largest-remainder: 1:3 over 8 slots is 2 stocked and 6
    blind, and the quotas always add up to a FULL ring."""
    try:
        pool = _pool(8, ["ANT", "BEE", "CAT", "DOG"], share=0.25)
        assert pool.size() == 8
        assert pool.targeted_count() == 2
    finally:
        _restore()
