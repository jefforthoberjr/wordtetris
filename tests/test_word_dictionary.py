from models.word_dictionary import is_word, is_prefix, select_maximal_paths
from models.hex_domino import HEX_UP_RIGHT, HEX_DOWN, HEX_DOWN_RIGHT
from models.hex_grid import (
    rule_snake_rightanddown, rule_snake_rightanddown_nosharptwist,
)


def test_is_word_case_insensitive():
    assert is_word("cat")
    assert is_word("CAT")
    assert not is_word("zzz")


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
