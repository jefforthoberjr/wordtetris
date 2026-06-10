"""Persistence of the player's collected words and their gram groupings.

PlayerDictionary stores each word with the unique variations it was cleared with
(grams joined by "|" square / "/" hex, obstacle grams wrapped in "[ ]"). These
cover the bare-word derivation, the new-word vs new-grouping distinction that
drives the green highlight, and a save/load round-trip.
"""
from models.player_dictionary import PlayerDictionary, word_of_variation


def test_word_of_variation_strips_markup():
    assert word_of_variation("ge|[ar]") == "gear"
    assert word_of_variation("a/[re]/a") == "area"
    assert word_of_variation("ca|t") == "cat"
    # Already-bare input is returned lowercased and unchanged.
    assert word_of_variation("DOG") == "dog"


def test_add_new_word_returns_true(tmp_path):
    d = PlayerDictionary(tmp_path / "dict.txt")
    assert d.add("cat", "ca|t") is True
    assert d.contains("cat")
    assert len(d) == 1
    assert d.variations("cat") == ["ca|t"]


def test_re_add_same_variation_is_noop(tmp_path):
    d = PlayerDictionary(tmp_path / "dict.txt")
    d.add("cat", "ca|t")
    # Same word, same grouping: not new, no duplicate stored.
    assert d.add("cat", "ca|t") is False
    assert d.variations("cat") == ["ca|t"]


def test_new_variation_of_known_word_stays_not_new(tmp_path):
    d = PlayerDictionary(tmp_path / "dict.txt")
    d.add("barf", "ba|rf")
    # Known word, fresh grouping: count didn't grow (False -> black), but the
    # grouping is appended.
    assert d.add("barf", "b|a|rf") is False
    assert d.variations("barf") == ["ba|rf", "b|a|rf"]
    assert len(d) == 1


def test_case_insensitive(tmp_path):
    d = PlayerDictionary(tmp_path / "dict.txt")
    d.add("Cat", "Ca|t")
    assert d.contains("CAT")
    assert d.add("cat", "ca|t") is False


def test_round_trip_save_and_load(tmp_path):
    path = tmp_path / "dict.txt"
    d = PlayerDictionary(path)
    d.add("cat", "ca|t")
    d.add("barf", "ba|rf")
    d.add("barf", "b|a|rf")
    d.add("gear", "ge|[ar]")
    d.add("dog", "do/g")

    reloaded = PlayerDictionary(path)
    assert reloaded.words() == ["barf", "cat", "dog", "gear"]
    assert reloaded.variations("barf") == ["ba|rf", "b|a|rf"]
    assert reloaded.variations("gear") == ["ge|[ar]"]
    assert reloaded.variations("dog") == ["do/g"]
    assert len(reloaded) == 4


def test_add_without_variation(tmp_path):
    # A word recorded with no grouping still counts and round-trips as the bare
    # word (no variations).
    path = tmp_path / "dict.txt"
    d = PlayerDictionary(path)
    assert d.add("solo") is True
    assert d.variations("solo") == []
    reloaded = PlayerDictionary(path)
    assert reloaded.contains("solo")
    assert reloaded.variations("solo") == ["solo"]
