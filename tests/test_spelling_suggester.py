from models.spelling_suggester import (
    rule_spell_suggest_constrained, rule_spell_suggest_off,
)


def test_suggests_real_dictionary_words():
    # Driving examples whose correct spelling is present in the 20k dict.
    # (APPALLED is intentionally absent from this dict, so appauled has no fix.)
    assert "APARTMENT" in rule_spell_suggest_constrained("appartment")
    assert "BUTTON" in rule_spell_suggest_constrained("buttin")
    assert "PRESCRIPTION" in rule_spell_suggest_constrained("perscripsion")
    assert "SCIENCE" in rule_spell_suggest_constrained("sience")
    assert "INDUCE" in rule_spell_suggest_constrained("induse")


def test_caps_to_max_suggestions():
    # Never more than the configured max (2).
    assert len(rule_spell_suggest_constrained("buttin")) <= 2


def test_no_suggestion_for_real_word():
    # A valid word isn't a misspelling, so nothing is offered.
    assert rule_spell_suggest_constrained("button") == []


def test_no_suggestion_for_short_word():
    assert rule_spell_suggest_constrained("cet") == []


def test_off_rule_returns_nothing():
    assert rule_spell_suggest_off("appauled") == []
