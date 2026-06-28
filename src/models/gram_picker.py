import csv
import os
import string

from config import CONFIG, select_rule
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

# Length-quota bookkeeping for rule_grams_greater_than_47_lengthcontrolled (see that rule and
# _pick_grams_length_enforced below). _length_counts tallies how many KEPT grams
# of each length category (1 / 2 / 3+) the formation has placed so far, so the
# quota picker can steer the next draw toward whichever category is running
# behind its configured share. _forced_length, when set, pins the picker to a
# single length bucket for the current draw (so dedup re-rolls stay in-category).
# Both reset per game alongside the dedup state.
_length_counts = {1: 0, 2: 0, 3: 0}
_forced_length = None

# Level-2 formation arrangement (see formation_length_sequence below and
# game_screen._rule_formation_arrange_*). The arrangement decides every cell's
# length UP FRONT, then pins each cell's draw to that length via this global, so
# the diagonal length placement is independent of the order grams are drawn.
# When set, pick_grams routes a formation draw through _draw_forced_formation
# instead of the legacy per-draw quota _pick_grams_length_enforced (kept below,
# now uncalled in this path). None outside an arranged formation draw.
_forced_formation_length = None

# A SECOND quota nested inside the unigram category: every formation unigram is
# also a "common glue" or "uncommon flavor" letter (see _COMMON_GLUE_LETTERS /
# _UNCOMMON_FLAVOR_LETTERS below), and gram_length.unigram_*_percent enforces that
# split the same largest-remainder way the length quota does. _unigram_group_counts
# tallies KEPT unigrams per group; _forced_unigram_group, when set, pins a forced
# unigram draw to one group. Reset per game with the length counts.
_unigram_group_counts = {"common": 0, "uncommon": 0}
_forced_unigram_group = None


def reset_gram_dedup():
    """Forget every multi-letter gram (and formation unigram count) used so far,
    so a new game starts fresh. Call once before building a game's formation +
    pools."""
    _used_multigrams.clear()
    _unigram_counts.clear()
    for category in _length_counts:
        _length_counts[category] = 0
    for group in _unigram_group_counts:
        _unigram_group_counts[group] = 0


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
    is first multigram-deduped, then checked against the unigram cap.

    One more layer sits on top, but only for the opening formation when the
    length-controlled picker is active: rule_grams_greater_than_47_lengthcontrolled's gram_length.*
    percentages are then enforced as a QUOTA across the whole formation (so a board
    can't come out trigram-heavy by luck), not just rolled per cell. See
    _pick_grams_length_enforced. The piece pool and every other picker fall through
    to the plain deduped draw."""
    multigram_deduped = lambda n: _gram_dedup_rule(rule, n)
    deduped = lambda n: _unigram_dedup_rule(multigram_deduped, n)
    if rule is rule_grams_greater_than_47_lengthcontrolled and _in_formation:
        # Level-2 arrangement active: the formation has pinned this cell's length
        # (set_forced_formation_length), so draw straight from that bucket. Else
        # fall back to the legacy per-draw round-robin quota.
        if _forced_formation_length is not None:
            return _draw_forced_formation(deduped, count)
        return _pick_grams_length_enforced(deduped, count)
    return deduped(count)


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


# --- length-controlled corpus picker (rule_grams_greater_than_47_lengthcontrolled) -----
# Same JPO corpus as rule_grams_greater_than_47, but the per-cell length is
# governed by configurable category percentages instead of the corpus's own
# length mix. (The raw corpus skews toward multigrams -- see the _load_gram_corpus
# note "getting a unigram is less likely than a multigram" -- so this rule exists
# to steer that blend.) Within whichever length bucket (1 / 2 / 3+) is chosen, the
# corpus's own frequency weights are respected.
#
# The length percentages mean two different things depending on context:
#   * Opening formation -- enforced as a QUOTA (largest-remainder), so the board's
#     actual unigram/digram/3+ counts land within ~1 of the configured shares and
#     a board can't come out trigram-heavy / unigram-starved by luck. The choke
#     point pick_grams routes formation draws through _pick_grams_length_enforced,
#     which pins each draw to one bucket via _forced_length and tallies _length_counts.
#   * Piece pool (and anywhere outside the formation) -- rolled per cell as relative
#     probabilities. The 100+-piece pool self-averages, and a quota across it would
#     fight the per-game dedup, so plain rolls are fine there.

# Per-length corpus partition, lazily built: {1: (grams, weights), 2: (...),
# 3: (...)} where the "3" bucket holds every gram of length 3 OR MORE (the corpus
# tops out at quadgrams). Cached after the first build like the other _load_*.
_corpus_by_length = None


def _partition_corpus_by_length():
    global _corpus_by_length
    if _corpus_by_length is not None:
        return
    _load_gram_corpus()
    # Three buckets; length>=3 all funnel into key 3 (the "3+" category).
    buckets = {1: ([], []), 2: ([], []), 3: ([], [])}
    for gram, weight in zip(_corpus_grams, _corpus_weights):
        key = min(len(gram), 3)
        buckets[key][0].append(gram)
        buckets[key][1].append(weight)
    _corpus_by_length = buckets


# Length-mix percentages for rule_grams_greater_than_47_lengthcontrolled, read from config
# (gram_length.* in the rules block). rand().choices treats these as RELATIVE
# weights, so they need not sum to 100 -- writing them as percentages just keeps
# the YAML readable, and zeroing one category drops that length entirely.
_LENGTH_CATEGORIES = [1, 2, 3]
_LENGTH_PCT_WEIGHTS = [
    CONFIG["rules"]["gram_length.unigram_percent"],
    CONFIG["rules"]["gram_length.digram_percent"],
    CONFIG["rules"]["gram_length.trigramplus_percent"],
]


def _draw_from_length_bucket(length, count):
    """Draw `count` grams of the given length category (1 / 2 / 3+) from the
    corpus, weighted by the corpus's own frequencies within that bucket."""
    bucket_grams, bucket_weights = _corpus_by_length[length]
    picks = rand().choices(bucket_grams, weights=bucket_weights, k=count)
    return [Gram(text) for text in picks]


# --- unigram sub-bins (common glue vs uncommon flavor) -----------------
# A second quota nested inside the unigram category: each formation unigram is
# steered to be a frequent "glue" letter or a rarer "flavor" letter, in the ratio
# set by gram_length.unigram_common_percent / unigram_uncommon_percent. WITHIN a
# group the corpus's own letter frequencies still apply (so glue draws lean E/I/A,
# flavor draws lean P/M/D over Z/X/J). "QU" is the one digram counted as a unigram
# here -- it is the only way Q reaches the board (the corpus has no lone Q), and it
# sits in the flavor group. These bins govern the OPENING FORMATION only; the piece
# pool keeps rolling unigrams from the whole length-1 bucket (no QU).
_COMMON_GLUE_LETTERS = ["E", "I", "A", "T", "R", "N", "O", "S", "L", "C", "U"]
_UNCOMMON_FLAVOR_LETTERS = [
    "P", "M", "D", "G", "H", "Y", "B", "F", "V", "K", "W", "Z", "X", "J", "QU",
]
_UNIGRAM_GROUP_KEYS = ["common", "uncommon"]
_UNIGRAM_GROUP_WEIGHTS = [
    CONFIG["rules"]["gram_length.unigram_common_percent"],
    CONFIG["rules"]["gram_length.unigram_uncommon_percent"],
]

# Lazily built: {"common": (letters, weights), "uncommon": (...)} where each
# weight is that letter's corpus frequency (QU's own corpus freq for the digram).
_unigram_groups = None


def _partition_unigrams_into_groups():
    global _unigram_groups
    if _unigram_groups is not None:
        return
    _load_gram_corpus()
    freq = {g.upper(): w for g, w in zip(_corpus_grams, _corpus_weights)}

    def build(letters):
        items, weights = [], []
        for letter in letters:
            items.append(letter)
            # Default any letter the corpus somehow lacks to weight 1 so it can
            # still appear rather than silently dropping out of its group.
            weights.append(freq.get(letter) or 1)
        return items, weights

    _unigram_groups = {
        "common": build(_COMMON_GLUE_LETTERS),
        "uncommon": build(_UNCOMMON_FLAVOR_LETTERS),
    }


def _draw_from_unigram_group(group, count):
    """Draw `count` unigrams from one sub-bin (common / uncommon), weighted by
    each letter's corpus frequency within the group."""
    _partition_unigrams_into_groups()
    items, weights = _unigram_groups[group]
    picks = rand().choices(items, weights=weights, k=count)
    return [Gram(text) for text in picks]


def rule_grams_greater_than_47_lengthcontrolled(count):
    """
    Pick grams from the JPO corpus (same file as rule_grams_greater_than_47) but
    with the unigram / digram / 3+-gram mix dictated by the gram_length.* config
    rather than the corpus's own length skew. A category set to 0 is never drawn.

    Two paths (see the section comment above):
      * _forced_length set -- the quota enforcer (formation) has pinned this draw
        to one length bucket; every gram comes from it. When that bucket is the
        unigram one AND a sub-bin is pinned too (_forced_unigram_group), the gram
        is drawn from that common/uncommon group instead of the whole bucket.
      * otherwise -- each cell independently rolls a length category using the
        configured percentages as relative weights (the piece-pool path).

    Within whichever bucket, grams are drawn weighted by the corpus's frequencies.

    Args:
        count: Number of grams needed (one per cell)

    Returns:
        List of Grams whose length mix follows the configured percentages
    """
    _partition_corpus_by_length()
    if _forced_length is not None:
        if _forced_length == 1 and _forced_unigram_group is not None:
            return _draw_from_unigram_group(_forced_unigram_group, count)
        return _draw_from_length_bucket(_forced_length, count)
    lengths = rand().choices(_LENGTH_CATEGORIES, weights=_LENGTH_PCT_WEIGHTS, k=count)
    grams = []
    for length in lengths:
        grams.extend(_draw_from_length_bucket(length, 1))
    return grams


def _largest_remainder_pick(keys, weights, counts):
    """Of `keys`, return the one whose configured share (its parallel entry in
    `weights`) is currently most under-filled given `counts` so far, using the
    largest-remainder method: maximize share * (placed + 1) - counts[key]. Keys
    weighted 0 are skipped. Returns None if every weight is 0 (degenerate config)."""
    placed = sum(counts.values())
    weight_sum = sum(weights)
    if weight_sum <= 0:
        return None
    best_key = None
    best_deficit = None
    for key, weight in zip(keys, weights):
        if weight <= 0:
            continue
        ideal = weight / weight_sum * (placed + 1)
        deficit = ideal - counts[key]
        if best_deficit is None or deficit > best_deficit:
            best_deficit = deficit
            best_key = key
    return best_key


def _next_quota_length():
    """The length category (1 / 2 / 3+) most behind its gram_length.*_percent
    share so far. None if every length share is 0."""
    return _largest_remainder_pick(_LENGTH_CATEGORIES, _LENGTH_PCT_WEIGHTS, _length_counts)


def _next_quota_unigram_group():
    """The unigram sub-bin ("common" / "uncommon") most behind its
    gram_length.unigram_*_percent share so far. None if both shares are 0."""
    return _largest_remainder_pick(
        _UNIGRAM_GROUP_KEYS, _UNIGRAM_GROUP_WEIGHTS, _unigram_group_counts)


def _pick_grams_length_enforced(deduped, count):
    """Hand out `count` formation grams whose length categories follow the
    gram_length.* percentages as an enforced QUOTA. Per cell: pick the most under-
    filled category (_next_quota_length), pin the picker to that bucket via
    _forced_length so dedup re-rolls stay in-category, draw one KEPT gram through
    the dedup pipeline `deduped`, and tally it. Counting only kept grams keeps the
    quota honest even when the dedup rules discard and re-roll.

    Unigrams carry a second, nested quota: each is also steered to a common/
    uncommon sub-bin (_next_quota_unigram_group) via _forced_unigram_group, so the
    glue-vs-flavor split is enforced the same way."""
    global _forced_length, _forced_unigram_group
    grams = []
    for _ in range(count):
        category = _next_quota_length()
        if category is None:  # every share is 0 -- nothing to steer toward
            grams.extend(deduped(1))
            continue
        group = _next_quota_unigram_group() if category == 1 else None
        _forced_length = category
        _forced_unigram_group = group
        try:
            picked = deduped(1)
        finally:
            _forced_length = None
            _forced_unigram_group = None
        grams.extend(picked)
        _length_counts[category] += len(picked)
        if group is not None:
            _unigram_group_counts[group] += len(picked)
    return grams


# --- Level-2 formation arrangement (length placement detached from draw order) ---
# The legacy path above (_pick_grams_length_enforced) decides each cell's length
# AT DRAW TIME, in row-major fill order -- so the round-robin cadence aliases into
# diagonal lines only as long as draw-order == fill-order. To keep that diagonal
# reveal even if we later reorder draws (e.g. draw all trigrams first), the
# formation now decides the length-per-cell sequence UP FRONT here, hands it to a
# game_screen arrangement rule to map onto cells (row-major -> diagonal, shuffled
# -> scattered), and pins each cell's draw via set_forced_formation_length. Same
# percentages, same cadence -- just no longer coupled to when grams are drawn.

def set_forced_formation_length(length):
    """Pin the next length-controlled formation draw to `length` (1 / 2 / 3+), or
    clear with None. game_screen sets this around each arranged formation cell's
    piece build so pick_grams draws straight from that length bucket."""
    global _forced_formation_length
    _forced_formation_length = length


def formation_length_sequence(count):
    """Return a list of `count` length categories (1 / 2 / 3+) in the round-robin
    largest-remainder cadence dictated by gram_length.*_percent -- the SAME
    periodic cadence the legacy _pick_grams_length_enforced produced per draw, but
    computed up front and detached from gram drawing. A re-roll never changes a
    draw's length (dedup stays in-bucket), so the legacy kept-gram cadence equals
    this pre-computed one; mapping it row-major reproduces today's diagonal."""
    counts = {1: 0, 2: 0, 3: 0}
    seq = []
    for _ in range(count):
        category = _largest_remainder_pick(_LENGTH_CATEGORIES, _LENGTH_PCT_WEIGHTS, counts)
        if category is None:  # degenerate config (all shares 0) -- default unigram
            category = 1
        seq.append(category)
        counts[category] += 1
    return seq


def _draw_forced_formation(deduped, count):
    """Draw `count` formation grams pinned to _forced_formation_length, through the
    full dedup pipeline. Unigram cells still honor the common/uncommon sub-bin
    quota. The Level-2 twin of _pick_grams_length_enforced's per-cell body, minus
    the length round-robin (the arrangement already chose the length)."""
    global _forced_length, _forced_unigram_group
    length = _forced_formation_length
    grams = []
    for _ in range(count):
        group = _next_quota_unigram_group() if length == 1 else None
        _forced_length = length
        _forced_unigram_group = group
        try:
            picked = deduped(1)
        finally:
            _forced_length = None
            _forced_unigram_group = None
        grams.extend(picked)
        _length_counts[length] += len(picked)
        if group is not None:
            _unigram_group_counts[group] += len(picked)
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
