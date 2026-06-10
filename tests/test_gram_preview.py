"""Decoding of player-dictionary variations for the dictionary-screen preview.

Only parse_variation is exercised here -- building the actual square/hex shapes
needs a live GL context, so that is left to in-app playtesting.
"""
from views.gram_preview import parse_variation


def test_square_variation():
    shape, grams = parse_variation("ca|t")
    assert shape == "square"
    assert grams == [("CA", False), ("T", False)]


def test_hex_variation():
    shape, grams = parse_variation("do/g")
    assert shape == "hex"
    assert grams == [("DO", False), ("G", False)]


def test_obstacle_grams_flagged():
    shape, grams = parse_variation("ge|[ar]")
    assert shape == "square"
    assert grams == [("GE", False), ("AR", True)]


def test_hex_with_obstacle():
    shape, grams = parse_variation("a/[re]/a")
    assert shape == "hex"
    assert grams == [("A", False), ("RE", True), ("A", False)]


def test_single_gram_defaults_to_square():
    # No separator -> grid type is unknown; default to square, whole word as one
    # gram.
    shape, grams = parse_variation("solo")
    assert shape == "square"
    assert grams == [("SOLO", False)]
