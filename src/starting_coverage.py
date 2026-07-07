"""Starting-coverage dictionary: every word the player could possibly spell from
the board's INITIAL formation, before any movement -- a debug/analysis snapshot
of how rich or limited a given board layout (gram distribution) is.

This module is deliberately decoupled from the game/UI: it works on a plain
multiset of gram strings (text -> how many cells hold it) and an iterable of
dictionary words, so it can be unit-tested in isolation and called once, blocking,
at game start (see the game_screen wiring).

What it models (and what it ignores):
  * A word is FORMED by cutting it into consecutive substrings ("groupings"),
    each of which is the text of a distinct board cell. Order is free -- the
    player may rearrange pieces any way -- so adjacency / nucleation /
    word-pathfinding / how cells would fit on a crowded board are all IGNORED.
  * The only formation rule respected is the configured word-length rule
    (e.g. rule_word_min3letters_min2cells): passed in as `accept(word, n_cells)`.
  * A cell can't be reused within one word. Two cells with the SAME text are
    interchangeable, so when a grouping fills k slots with a gram that the board
    has m copies of, the number of distinct ways is C(m, k) (a COMBINATION, not a
    permutation): e.g. "kiss" with two S-cells = C(2,2) = 1 way; "sat" with two
    S-cells = C(2,1) = 2 ways. A grouping's way-count is the product of C(m, k)
    over its distinct gram values; a word's total_count is the sum over groupings.
  * Grams are pooled by TEXT regardless of source: player, obstacle and mission
    cells all contribute (the caller decides which cells to include); wild-vowel
    cells, the jigsaw piece pool, and any gram-manipulation rules are excluded by
    the caller, not here.

Algorithm: Approach A -- iterate the dictionary, segment each word with a small
word-break DP over the (short) board gram set, and count assignments
combinatorially. Cost is linear in dictionary size and essentially flat in board
size, because physical cell assignments are counted with C(m, k) rather than
enumerated.
"""

import math
from collections import Counter


def _segmentations(word, grams, max_len):
    """All ways to cut `word` (uppercase) into consecutive substrings that are
    each a key of `grams`. Returns a list of tuples of segment strings. A small
    suffix DP: memo[i] = segmentations covering word[i:], built right-to-left."""
    n = len(word)
    memo = {n: [()]}
    for i in range(n - 1, -1, -1):
        segs = []
        limit = min(max_len, n - i)
        for ln in range(1, limit + 1):
            piece = word[i:i + ln]
            if piece in grams:
                for rest in memo[i + ln]:
                    segs.append((piece,) + rest)
        memo[i] = segs
    return memo[0]


def _ways(segmentation, grams):
    """Number of distinct ways to assign distinct board cells to this grouping:
    the product of C(m, k) over each gram value used k times when the board holds
    m of it. 0 if the board lacks enough copies of some gram."""
    total = 1
    for gram, k in Counter(segmentation).items():
        m = grams[gram]
        if k > m:
            return 0
        total *= math.comb(m, k)
    return total


def coverage_for_word(word, grams, max_len, accept, sep):
    """(total_count, [(grouping_str, count), ...]) for one word. `grouping_str`
    joins the grouping's lowercase grams with `sep`; combos are ordered by cell
    count then string for a stable, readable file. Groupings that fail `accept`
    (the word-length rule) or have 0 ways are dropped."""
    w = word.upper()
    combos = []
    total = 0
    for seg in _segmentations(w, grams, max_len):
        if not accept(w, len(seg)):
            continue
        ways = _ways(seg, grams)
        if ways <= 0:
            continue
        combos.append((sep.join(s.lower() for s in seg), ways))
        total += ways
    combos.sort(key=lambda c: (c[0].count(sep), c[0]))
    return total, combos


def rules_allow_spellable(word, accept):
    """Whether the configured word rules PERMIT this word at all, ignoring the
    board's grams: True if some cell count (1..len(word)) passes `accept`. This is
    board-independent -- e.g. under rule_word_min3letters_min2cells a 2-letter word
    is never spellable (too short) no matter what cells exist, whereas a 3-letter
    word is allowed (it can be cut into >= 2 cells). It distinguishes a word that is
    absent because the rules forbid it from one merely missing the right grams."""
    return any(accept(word.upper(), n) for n in range(1, len(word) + 1))


def any_word_formable(words, grams, accept):
    """True as soon as SOME word in `words` can be formed from the gram multiset
    `grams` (text -> cell count) under `accept` -- the existence-only, early-exit
    companion to coverage_for_word, for "can the player still make ANY word?"
    end-detection (see the constellation auto-end rule).

    Iterates the dictionary and returns on the first formable word, so a board
    that can still spell something is cheap; only a truly exhausted board pays a
    full scan (and that happens once, on the clear that empties it). `grams` keys
    are upper-cased to match the dictionary; an empty multiset yields False."""
    grams = {g.upper(): c for g, c in grams.items()}
    if not grams:
        return False
    max_len = max(len(g) for g in grams)
    for word in words:
        w = word.upper()
        for seg in _segmentations(w, grams, max_len):
            if accept(w, len(seg)) and _ways(seg, grams) > 0:
                return True
    return False


def write_coverage_csv(path, words, grams, accept, sep):
    """Write the starting-coverage CSV: one line per dictionary word (sorted,
    INCLUDING zero-coverage words), columns
    `word,word_length,is_present,do_rules_allow_spellable,total_count,combos`
    where word_length is the letter count, is_present is "true"/"false" (whether
    the board can form it at all, i.e. total_count > 0), do_rules_allow_spellable
    is "true"/"false" (whether the word-length rule permits the word regardless of
    the board's grams; see rules_allow_spellable), and combos is a ";"-separated
    list of `grouping:count`. Returns summary stats for logging."""
    grams = {g.upper(): c for g, c in grams.items()}
    max_len = max((len(g) for g in grams), default=0)
    n_words = n_covered = n_combos = 0
    with open(path, "w") as f:
        f.write("word,word_length,is_present,do_rules_allow_spellable,total_count,combos\n")
        for word in sorted(set(w.lower() for w in words)):
            total, combos = coverage_for_word(word, grams, max_len, accept, sep)
            field = ";".join(f"{g}:{c}" for g, c in combos)
            is_present = "true" if total else "false"
            allowed = "true" if rules_allow_spellable(word, accept) else "false"
            f.write(f"{word},{len(word)},{is_present},{allowed},{total},{field}\n")
            n_words += 1
            n_covered += 1 if total else 0
            n_combos += len(combos)
    return {"words": n_words, "covered": n_covered, "combos": n_combos}
