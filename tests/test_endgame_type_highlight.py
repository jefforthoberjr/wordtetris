"""The live typing highlight over the endgame target words (endgame.type_highlight).

Only the MATCHING is exercised here -- drawing the lit/typo colors needs a live GL
context, so that is left to in-app playtesting. The rule writes two keys on every
target: "lit" (leading letters typed correctly) and "typo" (index of the one
mistyped letter, -1 for none).
"""
from views.endgame_typing import (rule_endgame_type_highlight_off,
                                  rule_endgame_type_highlight_prefix)


def _targets(*words):
    return [{"word": w, "done": False, "lit": 0, "typo": -1} for w in words]


def _state(targets):
    return [(t["word"], t["lit"], t["typo"]) for t in targets]


def test_off_rule_never_lights_anything():
    targets = _targets("CAT", "CATCH")
    rule_endgame_type_highlight_off("CA", targets)
    assert _state(targets) == [("CAT", 0, -1), ("CATCH", 0, -1)]


def test_every_matching_word_lights_together():
    targets = _targets("CAT", "CATCH", "DOG")
    rule_endgame_type_highlight_prefix("CA", targets)
    assert _state(targets) == [("CAT", 2, -1), ("CATCH", 2, -1), ("DOG", 0, -1)]


def test_the_field_narrows_to_one_word():
    targets = _targets("CAT", "CATCH", "DOG")
    rule_endgame_type_highlight_prefix("CATC", targets)
    assert _state(targets) == [("CAT", 0, -1), ("CATCH", 4, -1), ("DOG", 0, -1)]


def test_a_first_letter_matching_nothing_lights_nothing():
    targets = _targets("CAT", "DOG")
    rule_endgame_type_highlight_prefix("Z", targets)
    assert _state(targets) == [("CAT", 0, -1), ("DOG", 0, -1)]


def test_a_typo_keeps_the_good_prefix_and_marks_one_letter():
    targets = _targets("CAT", "CATCH")
    rule_endgame_type_highlight_prefix("CAR", targets)
    # CA was good on both; the R is wrong, so each word's third letter is the typo.
    assert _state(targets) == [("CAT", 2, 2), ("CATCH", 2, 2)]


def test_typing_on_past_a_typo_holds_the_same_highlight():
    targets = _targets("CAT")
    rule_endgame_type_highlight_prefix("CARRR", targets)
    assert _state(targets) == [("CAT", 2, 2)]


def test_backspacing_off_a_typo_clears_it():
    targets = _targets("CAT")
    rule_endgame_type_highlight_prefix("CA", targets)
    assert _state(targets) == [("CAT", 2, -1)]


def test_overtyping_a_finished_word_leaves_it_fully_lit():
    # PLANTS at PLANT: there is no further letter to mark, so nothing goes red.
    targets = _targets("PLANT")
    rule_endgame_type_highlight_prefix("PLANTS", targets)
    assert _state(targets) == [("PLANT", 5, -1)]


def test_a_word_already_typed_is_ignored():
    targets = _targets("CAT", "CATCH")
    targets[0]["done"] = True
    rule_endgame_type_highlight_prefix("CAT", targets)
    # CAT is banked, so only CATCH is still a candidate -- and CAT stays unlit.
    assert _state(targets) == [("CAT", 0, -1), ("CATCH", 3, -1)]


def test_an_empty_field_lights_nothing():
    targets = _targets("CAT")
    rule_endgame_type_highlight_prefix("", targets)
    assert _state(targets) == [("CAT", 0, -1)]
