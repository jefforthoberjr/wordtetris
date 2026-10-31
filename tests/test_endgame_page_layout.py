"""The paged endgame layout keeps its fixed font unless a word cannot fit a row.

A stand-in page supplies the measurements, since the real PageDisplay measures text
with a live GL context; that part is left to in-app playtesting.
"""
from views.endgame_displays import rule_endgame_page_layout_two_then_one_paged


class _Page:
    """Every letter is as wide as the font size, and each row is as tall."""

    def fixed_font_size(self, usable_h):
        return 20

    def min_font_size(self):
        return 6

    def row_height(self, size):
        return size

    def word_width(self, target, size):
        return len(target["word"]) * size

    def widest(self, targets, size):
        widest = 0
        for target in targets:
            widest = max(widest, self.word_width(target, size))
        return widest

    def column_room(self, col_width):
        return col_width


def _targets(*words):
    targets = []
    for word in words:
        targets.append({"word": word})
    return targets


def _layout(*words):
    return rule_endgame_page_layout_two_then_one_paged(
        _Page(), _targets(*words), 200, 160)


def test_words_that_fit_a_row_keep_the_fixed_font():
    font_size, _columns, _indices, _slots = _layout("CAT", "ELEPHANTS")[0]
    assert font_size == 20


def test_a_word_too_long_for_a_row_shrinks_the_font_until_it_fits():
    font_size, _columns, _indices, _slots = _layout("CAT", "A" * 20)[0]
    assert font_size == 10


def test_every_page_shares_the_shrunken_font():
    words = ["CAT"] * 40 + ["A" * 20]
    pages = _layout(*words)
    assert len(pages) > 1
    for font_size, _columns, _indices, _slots in pages:
        assert font_size == 10


def test_font_stops_shrinking_at_the_minimum():
    font_size, _columns, _indices, _slots = _layout("A" * 100)[0]
    assert font_size == 6
