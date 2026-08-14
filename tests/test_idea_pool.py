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
