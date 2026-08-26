"""Deck FORMATS behind the idea belt (idea_belt.deck_format / min_fit).

Two shapes of deck file feed one belt: the hand-written picture rows
(image,emoji,word1,word2) and the generated word rows (word,image,emoji,fit) the
emoji classification pass produces. What has to stay true: the fit filter runs at
LOAD so no unfair prompt reaches any layer above, and a 21k-row word deck does not
break the dedupe rule that a 110-row picture deck was written against.
"""
import csv
import os

import config
from models import idea_pool


WORD_ROWS = [
    ("shark", "", "\U0001F988", "3"),
    ("brick", "", "\U0001F9F1", "3"),
    ("imagine", "", "\U0001F4AD", "2"),
    ("nonetheless", "", "\U0001F937", "1"),
    ("panda", "", "\U0001F43C", "3"),
    ("cub", "", "\U0001F43C", "3"),      # same picture as panda, different word
]


def _with_rules(**overrides):
    rules = config.CONFIG.setdefault("rules", {})
    for key, value in overrides.items():
        rules[key.replace("__", ".")] = value


def _restore():
    base = config.load_config()
    config.CONFIG.clear()
    config.CONFIG.update(base)


def _word_deck_file(tmp_path):
    path = os.path.join(tmp_path, "words.csv")
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["word", "image", "emoji", "fit"])
        for row in WORD_ROWS:
            writer.writerow(row)
    return path


# --- the fit filter (idea_belt.min_fit) -----------------------------------
def test_the_fit_filter_drops_unfair_prompts_at_load(tmp_path):
    """A fit-1 row is a child asked to spell NONETHELESS from a shrug. It must not
    survive the loader -- not the ring, not deck_words(), not the board scan."""
    try:
        _with_rules(idea_belt__deck_format="rule_idea_deck_word_rows",
                    idea_belt__min_fit=3)
        rows = idea_pool.load_deck(_word_deck_file(str(tmp_path)))
        words = [row["word1"] for row in rows]
        assert "shark" in words and "panda" in words
        assert "imagine" not in words and "nonetheless" not in words
    finally:
        _restore()


def test_lowering_min_fit_widens_the_deck(tmp_path):
    try:
        _with_rules(idea_belt__deck_format="rule_idea_deck_word_rows",
                    idea_belt__min_fit=2)
        rows = idea_pool.load_deck(_word_deck_file(str(tmp_path)))
        words = [row["word1"] for row in rows]
        assert "imagine" in words
        assert "nonetheless" not in words
    finally:
        _restore()


def test_picture_rows_still_load_the_hand_written_way(tmp_path):
    """The original format is untouched: one row, two words, no fit column."""
    path = os.path.join(str(tmp_path), "pictures.csv")
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["image", "emoji", "word1", "word2"])
        writer.writerow(["", "\U0001F988", "shark", "fish"])
    try:
        _with_rules(idea_belt__deck_format="rule_idea_deck_picture_rows")
        rows = idea_pool.load_deck(path)
        assert rows == [{"image": "", "emoji": "\U0001F988",
                         "word1": "shark", "word2": "fish"}]
    finally:
        _restore()


# --- dedupe timing on a word-indexed deck ---------------------------------
def test_dedupe_no_longer_throws_away_the_words_the_board_can_make(tmp_path):
    """The regression a 21k-row deck introduces: dedupe keeps the FIRST word of
    each picture, and on an alphabetical word deck that word is arbitrary. Deduping
    the whole deck up front would spend the panda picture on CUB (sorts first) and
    then find no match for the board's PANDA. Dedupe must run AFTER the board
    filter."""
    try:
        _with_rules(idea_belt__deck_format="rule_idea_deck_word_rows",
                    idea_belt__min_fit=3,
                    idea_belt__order="rule_idea_order_deck",
                    idea_belt__dedupe="rule_idea_dedupe_on",
                    idea_belt__stock_category_weight__spellable_multigram=0,
                    idea_belt__stock_category_weight__spellable_by_path=0,
                    idea_belt__stock_category_weight__spellable_any_gram=100,
                    idea_belt__stock_category_weight__blind=0)
        deck = idea_pool.load_deck(_word_deck_file(str(tmp_path)))
        pool = idea_pool.IdeaPool(size=4, deck=deck,
                                  stock={"spellable_any_gram": ["panda"]})
        assert "PANDA" in pool.words()
        assert pool.stock_counts() == {"spellable_any_gram": 1}
    finally:
        _restore()


def test_one_picture_never_rides_the_ring_twice_under_dedupe(tmp_path):
    """Dedupe moved into the blend, so it now has to hold ACROSS categories --
    PANDA and CUB share a picture, each matched by a DIFFERENT category, and only
    one of them may be stocked.

    (A ring whose deck is smaller than pool_size still repeats the pictures it has,
    as it always did -- dedupe thins the candidate list, it does not stop the ring
    cycling. That is why this checks the words stocked, not the ring slots.)"""
    try:
        _with_rules(idea_belt__deck_format="rule_idea_deck_word_rows",
                    idea_belt__min_fit=3,
                    idea_belt__order="rule_idea_order_deck",
                    idea_belt__dedupe="rule_idea_dedupe_on",
                    idea_belt__stock_category_weight__spellable_multigram=50,
                    idea_belt__stock_category_weight__spellable_by_path=0,
                    idea_belt__stock_category_weight__spellable_any_gram=50,
                    idea_belt__stock_category_weight__blind=0)
        deck = idea_pool.load_deck(_word_deck_file(str(tmp_path)))
        pool = idea_pool.IdeaPool(size=4, deck=deck, stock={
            "spellable_multigram": ["panda"],
            "spellable_any_gram": ["cub", "shark"],
        })
        words = set(pool.words())
        assert "SHARK" in words
        assert ("PANDA" in words) != ("CUB" in words)
        assert pool.stock_counts() == {"spellable_multigram": 1,
                                       "spellable_any_gram": 1}
    finally:
        _restore()
