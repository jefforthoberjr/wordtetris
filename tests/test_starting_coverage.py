"""Starting-coverage word enumeration: every word formable from a board's initial
grams, counted combinatorially (C(m, k) for k slots of a gram the board has m of).

These exercise the pure algorithm only -- building the gram multiset from a live
board, and the blocking game-start wiring, are left to in-app playtesting.
"""
from starting_coverage import (
    any_word_formable,
    coverage_for_word,
    rules_allow_spellable,
    write_coverage_csv,
)

# The configured word-length rule (rule_word_min3letters_min2cells) reduced to the
# only two things it reads: word length and cell count.
ACCEPT = lambda word, n_cells: len(word) >= 3 and n_cells >= 2
SEP = "/"


def _combos(word, grams):
    total, combos = coverage_for_word(word, grams, max(len(g) for g in grams), ACCEPT, SEP)
    return total, dict(combos)


def test_identical_cells_are_combinations_not_permutations():
    # Two interchangeable S-cells: "kiss" fills both S slots = C(2,2) = 1 way.
    total, combos = _combos("KISS", {"K": 1, "I": 1, "S": 2})
    assert total == 1
    assert combos == {"k/i/s/s": 1}


def test_single_slot_picks_either_copy():
    # "sat" uses one S slot with two S-cells available = C(2,1) = 2 ways.
    total, combos = _combos("SAT", {"S": 2, "A": 1, "T": 1})
    assert total == 2
    assert combos == {"s/a/t": 2}


def test_multi_gram_groupings_sum_to_total():
    # Mirrors the cat example: 5 + 25 + 4 = 34 across three groupings.
    total, combos = _combos("CAT", {"C": 5, "A": 1, "T": 1, "CA": 4, "AT": 5})
    assert total == 34
    assert combos == {"c/a/t": 5, "c/at": 25, "ca/t": 4}


def test_min_cells_excludes_single_gram_word():
    # A lone "CAT" cell can't form the word: needs >= 2 cells.
    total, combos = _combos("CAT", {"CAT": 1, "C": 1, "A": 1, "T": 1})
    assert total == 1  # only c/a/t survives
    assert combos == {"c/a/t": 1}


def test_insufficient_copies_gives_zero():
    # Only one S-cell, "kiss" needs two -> not formable.
    total, _ = _combos("KISS", {"K": 1, "I": 1, "S": 1})
    assert total == 0


def test_csv_includes_zero_coverage_words(tmp_path):
    path = tmp_path / "cov.csv"
    grams = {"C": 1, "A": 1, "T": 1}
    stats = write_coverage_csv(path, ["cat", "dog", "to"], grams, ACCEPT, SEP)
    lines = path.read_text().splitlines()
    assert lines[0] == "word,word_length,is_present,do_rules_allow_spellable,total_count,combos"
    assert lines[1] == "cat,3,true,true,1,c/a/t:1"
    # Zero-coverage word still listed: length filled, is_present false, but the
    # rules still allow it (3 letters) -- it's just missing grams. Empty combos.
    assert lines[2] == "dog,3,false,true,0,"
    # Too short for rule_word_min3letters_min2cells: the rules forbid it outright,
    # so do_rules_allow_spellable is false (and it's of course not present).
    assert lines[3] == "to,2,false,false,0,"
    assert stats == {"words": 3, "covered": 1, "combos": 1}


def test_any_word_formable_finds_a_word():
    # CAT is in the word list and the grams spell it -> formable (early-exit True).
    assert any_word_formable(["dog", "cat"], {"C": 1, "A": 1, "T": 1}, ACCEPT) is True


def test_any_word_formable_none_when_grams_exhausted():
    # No listed word can be cut from a lone Q -> the auto-end trigger.
    assert any_word_formable(["cat", "dog"], {"Q": 1}, ACCEPT) is False


def test_any_word_formable_respects_length_rule():
    # AT is the only spellable word but rule_word_min3letters_min2cells forbids it,
    # so the board counts as having no formable word.
    assert any_word_formable(["at"], {"A": 1, "T": 1}, ACCEPT) is False


def test_any_word_formable_empty_grams():
    assert any_word_formable(["cat"], {}, ACCEPT) is False


def test_any_word_formable_needs_whole_grams():
    # HAT's letters are present, but only as the whole gram "HA" plus "T": HAT is
    # cut into HA+T (formable). ART shares no gram cut -> not formable from these.
    assert any_word_formable(["hat"], {"HA": 1, "T": 1}, ACCEPT) is True
    assert any_word_formable(["art"], {"HA": 1, "T": 1}, ACCEPT) is False


def test_rules_allow_spellable_respects_length_rule():
    # ACCEPT here is rule_word_min3letters_min2cells.
    assert rules_allow_spellable("cat", ACCEPT) is True   # 3 letters, splittable
    assert rules_allow_spellable("to", ACCEPT) is False   # too short, ever
    assert rules_allow_spellable("a", ACCEPT) is False
