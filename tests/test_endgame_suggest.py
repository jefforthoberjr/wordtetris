"""The endgame typing bonus spell-checks against the TARGET WORDS only.

The in-play engine (game_screen.spell_suggest) scans the whole dictionary; that
would be wrong here, since a word outside the target list cannot be typed for
score. These pin the closed-list engine: one word, nearest by plain Levenshtein
distance, ties alphabetical, already-typed words excluded.
"""
from models.spelling_suggester import levenshtein, nearest_word
from views.endgame_typing import (rule_endgame_suggest_nearest_target,
                                  rule_endgame_suggest_off)

_TARGETS = ["CAT", "CART", "BATTER", "SCIENCE"]


def test_levenshtein_is_plain_edit_distance():
    assert levenshtein("KITTEN", "SITTING") == 3
    assert levenshtein("CAT", "CAT") == 0
    assert levenshtein("", "CAT") == 3


def test_suggests_the_nearest_target():
    assert nearest_word("battr", _TARGETS) == "BATTER"
    assert nearest_word("sience", _TARGETS) == "SCIENCE"


def test_ties_break_alphabetically():
    # CATT is one edit from both CAT and CART; CART wins on the alphabet.
    assert nearest_word("catt", _TARGETS) == "CART"


def test_never_suggests_a_word_outside_the_list():
    # BUTTON is a perfectly good dictionary word the in-play engine would offer;
    # it is not a target, so the only thing on offer is a target.
    assert nearest_word("buttin", _TARGETS) in _TARGETS


def test_max_distance_withholds_a_hopeless_guess():
    assert nearest_word("zzzzzzzz", _TARGETS, 3) == ""
    assert nearest_word("zzzzzzzz", _TARGETS, 99) != ""


def test_empty_input_or_empty_list_suggests_nothing():
    assert nearest_word("", _TARGETS) == ""
    assert nearest_word("cat", []) == ""


def test_rule_seam():
    assert rule_endgame_suggest_off("battr", _TARGETS, 3) == ""
    assert rule_endgame_suggest_nearest_target("battr", _TARGETS, 3) == "BATTER"


def test_already_typed_words_are_not_candidates():
    """A banked word is worth nothing now, so the pane never names it. A bare
    instance is enough -- _remaining_words touches only the target list."""
    from views.endgame_typing import EndgameTyping
    view = EndgameTyping.__new__(EndgameTyping)
    view._targets = [{"word": "CART", "done": True},
                     {"word": "CAT", "done": False}]
    assert view._remaining_words() == ["CAT"]
    # Same misspelling as the tie test, but CART is spent -- so CAT is offered.
    assert rule_endgame_suggest_nearest_target(
        "catt", view._remaining_words(), 3) == "CAT"
