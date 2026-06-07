import os
from pathlib import Path


# The player's running collection of every word they've ever cleared, across all
# games -- the long-term "find every word in the dictionary" goal. Persisted as a
# plain txt file: all lowercase, one word per line, alphabetical order. Loaded
# once at startup and autosaved the instant a new word is added.
_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "player_dictionary.txt"


class PlayerDictionary:
    """A persistent set of words the player has collected. Words are stored
    lowercase; the on-disk file is rewritten (sorted, one word per line) every
    time a genuinely new word is added, so it stays a readable alphabetical list
    and survives a crash mid-write via an atomic temp-file replace."""

    def __init__(self, path=_DEFAULT_PATH):
        self._path = Path(path)
        self._words = set()
        if self._path.exists():
            with open(self._path) as f:
                for line in f:
                    word = line.strip().lower()
                    if word:
                        self._words.add(word)

    def __len__(self):
        """Total number of words the player has collected."""
        return len(self._words)

    def contains(self, word):
        """True if `word` is already in the player's dictionary (case-insensitive)."""
        return word.lower() in self._words

    def add(self, word):
        """Add `word`; return True if it was new (and autosave), False if the
        player already had it."""
        w = word.lower()
        if w in self._words:
            return False
        self._words.add(w)
        self._save()
        return True

    def _save(self):
        # Atomic write: build the full sorted list in a temp file, then replace
        # the real one in a single rename, so an interrupted save can't truncate
        # or corrupt the player's collection.
        tmp = self._path.with_name(self._path.name + ".tmp")
        with open(tmp, "w") as f:
            for w in sorted(self._words):
                f.write(w + "\n")
        os.replace(tmp, self._path)
