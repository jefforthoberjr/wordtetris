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
from models.word_dictionary import all_words, is_word, is_obscure
from models import spell_check
from models import morpheme_check


# --- rule seam (game_screen.spell_suggest) ----------------------------------

def rule_spell_suggest_off(typed):
    """Suggestions disabled: never offer a "did you mean?"."""
    return []


def rule_spell_suggest_constrained(typed):
    """The restricted edit-distance engine: scan the dictionary for close,
    same-shape misspellings of `typed`, ranked best-first, capped to
    max_suggestions. Returns a list of uppercase words (possibly empty)."""
    return _suggest_constrained(typed)


def rule_spell_suggest_constrained_morpheme(typed):
    """The letter-level engine PLUS the morpheme-level engine
    (models/morpheme_check.py), merged and ranked together by exoticness under
    the shared max_suggestions cap. The morpheme engine runs in PARALLEL, so
    spell_check's pattern-violation rejections never block a morpheme candidate
    (e.g. ABSOLUTIONIST -> ABSOLUTION, a wrong-affix slip letters can't catch)."""
    return _suggest_constrained_morpheme(typed)


SUGGEST_RULES = {
    "rule_spell_suggest_off": rule_spell_suggest_off,
    "rule_spell_suggest_constrained": rule_spell_suggest_constrained,
    "rule_spell_suggest_constrained_morpheme": rule_spell_suggest_constrained_morpheme,
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
            "obscurity_extra_score": block.get("obscurity_extra_score", 2),
        }
    return _costs, _suffix_tails, _settings


def obscurity_surcharge(word_upper):
    """Extra exoticness a suggestion earns for being valid ONLY via the obscure
    tier -- config spell_check.obscurity_extra_score (default 2). Zero when the
    word is in the main tier or the obscure tier is off. Applied to BOTH the
    letter- and morpheme-level scans so obscure "did you mean?" words rank below
    equally-close common ones. (The CLI reuses this so its ranking matches.)"""
    extra = _config()[2]["obscurity_extra_score"]
    return extra if (extra and is_obscure(word_upper)) else 0


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

def _scan_constrained(word):
    """Every letter-level suggestion the matcher accepts for `word` (already
    uppercase, already known non-word), as a sorted list of
    (exoticness, edits, -frequency, WORD) rows. No max_suggestions cap here --
    the caller trims, so the combined engine can merge before trimming."""
    costs, tails, _settings = _config()
    freq = _freq_table()
    delta = _config()[2]["max_length_delta"]
    scored = []
    for candidate in all_words():
        # Cheap length pre-filter before the O(n*m) matcher: an accepted
        # alignment can't change length by more than its edit count.
        if abs(len(candidate) - len(word)) <= delta:
            hit = spell_check.evaluate(word, candidate, costs, tails)
            if hit is not None:
                exo = hit["exoticness"] + obscurity_surcharge(candidate)
                scored.append((
                    exo, hit["edits"], -freq.get(candidate, 0), candidate))
    scored.sort()
    return scored


def _suggest_constrained(typed):
    """Rank close dictionary words for `typed`: keep every candidate the matcher
    accepts, sort by (exoticness, edits, -frequency), return the top words."""
    word = typed.strip().upper()
    settings = _config()[2]
    if len(word) < settings["min_word_length"] or is_word(word):
        return []
    return [row[3] for row in _scan_constrained(word)[:settings["max_suggestions"]]]


# --- morpheme-level scan (models/morpheme_check.py) --------------------------

_morpheme_model = None


def _morpheme():
    """Lazily build the morpheme model (inventory + scores) from config."""
    global _morpheme_model
    if _morpheme_model is None:
        _morpheme_model = morpheme_check.build_model(
            CONFIG.get("morpheme_check", {}))
    return _morpheme_model


def _scan_morphemes(word):
    """Every real word within the morpheme cap of `word` (already uppercase), as
    a sorted list of (exoticness, distance, -frequency, WORD) rows -- the same
    shape as _scan_constrained so the two merge directly. `distance` (affix ops)
    stands in for the letter scan's `edits` as the secondary rank key."""
    model = _morpheme()
    freq = _freq_table()
    hits = morpheme_check.suggest(word, is_word, model, model["max_distance"])
    scored = []
    for cand, info in hits.items():
        up = cand.upper()
        exo = info["exoticness"] + obscurity_surcharge(up)
        scored.append((exo, info["distance"], -freq.get(up, 0), up))
    scored.sort()
    return scored


def _suggest_constrained_morpheme(typed):
    """Merge the letter-level and morpheme-level scans, dedup by word keeping the
    cheaper (exoticness, secondary, -freq) key, and return the top
    max_suggestions words. Both scans share one cap and one ranking."""
    word = typed.strip().upper()
    settings = _config()[2]
    if len(word) < settings["min_word_length"] or is_word(word):
        return []
    best = {}
    for exo, second, negf, cand in _scan_constrained(word) + _scan_morphemes(word):
        key = (exo, second, negf)
        if cand not in best or key < best[cand]:
            best[cand] = key
    ranked = sorted(key + (cand,) for cand, key in best.items())
    return [row[3] for row in ranked[:settings["max_suggestions"]]]


# --- closed-list nearest word (endgame.spell_suggest) ------------------------
# The endgame typing bonus does NOT use the engines above. There the player is
# copying words that are all on screen, from a short, known list -- so a
# suggestion drawn from the whole dictionary would offer a word that cannot be
# typed for score. These two functions are the whole endgame engine: plain
# (unweighted) Levenshtein distance against a caller-supplied candidate list.

def levenshtein(a, b):
    """Plain unweighted edit distance between two strings: the number of single
    character insertions, deletions or substitutions to turn `a` into `b`. The
    standard two-row DP -- no letter-class costs, no transposition, none of
    spell_check's shape constraints, because over a handful of candidates the
    nearest one is all we need."""
    if a == b:
        return 0
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1,          # delete from a
                               current[j - 1] + 1,       # insert into a
                               previous[j - 1] + (ca != cb)))  # substitute
        previous = current
    return previous[-1]


def nearest_word(typed, words, max_distance=None):
    """The single closest word in `words` to `typed`, or "" if there is none.

    Closest = smallest Levenshtein distance, ties broken ALPHABETICALLY so the
    same misspelling always names the same word (no frequency or exoticness
    ranking: every candidate here is equally typable for score). `max_distance`,
    when given, is the furthest a word may be and still be offered -- past it the
    player has typed something too far off for a guess to be a helpful hint.
    Comparison is case-insensitive; the returned word keeps its candidate
    spelling."""
    word = typed.strip().upper()
    best = ""
    best_distance = None
    if word:
        for candidate in words:
            distance = levenshtein(word, candidate.upper())
            if max_distance is not None and distance > max_distance:
                continue
            if (best_distance is None or distance < best_distance
                    or (distance == best_distance and candidate.upper() < best.upper())):
                best = candidate
                best_distance = distance
    return best
