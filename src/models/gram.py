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
