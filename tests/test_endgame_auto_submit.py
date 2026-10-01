"""Banking a word with no ENTER (endgame.auto_submit).

Only the DECISION is exercised here -- "is this typed text ready to commit?" The
commit itself runs the ordinary submit path (scoring, flash, finish check), which
needs a live GL context to build, so that is left to in-app playtesting.
"""
from views.endgame_typing import (rule_endgame_auto_submit_off,
                                  rule_endgame_auto_submit_exact,
                                  rule_endgame_auto_submit_unambiguous)


def _targets(*words):
    """Targets as (word, done) pairs; a bare string is a word still to be typed."""
    targets = []
    for word in words:
        if isinstance(word, tuple):
            targets.append({"word": word[0], "done": word[1]})
        else:
            targets.append({"word": word, "done": False})
    return targets


def test_off_rule_never_submits_however_complete_the_word():
    targets = _targets("CAT", "DOG")
    for typed in ("", "C", "CA", "CAT"):
        assert rule_endgame_auto_submit_off(typed, targets) is False


def test_exact_submits_on_the_last_letter_and_not_before():
    targets = _targets("CAT", "DOG")
    assert [rule_endgame_auto_submit_exact(t, targets)
            for t in ("C", "CA", "CAT")] == [False, False, True]


def test_exact_ignores_a_word_already_banked():
    """A typed word is only worth committing while it is still a target -- retyping
    a banked word must fall through to the ordinary (scoreless) ENTER path."""
    targets = _targets(("CAT", True), "DOG")
    assert rule_endgame_auto_submit_exact("CAT", targets) is False


def test_exact_never_fires_on_a_non_target():
    targets = _targets("CAT")
    assert rule_endgame_auto_submit_exact("COT", targets) is False
    # Nor on an empty field, which would bank nothing on every keystroke.
    assert rule_endgame_auto_submit_exact("", targets) is False


def test_exact_takes_the_prefix_word_out_from_under_the_longer_one():
    """The documented cost of ..._exact: CAT commits while CATCH is still to type."""
    targets = _targets("CAT", "CATCH")
    assert rule_endgame_auto_submit_exact("CAT", targets) is True


def test_unambiguous_waits_while_a_longer_word_is_still_to_type():
    targets = _targets("CAT", "CATCH")
    assert rule_endgame_auto_submit_unambiguous("CAT", targets) is False
    # The longer word itself has nothing past it, so it still banks itself.
    assert rule_endgame_auto_submit_unambiguous("CATCH", targets) is True


def test_unambiguous_submits_once_the_longer_word_is_banked():
    targets = _targets("CAT", ("CATCH", True))
    assert rule_endgame_auto_submit_unambiguous("CAT", targets) is True


def test_unambiguous_submits_a_word_nothing_extends():
    targets = _targets("CAT", "DOG")
    assert rule_endgame_auto_submit_unambiguous("CAT", targets) is True
    assert rule_endgame_auto_submit_unambiguous("CA", targets) is False
