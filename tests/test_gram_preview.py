"""Decoding of player-dictionary variations for the dictionary-screen preview.

Only parse_variation is exercised here -- building the actual square/hex shapes
(and the wild emblem sprite) needs a live GL context, so that is left to in-app
playtesting.
"""
from views.gram_preview import parse_variation


def test_square_variation():
    shape, grams = parse_variation("ca|t")
    assert shape == "square"
    assert grams == [("CA", False, False), ("T", False, False)]


def test_hex_variation():
    shape, grams = parse_variation("do/g")
    assert shape == "hex"
    assert grams == [("DO", False, False), ("G", False, False)]


def test_obstacle_grams_flagged():
    shape, grams = parse_variation("ge|[ar]")
    assert shape == "square"
    assert grams == [("GE", False, False), ("AR", True, False)]


def test_hex_with_obstacle():
    shape, grams = parse_variation("a/[re]/a")
    assert shape == "hex"
    assert grams == [("A", False, False), ("RE", True, False), ("A", False, False)]


def test_single_gram_defaults_to_square():
    # No separator -> grid type is unknown; default to square, whole word as one
    # gram.
    shape, grams = parse_variation("solo")
    assert shape == "square"
    assert grams == [("SOLO", False, False)]


def test_wild_gram_flagged():
    shape, grams = parse_variation("c|?oa?|t")
    assert shape == "square"
    assert grams == [("C", False, False), ("OA", False, True), ("T", False, False)]


def test_obstacle_and_wild_gram():
    # The obstacle bracket sits outside the wild marker: "[?a?]".
    shape, grams = parse_variation("c|[?a?]|t")
    assert shape == "square"
    assert grams == [("C", False, False), ("A", True, True), ("T", False, False)]


def test_hex_wild_gram():
    shape, grams = parse_variation("[br]/?ea?/ch")
    assert shape == "hex"
    assert grams == [("BR", True, False), ("EA", False, True), ("CH", False, False)]
