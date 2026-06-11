"""Decoding of player-dictionary variations for the dictionary-screen preview.

Only parse_variation is exercised here -- building the actual square/hex shapes
(and the wild emblem sprite) needs a live GL context, so that is left to in-app
playtesting.

Each parsed gram is (text, is_obstacle, is_mission, is_wild).
"""
from views.gram_preview import parse_variation


def test_square_variation():
    shape, grams = parse_variation("ca|t")
    assert shape == "square"
    assert grams == [("CA", False, False, False), ("T", False, False, False)]


def test_hex_variation():
    shape, grams = parse_variation("do/g")
    assert shape == "hex"
    assert grams == [("DO", False, False, False), ("G", False, False, False)]


def test_obstacle_grams_flagged():
    shape, grams = parse_variation("ge|[ar]")
    assert shape == "square"
    assert grams == [("GE", False, False, False), ("AR", True, False, False)]


def test_mission_grams_flagged():
    shape, grams = parse_variation("g|<o>|al")
    assert shape == "square"
    assert grams == [
        ("G", False, False, False),
        ("O", False, True, False),
        ("AL", False, False, False),
    ]


def test_hex_with_obstacle():
    shape, grams = parse_variation("a/[re]/a")
    assert shape == "hex"
    assert grams == [
        ("A", False, False, False),
        ("RE", True, False, False),
        ("A", False, False, False),
    ]


def test_hex_with_mission():
    shape, grams = parse_variation("a/<re>/a")
    assert shape == "hex"
    assert grams == [
        ("A", False, False, False),
        ("RE", False, True, False),
        ("A", False, False, False),
    ]


def test_single_gram_defaults_to_square():
    # No separator -> grid type is unknown; default to square, whole word as one
    # gram.
    shape, grams = parse_variation("solo")
    assert shape == "square"
    assert grams == [("SOLO", False, False, False)]


def test_wild_gram_flagged():
    shape, grams = parse_variation("c|?oa?|t")
    assert shape == "square"
    assert grams == [
        ("C", False, False, False),
        ("OA", False, False, True),
        ("T", False, False, False),
    ]


def test_obstacle_and_wild_gram():
    # The obstacle bracket sits outside the wild marker: "[?a?]".
    shape, grams = parse_variation("c|[?a?]|t")
    assert shape == "square"
    assert grams == [
        ("C", False, False, False),
        ("A", True, False, True),
        ("T", False, False, False),
    ]


def test_mission_and_wild_gram():
    # The mission bracket sits outside the wild marker: "<?a?>".
    shape, grams = parse_variation("c|<?a?>|t")
    assert shape == "square"
    assert grams == [
        ("C", False, False, False),
        ("A", False, True, True),
        ("T", False, False, False),
    ]


def test_hex_wild_gram():
    shape, grams = parse_variation("[br]/?ea?/ch")
    assert shape == "hex"
    assert grams == [
        ("BR", True, False, False),
        ("EA", False, False, True),
        ("CH", False, False, False),
    ]
