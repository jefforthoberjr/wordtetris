import csv
import os
import string

from config import select_rule
from models.gram import Gram
from models.wild_vowel import is_vowel
# Every random draw routes through the swappable Source seam (see source.py) so a
# replay can reproduce or override the grams a session drew.
from source import rand


# --- duplicate-gram rule (gram.dedup) ----------------------------------
# One toggle governs EVERY gram picker (player / obstacle / mission, square +
# hex): all of them funnel through pick_grams() in the piece constructors. The
# dedup is best-effort across a whole game -- the initial formation AND the
# piece queue share one set of already-used multi-letter grams, reset per game.

# Multi-letter grams already handed out this game (e.g. {"TH", "ING"}). Single
# letters and wild vowels are never tracked. Cleared at the start of each game.
_used_multigrams = set()

# Single-letter grams handed out so far during the opening formation, with a
# running count each (e.g. {"E": 3, "S": 1}). The unigram dedup rule (gram.
# unigram_dedup) caps how many of any one letter the formation may use; the
# piece pool is exempt (see _in_formation below). Wild vowels and multigrams are
# never counted. Cleared at the start of each game alongside _used_multigrams.
_unigram_counts = {}

# True only while the opening board formation is being built. The unigram cap
# applies to the formation alone -- the piece pool (100+ pieces) would exhaust
# the 26 letters under a 3-each cap, so its draws skip the cap entirely.
_in_formation = False


def reset_gram_dedup():
    """Forget every multi-letter gram (and formation unigram count) used so far,
    so a new game starts fresh. Call once before building a game's formation +
    pools."""
    _used_multigrams.clear()
    _unigram_counts.clear()


def begin_formation_gram_run():
    """Mark the start of the opening-formation build so the unigram dedup rule
    starts capping. Pair with end_formation_gram_run() once the formation's
    pieces are all built (before the piece pool is built)."""
    global _in_formation
    _in_formation = True


def end_formation_gram_run():
    """Mark the end of the opening-formation build so later draws (the piece
    pool) skip the unigram cap. The twin of begin_formation_gram_run()."""
    global _in_formation
    _in_formation = False


def rule_allow_duplicate_grams(rule, count):
    """No dedup: hand back exactly what the picker chose (the original behavior;
    multi-letter grams may repeat across the board / queue)."""
    return rule(count)


def rule_no_duplicate_multigrams(rule, count):
    """Avoid repeating any 2+-letter gram across the whole game: re-roll a multi-
    letter gram already used. Single letters and wild vowels pass freely (the
    board needs many of them). If the picker's corpus runs out of fresh
    multigrams, fall back to allowing repeats so every cell still gets a gram
    (best-effort -- never returns fewer than `count`)."""
    chosen = []
    cap = max(50, count * 50)  # re-roll budget before giving up on freshness
    attempts = 0
    while len(chosen) < count and attempts < cap:
        gram = rule(1)[0]
        attempts += 1
        if len(gram) > 1 and not gram.is_wild:
            if gram.text in _used_multigrams:
                continue  # duplicate multigram -- re-roll
            _used_multigrams.add(gram.text)
        chosen.append(gram)
    # Corpus exhausted of fresh multigrams: top up allowing repeats.
    while len(chosen) < count:
        chosen.append(rule(1)[0])
    return chosen


_GRAM_DEDUP_RULES = {
    "rule_allow_duplicate_grams": rule_allow_duplicate_grams,
    "rule_no_duplicate_multigrams": rule_no_duplicate_multigrams,
}
_gram_dedup_rule = select_rule("gram.dedup", _GRAM_DEDUP_RULES)


# --- duplicate-unigram rule (gram.unigram_dedup) -----------------------
# A SEPARATE toggle from gram.dedup above: that one governs multi-letter grams;
# this one governs single letters. Both run on every draw (composed in
# pick_grams), so a board can dedup multigrams and cap unigrams at once. The
# unigram cap applies to the opening formation only (see _in_formation) -- the
# piece pool is never beholden to it, since 100+ pieces can't fit under a few
# copies of each of 26 letters.

# How many copies of any one single letter the formation may use. Named to match
# rule_max_3_duplicate_unigrams; kept as a constant so the cap is easy to retune.
_UNIGRAM_MAX = 3


def rule_nolimit_duplicate_unigrams(rule, count):
    """No unigram cap: hand back exactly what the picker chose (single letters may
    repeat freely across the board). The original behavior, named so it can sit
    opposite rule_max_3_duplicate_unigrams in the gram.unigram_dedup slot."""
    return rule(count)


def rule_max_3_duplicate_unigrams(rule, count):
    """During the opening formation, allow at most _UNIGRAM_MAX (3) copies of any
    one single letter across the whole board: re-roll a unigram already at the
    cap. Multi-letter grams and wild vowels pass freely (this rule only counts
    fixed single letters; multigrams are the other toggle's job). Outside the
    formation (the piece pool) the cap is skipped entirely. If the picker keeps
    handing back capped letters, fall back to allowing repeats so every cell
    still gets a gram (best-effort -- never returns fewer than `count`)."""
    if not _in_formation:
        return rule(count)
    chosen = []
    cap = max(50, count * 50)  # re-roll budget before giving up on the cap
    attempts = 0
    while len(chosen) < count and attempts < cap:
        gram = rule(1)[0]
        attempts += 1
        if len(gram) == 1 and not gram.is_wild:
            if _unigram_counts.get(gram.text, 0) >= _UNIGRAM_MAX:
                continue  # this letter is at its cap -- re-roll
            _unigram_counts[gram.text] = _unigram_counts.get(gram.text, 0) + 1
        chosen.append(gram)
    # Letters exhausted under the cap: top up allowing repeats.
    while len(chosen) < count:
        chosen.append(rule(1)[0])
    return chosen


_UNIGRAM_DEDUP_RULES = {
    "rule_nolimit_duplicate_unigrams": rule_nolimit_duplicate_unigrams,
    "rule_max_3_duplicate_unigrams": rule_max_3_duplicate_unigrams,
}
_unigram_dedup_rule = select_rule("gram.unigram_dedup", _UNIGRAM_DEDUP_RULES)


def pick_grams(rule, count):
    """The single choke point every piece's grams pass through: apply BOTH the
    active gram.dedup (multigram) rule and the gram.unigram_dedup (unigram) rule
    to the picker `rule`. Both SquarePiece and HexPiece call this, so the two
    toggles span the player queue, obstacles, missions and the initial board
    fill. The unigram rule wraps the multigram-deduped picker: each single draw
    is first multigram-deduped, then checked against the unigram cap."""
    multigram_deduped = lambda n: _gram_dedup_rule(rule, n)
    return _unigram_dedup_rule(multigram_deduped, count)


_scrabble_letters = None
_scrabble_weights = None
_english_words = None
_corpus_grams = None
_corpus_weights = None
_digrams52 = None
_digrams52_weights = None
_trigrams = None


def _load_scrabble_distribution():
    global _scrabble_letters, _scrabble_weights
    if _scrabble_letters is not None:
        return

    _scrabble_letters = []
    _scrabble_weights = []

    csv_path = os.path.join(os.path.dirname(__file__), 'gram_corpus', 'scrabble_letters.csv')
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            _scrabble_letters.append(row['letter'])
            _scrabble_weights.append(int(row['count']))


def rule_random_letters(count):
    """
    Pick grams for a piece using pure random single letters.

    Args:
        count: Number of grams needed (one per cell)

    Returns:
        List of unigram Grams
    """
    grams = []
    for _ in range(count):
        grams.append(Gram(rand().choice(string.ascii_uppercase)))
    return grams


def rule_scrabble_distribution(count):
    """
    Pick grams using Scrabble tile distribution weights.

    Args:
        count: Number of grams needed (one per cell)

    Returns:
        List of unigram Grams
    """
    _load_scrabble_distribution()
    letters = rand().choices(_scrabble_letters, weights=_scrabble_weights, k=count)
    grams = []
    for letter in letters:
        grams.append(Gram(letter))
    return grams


def rule_scrabble_with_allvowelswild(count):
    """
    Like rule_scrabble_distribution -- same Scrabble tile weights -- but every
    time the draw lands on a vowel (A, E, I, O, U, Y) the cell becomes a wild
    vowel instead of that fixed letter. Consonants are unchanged, so the overall
    letter frequencies are preserved; only the identity of the vowels is hidden
    behind a wild cell that can later stand for a 1-3 vowel run.

    Args:
        count: Number of grams needed (one per cell)

    Returns:
        List of Grams, with vowels replaced by wild-vowel Grams
    """
    _load_scrabble_distribution()
    letters = rand().choices(_scrabble_letters, weights=_scrabble_weights, k=count)
    grams = []
    for letter in letters:
        if is_vowel(letter):
            grams.append(Gram("", is_wild=True))
        else:
            grams.append(Gram(letter))
    return grams


def _load_english_words():
    global _english_words
    if _english_words is not None:
        return

    _english_words = []
    dict_path = os.path.join(os.path.dirname(__file__), 'dictionaries', 'spellingDictionary20k-nocompound.txt')
    with open(dict_path, 'r') as f:
        for line in f:
            word = line.strip().upper()
            if word:
                _english_words.append(word)


def rule_englishcorpus_random_unigram(count):
    """
    Pick grams by selecting random single letters from random words.

    Args:
        count: Number of grams needed (one per cell)

    Returns:
        List of unigram Grams
    """
    _load_english_words()
    grams = []
    for _ in range(count):
        word = rand().choice(_english_words)
        idx = rand().randint(0, len(word) - 1)
        grams.append(Gram(word[idx]))
    return grams


def rule_englishcorpus_random_digram(count):
    """
    Pick grams by selecting random 2-letter chunks from random words.
    Words shorter than 2 characters are skipped.

    Args:
        count: Number of grams needed (one per cell)

    Returns:
        List of digram Grams (each Gram holds 2 letters)
    """
    _load_english_words()
    grams = []
    while len(grams) < count:
        word = rand().choice(_english_words)
        if len(word) < 2:
            continue
        idx = rand().randint(0, len(word) - 2)
        grams.append(Gram(word[idx:idx + 2]))
    return grams

# Raw gram freq count from "v7" of analysis
# 1 letter grams: 26 entries; ~166k total weight
# 2 letter grams: ~300 entries; ~141k total weight
# 3 letter grams: ~700 entries; ~81k total weight
# 4 letter grams: ~150 entries; ~15k total weight
# (tossed out >5 grams; ~65 entries; ~6k total weight)
# known issues: contains weird grams (clipped morphological chunkks)
# known issues: getting a unigram is less likely than a multigram
def _load_gram_corpus():
    global _corpus_grams, _corpus_weights
    if _corpus_grams is not None:
        return

    _corpus_grams = []
    _corpus_weights = []

    csv_path = os.path.join(os.path.dirname(__file__), 'gram_corpus', 'jpo_allGramsGreaterThan47InFreq_cleaned.csv')
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            _corpus_grams.append(row['gram'])
            _corpus_weights.append(int(row['freq']))


def rule_grams_greater_than_47(count):
    """
    Pick grams from the JPO gram corpus (jpo_allGramsGreaterThan47InFreq_cleaned.csv),
    weighted by each gram's frequency.

    The corpus mixes 1-4 letter grams, so cells get a frequency-realistic
    blend of unigrams through quadgrams.

    Args:
        count: Number of grams needed (one per cell)

    Returns:
        List of Grams (each 1-4 letters)
    """
    _load_gram_corpus()
    picks = rand().choices(_corpus_grams, weights=_corpus_weights, k=count)
    grams = []
    for text in picks:
        grams.append(Gram(text))
    return grams


def _load_digrams52():
    global _digrams52, _digrams52_weights
    if _digrams52 is not None:
        return

    _digrams52 = []
    _digrams52_weights = []

    csv_path = os.path.join(os.path.dirname(__file__), 'gram_corpus', 'jpo_52digrams.csv')
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            _digrams52.append(row['gram'])
            _digrams52_weights.append(int(row['freq']))


# 1-in-3 odds of a digram, 2-in-3 odds of a unigram. Kept as a fraction so the
# split is easy to retune in one spot if we want a different blend later.
_DIGRAM52_CHANCE = 1.0 / 3.0


def rule_mixed_scrabble_digram52(count):
    """
    Pick grams as a blend of Scrabble unigrams and corpus digrams.

    Each cell rolls independently: a 1-in-3 chance to pull a digram from
    jpo_52digrams.csv, otherwise a 2-in-3 chance to pull a unigram from
    scrabble_letters.csv. Within whichever source is chosen, that file's own
    weights are respected.

    Args:
        count: Number of grams needed (one per cell)

    Returns:
        List of Grams (a mix of unigrams and digrams)
    """
    _load_scrabble_distribution()
    _load_digrams52()
    grams = []
    for _ in range(count):
        if rand().random() < _DIGRAM52_CHANCE:
            text = rand().choices(_digrams52, weights=_digrams52_weights, k=1)[0]
        else:
            text = rand().choices(_scrabble_letters, weights=_scrabble_weights, k=1)[0]
        grams.append(Gram(text))
    return grams


def rule_digram52_distribution(count):
    """
    Pick grams as digrams only, drawn from jpo_52digrams.csv weighted by each
    digram's frequency. Like rule_mixed_scrabble_digram52 but with no Scrabble
    unigrams mixed in: every cell gets a 2-letter gram.

    Args:
        count: Number of grams needed (one per cell)

    Returns:
        List of digram Grams (each 2 letters)
    """
    _load_digrams52()
    picks = rand().choices(_digrams52, weights=_digrams52_weights, k=count)
    grams = []
    for text in picks:
        grams.append(Gram(text))
    return grams


def _load_trigrams():
    global _trigrams
    if _trigrams is not None:
        return

    # Unlike the other gram CSVs, this file is a plain one-trigram-per-line list:
    # no header row and no frequency column (every trigram is weighted equally).
    _trigrams = []
    csv_path = os.path.join(os.path.dirname(__file__), 'gram_corpus', 'jpo_5.2.2_trigrams.csv')
    with open(csv_path, 'r') as f:
        for line in f:
            gram = line.strip().upper()
            if gram:
                _trigrams.append(gram)


def rule_trigram_equalweight(count):
    """
    Pick grams as trigrams only, drawn from jpo_5.2.2_trigrams.csv with EVERY
    trigram equally likely (the file carries no frequencies). Every cell gets a
    3-letter gram.

    Args:
        count: Number of grams needed (one per cell)

    Returns:
        List of trigram Grams (each 3 letters)
    """
    _load_trigrams()
    picks = rand().choices(_trigrams, k=count)
    grams = []
    for text in picks:
        grams.append(Gram(text))
    return grams
