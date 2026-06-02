from models.word_dictionary import (
    is_word, is_prefix, longest_word_span, select_maximal_paths,
)
from models.hex_domino import HEX_UP_RIGHT, HEX_DOWN, HEX_DOWN_RIGHT
from models.hex_grid import (
    rule_snake_rightanddown, rule_snake_rightanddown_nosharptwist,
)


def _spans(text, anchor, old_indices):
    """Helper: one letter per cell. Build the is_old mask and run the span."""
    grams = list(text)
    is_old = [i in old_indices for i in range(len(grams))]
    return longest_word_span(grams, anchor, is_old)


def _spans_grams(grams, anchor, old_indices):
    """Helper for multi-letter cells: `grams` is the per-cell gram list."""
    is_old = [i in old_indices for i in range(len(grams))]
    return longest_word_span(grams, anchor, is_old)


def test_is_word_case_insensitive():
    assert is_word("cat")
    assert is_word("CAT")
    assert not is_word("zzz")


def test_simple_word_cleared():
    # "CAT": placed T (index 2) links to existing C, A.
    assert _spans("CAT", anchor=2, old_indices={0, 1}) == (0, 3)


def test_requires_a_pre_existing_cell():
    # "CAT" entirely from the just-placed piece (no old cell) -> no clear.
    assert _spans("CAT", anchor=1, old_indices=set()) is None


def test_anchor_must_be_covered():
    # "CATZ": CAT is a word but it does not cover the placed Z (index 3), and
    # nothing covering the Z is a word, so there is nothing to clear.
    assert _spans("CATZ", anchor=3, old_indices={0, 1, 2}) is None


def test_longest_word_wins():
    # "PEAT": placed A (index 2). PEA, EAT and PEAT are all words; the full
    # PEAT (length 4) beats the two length-3 substrings.
    assert is_word("peat")
    assert _spans("PEAT", anchor=2, old_indices={0, 1, 3}) == (0, 4)


def test_straddle_tie_breaks_to_earliest_start():
    # "AIRE" is not a word, but AIR and IRE both are and both cover the placed
    # I (index 1). Equal length -> clear the earlier one (AIR), never both.
    assert not is_word("aire")
    assert _spans("AIRE", anchor=1, old_indices={0, 2, 3}) == (0, 3)


def test_no_word_returns_none():
    assert _spans("XQZ", anchor=1, old_indices={0, 2}) is None


# --- multi-letter grams (a cell can hold several letters) ---

def test_multiletter_gram_forms_word():
    # Cells [TH, E] spell THE. Placed E (cell 1) links to old TH (cell 0).
    assert is_word("the")
    assert _spans_grams(["TH", "E"], anchor=1, old_indices={0}) == (0, 2)


def test_multiletter_span_returns_cell_indices():
    # Cells [S, TA, R] spell STAR; the span is the cell range (0, 3), not chars.
    # TAR (cells 1-3) is also a word but STAR is longer, so the full span wins.
    assert is_word("star")
    assert _spans_grams(["S", "TA", "R"], anchor=2, old_indices={0, 1}) == (0, 3)


def test_multiletter_longest_counts_letters():
    # [HE, A, T] = HEAT. Placed A (cell 1). AT (cells 1-3) is a word too, but
    # HEAT (4 letters) beats AT (2), so the longer multi-cell word clears.
    assert is_word("heat") and is_word("at")
    assert _spans_grams(["HE", "A", "T"], anchor=1, old_indices={0, 2}) == (0, 3)


def test_multiletter_no_partial_gram_word():
    # [A, TH]: the letters contain "AT", but that would split the TH gram, so it
    # is never matched. Nothing whole-cell here spells a word -> no clear.
    assert is_word("at") and not is_word("ath")
    assert _spans_grams(["A", "TH"], anchor=0, old_indices={1}) is None


# --- hex snake helpers: prefix lookup and maximal-path selection ---

def test_is_prefix():
    assert is_prefix("ca")    # begins CAT, CAB, ...
    assert is_prefix("cat")   # a whole word is also a prefix of itself
    assert not is_prefix("qz")


def test_maximal_drops_contained_subpath():
    cat = [(0, 0), (1, 0), (2, 0)]
    at = [(1, 0), (2, 0)]  # contiguous tail of cat -> dropped
    assert select_maximal_paths([cat, at]) == [tuple(cat)]


def test_maximal_keeps_overlapping_straddle():
    # FIN and INK share the IN run but neither contains the other -> keep both.
    fin = [(0, 0), (1, 0), (2, 0)]
    ink = [(1, 0), (2, 0), (3, 0)]
    result = select_maximal_paths([fin, ink])
    assert set(result) == {tuple(fin), tuple(ink)}


def test_maximal_dedupes_identical_paths():
    p = [(0, 0), (1, 0)]
    assert select_maximal_paths([p, list(p)]) == [tuple(p)]


def test_maximal_branching_paths_both_kept():
    # Same start, diverging routes (a down word and a right word) -> both kept.
    down = [(0, 0), (0, 1), (0, 2)]
    right = [(0, 0), (1, 0), (2, 0)]
    result = select_maximal_paths([down, right])
    assert set(result) == {tuple(down), tuple(right)}


# --- hex snake step rules ---

def test_snake_rightanddown_allows_all_three_always():
    for prev in (None, HEX_UP_RIGHT, HEX_DOWN, HEX_DOWN_RIGHT):
        assert set(rule_snake_rightanddown(prev)) == {
            HEX_UP_RIGHT, HEX_DOWN, HEX_DOWN_RIGHT,
        }


def test_nosharptwist_unrestricted_at_start():
    assert set(rule_snake_rightanddown_nosharptwist(None)) == {
        HEX_UP_RIGHT, HEX_DOWN, HEX_DOWN_RIGHT,
    }


def test_nosharptwist_forbids_down_after_upright():
    # up-right then down is a 120-degree kink -> down is dropped.
    allowed = rule_snake_rightanddown_nosharptwist(HEX_UP_RIGHT)
    assert HEX_DOWN not in allowed
    assert HEX_UP_RIGHT in allowed and HEX_DOWN_RIGHT in allowed


def test_nosharptwist_forbids_upright_after_down():
    allowed = rule_snake_rightanddown_nosharptwist(HEX_DOWN)
    assert HEX_UP_RIGHT not in allowed
    assert HEX_DOWN in allowed and HEX_DOWN_RIGHT in allowed


def test_nosharptwist_allows_gentle_turns_after_downright():
    # down-right -> any of the three is at most a 60-degree turn.
    assert set(rule_snake_rightanddown_nosharptwist(HEX_DOWN_RIGHT)) == {
        HEX_UP_RIGHT, HEX_DOWN, HEX_DOWN_RIGHT,
    }
