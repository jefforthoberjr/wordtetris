"""Spelling-suggestion engine (game_screen.spell_suggest).

Sits between the pure matcher (models/spell_check.py) and the game: reads the
spell_check tunables from config.yaml, scans the dictionary for close
misspellings of a typed non-word, ranks them, and returns the best few words.

The "which engine" rule seam is here at the top: SUGGEST_RULES maps the
config rule name to a suggest(typed) -> [word, ...] function. game_screen picks
one via select_rule and calls it; swapping engines (e.g. a future Metaphone)
means adding a function here and one line in config.yaml.
"""
import csv
import os

from config import CONFIG
from models.word_dictionary import all_words, is_word
from models import spell_check


# --- rule seam (game_screen.spell_suggest) ----------------------------------

def rule_spell_suggest_off(typed):
    """Suggestions disabled: never offer a "did you mean?"."""
    return []


def rule_spell_suggest_constrained(typed):
    """The restricted edit-distance engine: scan the dictionary for close,
    same-shape misspellings of `typed`, ranked best-first, capped to
    max_suggestions. Returns a list of uppercase words (possibly empty)."""
    return _suggest_constrained(typed)


SUGGEST_RULES = {
    "rule_spell_suggest_off": rule_spell_suggest_off,
    "rule_spell_suggest_constrained": rule_spell_suggest_constrained,
}


# --- config-backed cost table -----------------------------------------------

_costs = None
_suffix_tails = None
_settings = None


def _config():
    """Lazily assemble the matcher cost table + tail set from the spell_check
    config block (falling back to the module defaults for any missing key)."""
    global _costs, _suffix_tails, _settings
    if _costs is None:
        block = CONFIG.get("spell_check", {})
        costs = dict(spell_check.DEFAULT_COSTS)
        for key in ("min_word_length", "max_suggestions", "base_distance",
                    "distance_per_vowel_run", "max_transpositions"):
            if key in block:
                costs[key] = block[key]
        for group in ("vowel", "consonant", "transposition"):
            if group in block:
                merged = dict(spell_check.DEFAULT_COSTS[group])
                merged.update(block[group])
                costs[group] = merged
        tails = block.get("suffix_tails")
        if tails:
            _suffix_tails = set(t.upper() for t in tails)
        else:
            _suffix_tails = spell_check.DEFAULT_SUFFIX_TAILS
        _costs = costs
        _settings = {
            "max_suggestions": costs["max_suggestions"],
            "min_word_length": costs["min_word_length"],
            "max_length_delta": block.get("max_length_delta", 3),
        }
    return _costs, _suffix_tails, _settings


# --- frequency tiebreaker (Google unigram counts) ---------------------------

_freq = None


def _freq_table():
    """Lazily load unigram_freq.csv (word,count) as {UPPERWORD: count}. Used only
    as the final tiebreak between equally-close suggestions (commoner wins)."""
    global _freq
    if _freq is None:
        freq = {}
        path = os.path.join(
            os.path.dirname(__file__), 'dictionaries', 'unigram_freq.csv')
        with open(path, 'r') as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) >= 2:
                    word = row[0].strip().upper()
                    try:
                        count = int(row[1])
                    except ValueError:
                        count = 0
                    if word:
                        freq[word] = count
        _freq = freq
    return _freq


# --- the scan ----------------------------------------------------------------

def _suggest_constrained(typed):
    """Rank close dictionary words for `typed`: keep every candidate the matcher
    accepts, sort by (exoticness, edits, -frequency), return the top words."""
    word = typed.strip().upper()
    costs, tails, settings = _config()
    result = []
    if len(word) >= settings["min_word_length"] and not is_word(word):
        freq = _freq_table()
        delta = settings["max_length_delta"]
        scored = []
        for candidate in all_words():
            # Cheap length pre-filter before the O(n*m) matcher: an accepted
            # alignment can't change length by more than its edit count.
            if abs(len(candidate) - len(word)) <= delta:
                hit = spell_check.evaluate(word, candidate, costs, tails)
                if hit is not None:
                    scored.append((
                        hit["exoticness"], hit["edits"],
                        -freq.get(candidate, 0), candidate))
        scored.sort()
        for entry in scored[:settings["max_suggestions"]]:
            result.append(entry[3])
    return result
