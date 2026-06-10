import os
from pathlib import Path


# The player's running collection of every word they've ever cleared, across all
# games -- the long-term "find every word in the dictionary" goal. Persisted as a
# plain txt file, one word per line, alphabetical order. Each line also carries
# the gram groupings the word was cleared with, so the dictionary screen can
# re-render what the cells looked like. Loaded once at startup and autosaved the
# instant a new word -- or a new grouping of a known word -- is added.
#
# Line format: a ";"-separated list of the word's unique variations.
#   A variation joins its per-cell grams with "|" (cleared in a square game) or
#   "/" (a hex game); an obstacle gram is wrapped in "[ ]". The bare word is
#   recovered by stripping "| / [ ]". Examples:
#     ca|t           -- "cat", square, grams ca + t
#     b|a|rf;ba|rf   -- "barf", two known square groupings
#     ge|[ar]        -- "gear", square, the "ar" gram came from an obstacle
#     a/[re]/a       -- "area", hex
_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "player_dictionary.txt"

# The separator / annotation characters used inside a variation; stripping them
# from a variation string leaves the bare word.
_GRAM_MARKUP = "|/[]"


def word_of_variation(variation):
    """The bare lowercase word a variation encodes, with the gram separators and
    obstacle brackets removed (e.g. "ge|[ar]" -> "gear")."""
    bare = variation
    for ch in _GRAM_MARKUP:
        bare = bare.replace(ch, "")
    return bare.lower()


class PlayerDictionary:
    """A persistent collection of the words the player has cleared, each mapped
    to the unique gram groupings it has been cleared with. Words are stored
    lowercase; the on-disk file is rewritten (sorted, one word per line) every
    time a genuinely new word -- or a new grouping of a known word -- is added,
    so it stays a readable alphabetical list and survives a crash mid-write via
    an atomic temp-file replace."""

    def __init__(self, path=_DEFAULT_PATH):
        self._path = Path(path)
        # word -> list of unique variation strings, in the order first seen.
        self._variations = {}
        if self._path.exists():
            with open(self._path) as f:
                for line in f:
                    self._load_line(line)

    def _load_line(self, line):
        text = line.strip()
        if text:
            for variation in text.split(";"):
                variation = variation.strip()
                if variation:
                    self._record(word_of_variation(variation), variation)

    def _record(self, word, variation):
        """Add `variation` under `word`, creating the word if new and skipping a
        grouping already known. Returns True only when `word` itself is new, so a
        caller can tell when the collected-word count actually grew (a fresh
        grouping of a known word does not count)."""
        is_new_word = word not in self._variations
        if is_new_word:
            self._variations[word] = []
        if variation is not None and variation not in self._variations[word]:
            self._variations[word].append(variation)
        return is_new_word

    def __len__(self):
        """Total number of distinct words the player has collected."""
        return len(self._variations)

    def words(self):
        """The player's words as a sorted (alphabetical) list -- a fresh snapshot
        the dictionary screen can page through without it changing underneath the
        viewer."""
        return sorted(self._variations.keys())

    def variations(self, word):
        """The unique gram groupings `word` has been cleared with, as a list of
        variation strings (empty if the word is unknown or was recorded without
        any grouping)."""
        return list(self._variations.get(word.lower(), []))

    def contains(self, word):
        """True if `word` is already in the player's dictionary (case-insensitive)."""
        return word.lower() in self._variations

    def add(self, word, variation=None):
        """Record that the player cleared `word`, optionally with the gram
        grouping `variation`. Returns True if the WORD was new (the collected
        count grew, so the UI lists it green), False if the player already had it
        -- even when this call appends a new grouping of it. Autosaves whenever
        something actually changed."""
        w = word.lower()
        had_word = w in self._variations
        had_variation = variation is None or variation in self._variations.get(w, [])
        is_new_word = self._record(w, variation)
        if not had_word or not had_variation:
            self._save()
        return is_new_word

    def _save(self):
        # Atomic write: build the full sorted list in a temp file, then replace
        # the real one in a single rename, so an interrupted save can't truncate
        # or corrupt the player's collection. One line per word: its variations
        # joined by ";" (a word recorded without any grouping writes as the bare
        # word, so the line still round-trips on load).
        tmp = self._path.with_name(self._path.name + ".tmp")
        with open(tmp, "w") as f:
            for word in sorted(self._variations.keys()):
                variations = self._variations[word]
                if variations:
                    line = ";".join(variations)
                else:
                    line = word
                f.write(line + "\n")
        os.replace(tmp, self._path)
