import os

from config import CONFIG


# Valid-word corpus for the word-clearing rule. One word per line; we hold the
# whole list as an uppercase set, matching how letters are stored on the board.
# The MAIN file is chosen by config.yaml dictionary.word_source (headword list
# vs the inflection-expanded list); see build_expanded_dictionary.py.
#
# An optional OBSCURE tier (dictionary.include_obscure) adds the exclusively-rare
# 2of12-sourced words (expandedAllowedWords_obscure.txt, built disjoint from the
# main tier by build_obscure_dictionary.py). When on, is_word / is_prefix accept
# both tiers; is_obscure() reports whether a word came ONLY from the obscure tier
# -- what the +2 hint surcharge and the orange "new obscure word" highlight key on.
_DICTS_DIR = os.path.join(os.path.dirname(__file__), 'dictionaries')
_WORD_SOURCE_FILES = {
    'headwords_20k': 'spellingDictionary20k-nocompound.txt',
    'expanded': 'expandedAllowedWords.txt',
}
_DEFAULT_WORD_SOURCE = 'headwords_20k'
_OBSCURE_FILE = 'expandedAllowedWords_obscure.txt'
_words = None            # main tier (the configured word_source)
_obscure = None          # obscure tier (loaded on first use)
_active = None           # main tier, unioned with obscure when enabled
_prefixes = None


def _dict_path():
    source = CONFIG.get('dictionary', {}).get('word_source', _DEFAULT_WORD_SOURCE)
    filename = _WORD_SOURCE_FILES.get(source, _WORD_SOURCE_FILES[_DEFAULT_WORD_SOURCE])
    return os.path.join(_DICTS_DIR, filename)


def _include_obscure():
    return bool(CONFIG.get('dictionary', {}).get('include_obscure', False))


def _load_upper(path):
    words = set()
    with open(path, 'r') as f:
        for line in f:
            word = line.strip().upper()
            if word:
                words.add(word)
    return words


def _word_set():
    """The MAIN tier only (the configured word_source), regardless of the
    obscure toggle -- so is_obscure can tell the tiers apart."""
    global _words
    if _words is None:
        _words = _load_upper(_dict_path())
    return _words


def _obscure_set():
    """The obscure tier, or an empty set when the toggle is off (so nothing is
    read from disk unless it is actually in play)."""
    global _obscure
    if _obscure is None:
        if _include_obscure():
            _obscure = _load_upper(os.path.join(_DICTS_DIR, _OBSCURE_FILE))
        else:
            _obscure = set()
    return _obscure


def _active_word_set():
    """The words the clearing rule actually accepts: the main tier, plus the
    obscure tier when dictionary.include_obscure is on."""
    global _active
    if _active is None:
        _active = _word_set() | _obscure_set()
    return _active


def _prefix_set():
    # Every prefix of every ACTIVE word, so a path-walking search can stop the
    # moment the letters so far can't begin any word (a poor man's trie).
    global _prefixes
    if _prefixes is None:
        prefixes = set()
        for word in _active_word_set():
            for i in range(1, len(word) + 1):
                prefixes.add(word[:i])
        _prefixes = prefixes
    return _prefixes


def all_words():
    """The full uppercase word set (the shared instance, not a copy) -- for bulk
    analysis like the starting-coverage enumeration. Includes the obscure tier
    when enabled. Callers must not mutate it."""
    return _active_word_set()


def is_word(text):
    """True if `text` is a valid dictionary word (case-insensitive), across every
    active tier."""
    return text.upper() in _active_word_set()


def is_obscure(text):
    """True if `text` is valid ONLY via the obscure tier -- present there and not
    in the main tier. Always False when the obscure toggle is off (empty tier)."""
    up = text.upper()
    return up in _obscure_set() and up not in _word_set()


def is_prefix(text):
    """True if `text` begins some active dictionary word (case-insensitive)."""
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
