import os


# A "wild vowel" cell stands for a run of 1-3 vowels drawn from this set. The
# same six letters are what the scrabble_with_allvowelswild gram-pick rule swaps
# out for a wild cell.
VOWELS = "AEIOUY"
_VOWEL_SET = set(VOWELS)

# The realistic expansions a wild cell can take: every 1-3 letter vowel run that
# actually occurs in the word dictionary (see gen_wild_vowel_expansions.py),
# rather than all 258 theoretical combinations. The pathfinder branches over
# these. Loaded once, lazily.
_EXPANSIONS = None
_EXPANSIONS_PATH = os.path.join(
    os.path.dirname(__file__), "dictionaries", "wild_vowel_expansions.txt"
)


def is_vowel(letter):
    """True if `letter` is one of the wild-vowel letters (case-insensitive)."""
    return letter.upper() in _VOWEL_SET


def wild_expansions():
    """The list of vowel runs a wild cell may expand to (uppercase), loaded from
    the precomputed dictionary-derived file. The same shared list every wild
    cell uses, so it is loaded once and reused."""
    global _EXPANSIONS
    if _EXPANSIONS is None:
        runs = []
        with open(_EXPANSIONS_PATH) as f:
            for line in f:
                run = line.strip().upper()
                if run:
                    runs.append(run)
        _EXPANSIONS = runs
    return _EXPANSIONS
