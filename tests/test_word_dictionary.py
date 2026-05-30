from models.word_dictionary import is_word, longest_word_span


def _spans(text, anchor, old_indices):
    """Helper: build the is_old mask and run longest_word_span."""
    is_old = [i in old_indices for i in range(len(text))]
    return longest_word_span(text, anchor, is_old)


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
