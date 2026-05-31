class Gram:
    """The contents of a single cell: a short run of letters.

    A cell can hold 1-4 letters: a unigram, digram, trigram, or quadgram.
    There is no need for separate classes per length; a digram is just a Gram
    whose text is 2 letters long. For now this is a thin wrapper around its
    string, but later it will carry extra metadata (scoring, color, etc.).
    """
    def __init__(self, text):
        self._text = text.upper()

    @property
    def text(self):
        return self._text

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


# Active font-sizing rule (swap to rule_gram_font_fixed to disable resizing).
_gram_font_size_rule = rule_gram_font_scale_by_length


def gram_font_size(base_size, gram):
    """Font size for `gram` in a cell whose single-letter font is `base_size`,
    via the active sizing rule. One place to swap how grams resize."""
    return _gram_font_size_rule(base_size, gram)
