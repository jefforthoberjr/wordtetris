"""The idea belt's inventory: the shipped deck and the pre-picked ring.

The deck is hand-edited (and will be re-stacked often for playtests), so the
tests here mostly guard the things a hand edit can silently break: a word the
player could never type because it is not in the dictionary, and a ring whose
size or dedupe rule quietly stops holding.
"""
import config
from models import idea_pool
from models import word_dictionary


def _with_rules(**overrides):
    """Apply rule overrides onto CONFIG for one pool build. Values are restored
    by the test module's own copy below (each test re-reads a fresh base)."""
    rules = config.CONFIG.setdefault("rules", {})
    for key, value in overrides.items():
        rules[key.replace("__", ".")] = value


def _restore():
    base = config.load_config()
    config.CONFIG.clear()
    config.CONFIG.update(base)


def test_shipped_deck_words_are_in_the_dictionary():
    """Every belt word must be typeable: a click fills the field with it, and a
    word outside the dictionary would hand a young player a guaranteed reject."""
    deck = idea_pool.load_deck()
    assert len(deck) > 0
    missing = []
    for row in deck:
        for word in (row["word1"], row["word2"]):
            if word and not word_dictionary.is_word(word.upper()):
                missing.append(word)
    assert missing == []


def test_shipped_deck_rows_have_art_and_a_first_word():
    deck = idea_pool.load_deck()
    for row in deck:
        assert row["emoji"] or row["image"]
        assert row["word1"]


def test_ring_fills_to_pool_size():
    try:
        _with_rules(idea_belt__dedupe="rule_idea_dedupe_off")
        pool = idea_pool.IdeaPool(size=50)
        assert pool.size() == 50
        # The ring wraps in both directions -- both columns are windows onto one
        # loop, and a window may run off either end.
        assert pool.item_at(50).word == pool.item_at(0).word
        assert pool.item_at(-1).word == pool.item_at(49).word
    finally:
        _restore()


def test_dedupe_on_keeps_one_item_per_picture():
    deck = [
        {"image": "", "emoji": "A", "word1": "apple", "word2": "fruit"},
        {"image": "", "emoji": "B", "word1": "bear", "word2": "forest"},
    ]
    try:
        _with_rules(idea_belt__dedupe="rule_idea_dedupe_on",
                    idea_belt__order="rule_idea_order_deck")
        pool = idea_pool.IdeaPool(size=4, deck=deck)
        assert pool.words() == ["APPLE", "BEAR", "APPLE", "BEAR"]
    finally:
        _restore()


def test_dedupe_off_gives_every_word_its_own_item():
    deck = [{"image": "", "emoji": "A", "word1": "apple", "word2": "fruit"}]
    try:
        _with_rules(idea_belt__dedupe="rule_idea_dedupe_off",
                    idea_belt__order="rule_idea_order_deck")
        pool = idea_pool.IdeaPool(size=3, deck=deck)
        assert pool.words() == ["APPLE", "FRUIT", "APPLE"]
    finally:
        _restore()


def test_image_art_falls_back_to_the_emoji():
    """Image mode with a half-filled images/ folder still plays: a row with no
    image draws its emoji rather than dropping out of the deck."""
    deck = [{"image": "", "emoji": "A", "word1": "apple", "word2": ""},
            {"image": "bear.png", "emoji": "B", "word1": "bear", "word2": ""}]
    try:
        _with_rules(idea_belt__art="rule_idea_art_image",
                    idea_belt__order="rule_idea_order_deck")
        pool = idea_pool.IdeaPool(size=2, deck=deck)
        assert [pool.item_at(0).art, pool.item_at(1).art] == ["A", "bear.png"]
    finally:
        _restore()


def test_clearing_a_word_strikes_every_ring_copy_of_it():
    """One word, several ring positions (deck smaller than the ring): spelling it
    blanks them ALL, or the belt would keep prompting for a word the player has
    just spelled. A repeated ring holds the same item object at each position, so
    the strike is reported once and every position goes dark."""
    deck = [{"image": "", "emoji": "A", "word1": "apple", "word2": ""},
            {"image": "", "emoji": "B", "word1": "bear", "word2": ""}]
    try:
        _with_rules(idea_belt__dedupe="rule_idea_dedupe_off",
                    idea_belt__order="rule_idea_order_deck")
        pool = idea_pool.IdeaPool(size=4, deck=deck)
        assert pool.clear_word("APPLE") == ["A"]
        assert pool.active_count() == 2
        # The ring keeps its size and its order -- struck items stay in place and
        # simply stop drawing, so no slot re-indexes mid-scroll.
        assert pool.size() == 4
        assert pool.words() == ["APPLE", "BEAR", "APPLE", "BEAR"]
        assert [pool.item_at(i).cleared for i in range(4)] == [True, False, True, False]
    finally:
        _restore()


def test_clearing_the_same_word_twice_strikes_nothing_the_second_time():
    """Idempotence is what keeps the match bonus to one payment per word: the
    caller pays only when a strike is reported."""
    deck = [{"image": "", "emoji": "A", "word1": "apple", "word2": ""}]
    try:
        _with_rules(idea_belt__order="rule_idea_order_deck")
        pool = idea_pool.IdeaPool(size=2, deck=deck)
        assert pool.clear_word("apple") == ["A"]   # matched case-insensitively
        assert pool.clear_word("APPLE") == []
        assert pool.active_count() == 0
    finally:
        _restore()


def test_two_pictures_of_one_word_both_come_off():
    """Two deck rows can name the same word with different pictures; both are
    struck, so the belt never keeps prompting for an already-spelled word."""
    deck = [{"image": "", "emoji": "A", "word1": "apple", "word2": ""},
            {"image": "", "emoji": "B", "word1": "apple", "word2": ""}]
    try:
        _with_rules(idea_belt__dedupe="rule_idea_dedupe_off",
                    idea_belt__order="rule_idea_order_deck")
        pool = idea_pool.IdeaPool(size=2, deck=deck)
        assert pool.clear_word("APPLE") == ["A", "B"]
        assert pool.active_count() == 0
    finally:
        _restore()


def test_clearing_a_word_the_ring_never_held_strikes_nothing():
    deck = [{"image": "", "emoji": "A", "word1": "apple", "word2": ""}]
    try:
        _with_rules(idea_belt__order="rule_idea_order_deck")
        pool = idea_pool.IdeaPool(size=1, deck=deck)
        assert pool.clear_word("BEAR") == []
        assert pool.active_count() == 1
    finally:
        _restore()
