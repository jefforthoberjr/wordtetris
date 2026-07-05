"""Spell-check debugging CLI (exercises game_screen.spell_suggest offline).

Runs the SAME restricted edit-distance matcher the game uses (models/spell_check
via models/spelling_suggester's live config) over the whole dictionary for one
typed word, but instead of returning just the top `max_suggestions` it buckets
every candidate by WHY it was (or wasn't) shown, so you can spot-check a word you
expected to see:

  TIER 1  accepted -- ranked exactly as in-game; the first `max_suggestions`
          are what the player actually sees, the rest are "the next best".
  TIER 2  rejected because edits exceeded the distance cap
          (base_distance / distance_per_vowel_run).
  TIER 3  rejected because no allowed run alignment exists, split into
          3a  transposition-limited: it WOULD align if max_transpositions were
              raised (so the budget is the only thing stopping it), and
          3b  pattern violation: no alignment even with unlimited transpositions
              (a real V/C class mismatch); ranked by raw edit distance so you can
              still eyeball how textually close it was.

This is PURE debug orchestration: it calls the existing matcher seams
(spell_check._match / .distance_cap) with the live cost table -- no new scoring
logic, nothing here feeds the game.

    python src/spell_check_cli.py CENTRE
    python src/spell_check_cli.py CENTRE --top 30
"""
import argparse
import os
import sys

# Run standalone: put src/ on the path so `config` / `models` import as in-game.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import spell_check
from models.spelling_suggester import _config, _freq_table
from models.word_dictionary import all_words, is_word

_RELAXED_TRANSPOSITIONS = 9  # "unlimited" for a short word: probe 3a vs 3b.


def _classify(word, costs, tails):
    """Bucket every dictionary candidate for typed `word` into the four tiers.

    Uses the same gates the game applies (min_word_length on both words, the
    max_length_delta scan pre-filter) so the candidate SET matches the live scan;
    only the max_suggestions cut is dropped, since seeing past it is the point.
    Returns (tier1, tier2, tier3a, tier3b) lists of pre-sort tuples.
    """
    settings = _config()[2]
    min_len = settings["min_word_length"]
    delta = settings["max_length_delta"]
    freq = _freq_table()
    relaxed = dict(costs)
    relaxed["max_transpositions"] = _RELAXED_TRANSPOSITIONS

    tier1, tier2, tier3a, tier3b = [], [], [], []
    for cand in all_words():
        if cand == word or len(cand) < min_len:
            continue
        if abs(len(cand) - len(word)) > delta:
            continue
        cap = spell_check.distance_cap(cand, costs)
        f = freq.get(cand, 0)
        scored = spell_check._match(word, cand, costs, tails)
        if scored is not None:
            exo, edits = scored
            if edits <= cap:
                tier1.append((exo, edits, -f, cand, cap, f))
            else:
                tier2.append((edits, exo, -f, cand, cap, f))
            continue
        scored_r = spell_check._match(word, cand, relaxed, tails)
        if scored_r is not None and scored_r[1] <= cap:
            exo_r, edits_r = scored_r
            tier3a.append((edits_r, exo_r, -f, cand, cap, f))
        else:
            raw = spell_check._levenshtein(word, cand)
            tier3b.append((raw, -f, cand, f))

    tier1.sort()
    tier2.sort()
    tier3a.sort()
    tier3b.sort()
    return tier1, tier2, tier3a, tier3b


def _spacer():
    print("=" * 60)


def _print_tier1(rows, top, max_suggestions):
    print("TIER 1 -- accepted suggestions, ranked as in-game "
          "(exoticness, edits, -freq).")
    print("         The first %d are what the player SEES; the rest are the "
          "next best, cut by max_suggestions." % max_suggestions)
    if not rows:
        print("  (none)")
        return
    print("  %-4s %-16s %-10s %-6s %-5s %-12s %s"
          % ("#", "word", "exoticness", "edits", "cap", "freq", "shown?"))
    for i, (exo, edits, _negf, cand, cap, f) in enumerate(rows[:top], start=1):
        shown = "<- SHOWN" if i <= max_suggestions else ""
        print("  %-4d %-16s %-10d %-6d %-5d %-12d %s"
              % (i, cand, exo, edits, cap, f, shown))


def _print_tier2(rows, top):
    print("TIER 2 -- rejected: run alignment is legal, but edits exceed the "
          "distance cap")
    print("         (cap = max(base_distance, vowel_runs * "
          "distance_per_vowel_run)). Nearest-to-passing first.")
    if not rows:
        print("  (none)")
        return
    print("  %-16s %-6s %-5s %-10s %-12s"
          % ("word", "edits", "cap", "exoticness", "freq"))
    for edits, exo, _negf, cand, cap, f in rows[:top]:
        print("  %-16s %-6d %-5d %-10d %-12d" % (cand, edits, cap, exo, f))


def _print_tier3(tier3a, tier3b, top):
    print("TIER 3 -- rejected: no allowed run alignment "
          "(max_transpositions / V-C pattern).")
    print("  3a) transposition-limited: WOULD align within the cap if "
          "max_transpositions were raised.")
    if not tier3a:
        print("      (none)")
    else:
        print("      %-16s %-14s %-10s %-12s"
              % ("word", "edits(relaxed)", "exoticness", "freq"))
        for edits_r, exo_r, _negf, cand, _cap, f in tier3a[:top]:
            print("      %-16s %-14d %-10d %-12d" % (cand, edits_r, exo_r, f))
    print("  3b) pattern violation: no alignment even with unlimited "
          "transpositions; ranked by raw edit distance.")
    if not tier3b:
        print("      (none)")
    else:
        print("      %-16s %-14s %-12s" % ("word", "raw_distance", "freq"))
        for raw, _negf, cand, f in tier3b[:top]:
            print("      %-16s %-14d %-12d" % (cand, raw, f))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Debug the game's spelling-suggestion algorithm for one "
                    "typed word.")
    parser.add_argument("word", help="the (mis)typed word to diagnose")
    parser.add_argument("--top", type=int, default=20,
                        help="rows to show per tier (default 20)")
    opts = parser.parse_args(argv)

    word = opts.word.strip().upper()
    costs, tails, settings = _config()

    print("Spell-check debug for typed word: %s" % word)
    print("Live config: min_word_length=%d  max_suggestions=%d  base_distance=%d"
          "  distance_per_vowel_run=%d  max_transpositions=%d  max_length_delta=%d"
          % (settings["min_word_length"], settings["max_suggestions"],
             costs["base_distance"], costs["distance_per_vowel_run"],
             costs["max_transpositions"], settings["max_length_delta"]))
    if len(word) < settings["min_word_length"]:
        print("NOTE: typed word is shorter than min_word_length -- the game "
              "would offer NO suggestions; showing analysis anyway.")
    if is_word(word):
        print("NOTE: typed word IS in the dictionary -- the game only suggests "
              "for non-words; showing analysis anyway.")
    print()

    tier1, tier2, tier3a, tier3b = _classify(word, costs, tails)
    _print_tier1(tier1, opts.top, settings["max_suggestions"])
    _spacer()
    _print_tier2(tier2, opts.top)
    _spacer()
    _print_tier3(tier3a, tier3b, opts.top)


if __name__ == "__main__":
    main()
