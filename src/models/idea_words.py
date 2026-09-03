"""The word->emoji lookup behind the right-click-for-an-idea cell hint
(game_screen.idea_hint).

Deliberately SEPARATE from models/idea_pool.py even though both read the same
generated CSV. The idea belt is a conveyor of pre-picked prompts dealt once per
game; this is a lookup answered on demand, for one cell, from the whole file --
different lifetime, different question, so they share the file format and nothing
else. Either can be repointed at its own mapping without disturbing the other.

The file is `word,image,emoji,fit` (see tools/emoji_classify): one row per
dictionary word, the emoji a classification pass gave it, and how honestly that
picture names the word (3 depicts / 2 suggests / 1 arbitrary). Only rows at or
above idea_hint.min_fit are loaded -- a hint is worthless if the picture does not
say the word.

Loaded once and cached: ~2,800 rows at fit 3, and the hint is asked for on a
click, so re-reading the CSV per click would be pure I/O.
"""
import csv
from pathlib import Path

from config import CONFIG


# {word (upper) -> emoji}, built on first use. None until then; a game mode swap
# calls reset() so the next lookup re-reads under the new rules.
_words = None


def deck_path():
    """Resolved path of the hint's word file (idea_hint.deck). Sits beside the
    belt's decks -- one folder owns the generated word/emoji data."""
    name = CONFIG.get("rules", {}).get("idea_hint.deck", "words_emoji.csv")
    return Path(__file__).parent.parent / "assets" / "idea_belt" / name


def reset():
    """Drop the cache so the next lookup re-reads the file. Called when a game
    mode is applied, since idea_hint.deck / min_fit may have changed."""
    global _words
    _words = None


def _load():
    """Read the word file into {word -> emoji}, filtered by idea_hint.min_fit.

    Comment lines are skipped so the file stays hand-editable, and a row with no
    fit column counts as the best fit (a hand-built mapping need not carry one).
    A missing file yields an empty map rather than raising: the hint then simply
    never fires, which is the right failure for a cosmetic feature."""
    rules = CONFIG.get("rules", {})
    min_fit = int(rules.get("idea_hint.min_fit", 3))
    words = {}
    path = deck_path()
    if not path.exists():
        return words
    with open(path, encoding="utf-8") as f:
        lines = []
        for line in f:
            if not line.strip().startswith("#"):
                lines.append(line)
        for row in csv.DictReader(lines):
            word = (row.get("word") or "").strip().upper()
            emoji = (row.get("emoji") or "").strip()
            fit = (row.get("fit") or "").strip()
            keep = True
            if fit:
                keep = int(fit) >= min_fit
            if word and emoji and keep:
                words[word] = emoji
    return words


def words_by_emoji():
    """{word -> emoji} for every word the hint may offer. Cached."""
    global _words
    if _words is None:
        _words = _load()
    return _words


def candidate_words():
    """Every word the hint may offer, as a list -- the candidate pool the board
    scan filters. Sorted so a run is reproducible from the session seed (a dict's
    order would still be stable in practice, but the seeded pick must not depend
    on that)."""
    return sorted(words_by_emoji())


def emoji_for(word):
    """The emoji for `word`, or "" when the file does not carry it."""
    return words_by_emoji().get(word.upper(), "")
