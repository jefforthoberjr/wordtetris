"""Spelling-suggestion matcher (game_screen.spell_suggest).

A "restricted" edit-distance scorer: given a word the player typed that is NOT
in the dictionary, decide whether a real dictionary word is a close-enough
"did you mean?" suggestion, and how exotic the misspelling is (for ranking).

This module is PURE logic -- no game, no I/O, no config loading. The cost table
and the morpheme-ending list are passed in (DEFAULT_COSTS / DEFAULT_SUFFIX_ENDINGS
here are sensible standalone defaults; the live game overrides them from
config.yaml, see the rule seam in word_dictionary / game_screen). Swapping this
whole algorithm out later (e.g. real Metaphone) means writing another module with
the same `evaluate(typed, candidate, ...)` entry point.

The model walks both words left-to-right in RUNS:
  * a maximal vowel run vs a vowel run     -> vowel_run_cost  (diphthong rules)
  * a maximal consonant run vs a cons run  -> consonant_run_cost (class/dup/suffix)
  * exactly ONE adjacent consonant+vowel transposition of two existing letters
    (the two swapped letters must match exactly and are never edited further).
Any other class mismatch makes the alignment impossible -> not a suggestion.

Two numbers come out of an accepted alignment:
  * exoticness -- the summed "how weird is this misspelling" score; RANKING only.
  * edits      -- the Damerau edit count; the only hard GATE, capped per word.
"""

# Y is treated as a vowel (per design).
_VOWELS = set("AEIOUY")

# General consonant equivalence classes: a consonant run may swap to another run
# in the same set. {C,S,K,CK,SC} covers the /s/ and /k/ confusions incl. digraphs;
# {T,CH,TCH} covers the /ch/ family (WACH/WATTCH -> WATCH, KICHEN -> KITCHEN).
# A run may sit in more than one class (T is in both td_class and tch_class) --
# consonant_run_cost collects every applicable class and the cheapest one wins.
CONSONANT_CLASSES = [
    (set(["C", "S", "K", "CK", "SC"]), "csk_class"),
    (set(["G", "J"]), "gj_class"),
    (set(["T", "D"]), "td_class"),
    (set(["Z", "S"]), "zs_class"),
    (set(["T", "CH", "TCH"]), "tch_class"),
]

# Consonants that are confusable ONLY inside a recognized morpheme ending
# (the -TION/-SION/-CION and -OUS families). Outside that context a T<->S swap,
# say, is disallowed; inside it, it is the cheapest swap there is.
SUFFIX_CONSONANTS = set(["C", "S", "T", "SH"])

# Default morpheme TAILS -- the part AFTER the confusable lead consonant (T/S/C/SH).
# A swap qualifies when the candidate is <lead consonant> + <one of these tails>,
# so the same tail list covers TION/SION/CION etc. with no per-lead duplication.
# Mined from the 20k dictionary (see notes in config.yaml's spell_check block);
# the live game overrides this from config. Tails end in the N or S families per
# the design's cV+n / cV+s patterns.
DEFAULT_SUFFIX_TAILS = set([
    "ION", "IOUS", "IONAL", "IAN", "OUS",
    "IENT", "IONARY", "IONIST", "EOUS", "IENCY", "UOUS",
])

DEFAULT_COSTS = {
    "vowel": {
        "single_to_diphthong": 1,   # A -> AU (add a vowel to the run)
        "diphthong_to_single": 1,   # AU -> A (drop a vowel)
        "diphthong_swap_one": 1,    # EA -> EE (one vowel changed in a run)
        "diphthong_reverse": 1,     # IE -> EI (two vowels reordered)
        "single_swap": 2,           # A -> E (lone vowel changed)
        "silent_e": 1,              # WORD -> WORDE (add a silent E at the end)
    },
    "consonant": {
        "csk_class": 2,             # C/S/K/CK/SC
        "gj_class": 3,              # G/J
        "td_class": 3,              # T/D
        "zs_class": 2,              # Z/S
        "tch_class": 2,             # T/CH/TCH
        "dup": 1,                   # D -> DD
        "dedup": 1,                 # DD -> D
        "suffix_swap": 1,           # -TION/-SION/-CION/-OUS family confusion
    },
    "transposition": {
        "end": 1,                   # swap of the final two letters
        "elsewhere": 2,             # swap anywhere else
    },
    "max_transpositions": 1,
    "min_word_length": 4,
    "base_distance": 2,
    "distance_per_vowel_run": 1,
    "max_suggestions": 2,
}


def is_vowel(ch):
    """True if `ch` (uppercase letter) is a vowel; Y counts as a vowel."""
    return ch in _VOWELS


def count_vowel_runs(word):
    """Number of maximal vowel runs in `word` (uppercase). CART -> 1, CARTOON -> 2."""
    runs = 0
    prev_vowel = False
    for ch in word:
        here = is_vowel(ch)
        if here and not prev_vowel:
            runs = runs + 1
        prev_vowel = here
    return runs


def distance_cap(word, costs=DEFAULT_COSTS):
    """Hard edit-distance ceiling for suggestions toward `word`: a floor of
    base_distance, plus distance_per_vowel_run for every vowel run.
    CART -> max(2, 1) = 2, CARTOON -> max(2, 2) = 2, CARTOONING -> max(2, 3) = 3."""
    base = costs["base_distance"]
    per_run = costs["distance_per_vowel_run"]
    scaled = count_vowel_runs(word) * per_run
    if scaled > base:
        cap = scaled
    else:
        cap = base
    return cap


# --- run helpers -------------------------------------------------------------

def _run_len(s, idx, want_vowel):
    """Length of the maximal same-class (vowel/consonant) run in `s` from `idx`."""
    n = 0
    while idx + n < len(s) and is_vowel(s[idx + n]) == want_vowel:
        n = n + 1
    return n


def _collapse(s):
    """Drop consecutive duplicate letters: LL -> L, SC -> SC, MM -> M."""
    out = []
    for ch in s:
        if not out or out[-1] != ch:
            out.append(ch)
    return "".join(out)


def _levenshtein(a, b):
    """Plain edit distance between two short strings (used for run edit counts)."""
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i]
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cost = 0
            else:
                cost = 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[len(b)]


# --- per-run scoring ---------------------------------------------------------

def vowel_run_cost(r1, r2, costs):
    """(exoticness, edits) to turn vowel run `r1` into `r2`, or None if it is not
    one of the allowed vowel moves. All in-diphthong edits cost the same small
    amount; a lone vowel swap costs more."""
    v = costs["vowel"]
    len1, len2 = len(r1), len(r2)
    result = None
    if r1 == r2:
        result = (0, 0)
    elif len1 == 1 and len2 == 1:
        result = (v["single_swap"], 1)
    elif len1 == 2 and len2 == 2 and r1 == r2[::-1]:
        result = (v["diphthong_reverse"], 1)
    else:
        # In/around a diphthong every edit is small but the kinds are scored
        # separately: adding a vowel (single->diphthong), dropping one
        # (diphthong->single), or swapping one (diphthong swap). Decompose the
        # edit distance into adds/drops/swaps (exact for these short runs).
        d = _levenshtein(r1, r2)
        adds = max(0, len2 - len1)
        drops = max(0, len1 - len2)
        swaps = d - adds - drops
        cost = (adds * v["single_to_diphthong"]
                + drops * v["diphthong_to_single"]
                + swaps * v["diphthong_swap_one"])
        result = (cost, d)
    return result


def consonant_run_cost(r1, r2, costs, candidate, idx, suffix_tails):
    """(exoticness, edits) to turn consonant run `r1` into `r2`, or None if no
    allowed move covers it. Cheaper rule wins when several apply: a suffix-context
    swap (1) beats the general class cost. `candidate`/`idx` locate `r2` so we can
    tell whether it leads a recognized morpheme ending."""
    c = costs["consonant"]
    options = []
    if r1 == r2:
        options.append((0, 0))
    # Pure doubling / de-duping: same letters, differing only by repetition.
    if _collapse(r1) == _collapse(r2) and r1 != r2:
        edits = abs(len(r1) - len(r2))
        if len(r2) > len(r1):
            key = "dup"
        else:
            key = "dedup"
        options.append((c[key] * edits, edits))
    # General consonant equivalence classes.
    for members, key in CONSONANT_CLASSES:
        if r1 in members and r2 in members:
            options.append((c[key], _levenshtein(r1, r2)))
    # Suffix-context confusion (T/S/C/SH at the head of a morpheme ending).
    if r1 in SUFFIX_CONSONANTS and r2 in SUFFIX_CONSONANTS:
        if _is_suffix_context(candidate, idx, len(r2), suffix_tails):
            options.append((c["suffix_swap"], _levenshtein(r1, r2)))
    if options:
        result = min(options)
    else:
        result = None
    return result


def _is_suffix_context(word, idx, lead_len, suffix_tails):
    """True if candidate `word`, after the confusable lead consonant run at `idx`
    (length `lead_len`), ends with a recognized morpheme tail -- so the run is the
    leading consonant of e.g. -TION, not a cV+n cluster somewhere near the start."""
    return word[idx + lead_len:] in suffix_tails


# --- the matcher -------------------------------------------------------------

def _better(x, y):
    """Lexicographically-smaller (exoticness, edits) pair, skipping None."""
    if x is None:
        result = y
    elif y is None:
        result = x
    elif x <= y:
        result = x
    else:
        result = y
    return result


def _add(cost, rest):
    """Combine a move cost with the recursive remainder; None propagates."""
    if rest is None:
        result = None
    else:
        result = (cost[0] + rest[0], cost[1] + rest[1])
    return result


def _match(a, b, costs, suffix_tails):
    """Best (exoticness, edits) alignment of typed `a` to candidate `b`, or None
    if no all-allowed alignment exists. Memoized over (i, j, transposition_used)."""
    n, m = len(a), len(b)
    max_trans = costs["max_transpositions"]
    memo = {}

    def rec(i, j, t_used):
        if i == n and j == m:
            return (0, 0)
        key = (i, j, t_used)
        if key in memo:
            return memo[key]
        best = None
        if i < n and j < m:
            # Exact character match (also lets a run be entered mid-cluster, so a
            # transposition straddling a run boundary can still be found).
            if a[i] == b[j]:
                best = _better(best, _add((0, 0), rec(i + 1, j + 1, t_used)))
            av, bv = is_vowel(a[i]), is_vowel(b[j])
            if av and bv:
                p = _run_len(a, i, True)
                q = _run_len(b, j, True)
                cost = vowel_run_cost(a[i:i + p], b[j:j + q], costs)
                if cost is not None:
                    best = _better(best, _add(cost, rec(i + p, j + q, t_used)))
            elif (not av) and (not bv):
                p = _run_len(a, i, False)
                q = _run_len(b, j, False)
                cost = consonant_run_cost(
                    a[i:i + p], b[j:j + q], costs, b, j, suffix_tails)
                if cost is not None:
                    best = _better(best, _add(cost, rec(i + p, j + q, t_used)))
        # Silent-E ending rule: one word carries a trailing E the other lacks
        # (WORD -> WORDE). Fires only at the very end, and the extra E must sit
        # right after a consonant -- a real silent-E slot, not part of a vowel
        # run like -EE / -IE, which the vowel-run rules already cover.
        e_cost = costs["vowel"]["silent_e"]
        if i == n - 1 and j == m and i >= 1 and a[i] == "E" and not is_vowel(a[i - 1]):
            best = _better(best, _add((e_cost, 1), rec(i + 1, j, t_used)))
        if j == m - 1 and i == n and j >= 1 and b[j] == "E" and not is_vowel(b[j - 1]):
            best = _better(best, _add((e_cost, 1), rec(i, j + 1, t_used)))
        # One consonant+vowel transposition of two existing, otherwise-untouched
        # letters. Works whether or not it preserves the C/V skeleton.
        if (t_used < max_trans and i + 1 < n and j + 1 < m
                and a[i] == b[j + 1] and a[i + 1] == b[j]
                and a[i] != a[i + 1]
                and is_vowel(a[i]) != is_vowel(a[i + 1])):
            if i + 2 == n and j + 2 == m:
                tcost = costs["transposition"]["end"]
            else:
                tcost = costs["transposition"]["elsewhere"]
            best = _better(best, _add((tcost, 1), rec(i + 2, j + 2, t_used + 1)))
        memo[key] = best
        return best

    return rec(0, 0, 0)


def evaluate(typed, candidate, costs=DEFAULT_COSTS,
             suffix_tails=DEFAULT_SUFFIX_TAILS):
    """Decide if dictionary word `candidate` is a valid spelling suggestion for
    the (non-dictionary) `typed` word. Returns {"exoticness", "edits"} for an
    accepted suggestion, else None. Gates: both words >= min_word_length, an
    all-allowed run alignment exists, and its edit count <= distance_cap."""
    a = typed.upper()
    b = candidate.upper()
    min_len = costs["min_word_length"]
    result = None
    if len(a) >= min_len and len(b) >= min_len and a != b:
        scored = _match(a, b, costs, suffix_tails)
        if scored is not None and scored[1] <= distance_cap(b, costs):
            result = {"exoticness": scored[0], "edits": scored[1]}
    return result
