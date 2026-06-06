import os


# Valid-word corpus for the word-clearing rule. One word per line; we hold the
# whole list as an uppercase set, matching how letters are stored on the board.
_DICT_PATH = os.path.join(
    os.path.dirname(__file__), 'dictionaries',
    'spellingDictionary20k-nocompound.txt'
)
_words = None
_prefixes = None


def _word_set():
    global _words
    if _words is None:
        words = set()
        with open(_DICT_PATH, 'r') as f:
            for line in f:
                word = line.strip().upper()
                if word:
                    words.add(word)
        _words = words
    return _words


def _prefix_set():
    # Every prefix of every word, so a path-walking search can stop the moment
    # the letters so far can't begin any word (a poor man's trie).
    global _prefixes
    if _prefixes is None:
        prefixes = set()
        for word in _word_set():
            for i in range(1, len(word) + 1):
                prefixes.add(word[:i])
        _prefixes = prefixes
    return _prefixes


def is_word(text):
    """True if `text` is a valid dictionary word (case-insensitive)."""
    return text.upper() in _word_set()


def is_prefix(text):
    """True if `text` begins some dictionary word (case-insensitive)."""
    return text.upper() in _prefix_set()


def _is_subpath(short, long):
    """True if cell path `short` appears as a contiguous run inside `long`."""
    n = len(short)
    for t in range(len(long) - n + 1):
        if long[t:t + n] == short:
            return True
    return False


def select_maximal_paths(paths):
    """Drop any word path that is a contiguous sub-path of a longer one.

    `paths` is an iterable of cell paths (each a sequence of positions).
    Returns the surviving paths as tuples. Two paths that merely overlap
    (neither contained in the other, e.g. FIN and INK sharing IN) are both
    kept, so a cell can be cleared by several branching words at once.
    """
    unique = list({tuple(p) for p in paths})
    result = []
    for i, path in enumerate(unique):
        contained = False
        for j, other in enumerate(unique):
            if i != j and len(path) < len(other) and _is_subpath(path, other):
                contained = True
                break
        if not contained:
            result.append(path)
    return result
