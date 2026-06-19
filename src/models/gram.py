from config import select_rule


class Gram:
    """The contents of a single cell: a short run of letters.

    A cell can hold 1-4 letters: a unigram, digram, trigram, or quadgram.
    There is no need for separate classes per length; a digram is just a Gram
    whose text is 2 letters long. For now this is a thin wrapper around its
    string, but later it will carry extra metadata (scoring, color, etc.).
    """
    def __init__(self, text, is_wild=False):
        self._text = text.upper()
        # A wild-vowel gram: its cell stands for a run of 1-3 vowels chosen when a
        # word is spelled (see models.wild_vowel). It has no fixed text -- it
        # renders as the vowel emblem, not a letter -- so _text stays empty.
        self._is_wild = is_wild

    @property
    def text(self):
        return self._text

    @property
    def is_wild(self):
        return self._is_wild

    def __len__(self):
        return len(self._text)


# --- font sizing rules -------------------------------------------------
# A multi-letter gram must shrink to stay inside one cell. `base_size` is the
# font a single letter uses in that cell, so length 1 always keeps it. Swap the
# active rule on the _gram_font_size_rule line below.

def rule_gram_font_fixed(base_size, gram):
    """No resize: every gram keeps the cell's single-letter font (the original
    behavior). Multi-letter grams overflow the cell; kept for restoring."""
    return base_size


def rule_gram_font_scale_by_length(base_size, gram):
    """Shrink the font as the gram grows so it fits the cell. Each extra letter
    scales the base down; length 1 -> base, 2 -> ~0.59, 3 -> ~0.42, 4 -> ~0.32."""
    length = len(gram)
    scaled = base_size / (1 + 0.7 * (length - 1))
    return int(scaled)


def rule_gram_font_scale_single_as_double(base_size, gram):
    """Like scale_by_length, but a single letter takes the 2-letter size instead
    of the full base, so a unigram no longer towers over a digram. Lengths >= 2
    are unchanged; only length 1 differs: 1 -> ~0.59 (was base), 2 -> ~0.59,
    3 -> ~0.42, 4 -> ~0.32."""
    length = max(len(gram), 2)
    scaled = base_size / (1 + 0.7 * (length - 1))
    return int(scaled)


# Active font-sizing rule, chosen by the YAML key gram.font_size.
_GRAM_FONT_SIZE_RULES = {
    "rule_gram_font_fixed": rule_gram_font_fixed,
    "rule_gram_font_scale_by_length": rule_gram_font_scale_by_length,
    "rule_gram_font_scale_single_as_double": rule_gram_font_scale_single_as_double,
}
_gram_font_size_rule = select_rule("gram.font_size", _GRAM_FONT_SIZE_RULES)


def gram_font_size(base_size, gram):
    """Font size for `gram` in a cell whose single-letter font is `base_size`,
    via the active sizing rule. One place to swap how grams resize."""
    return _gram_font_size_rule(base_size, gram)
