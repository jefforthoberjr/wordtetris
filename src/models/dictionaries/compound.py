#!/usr/bin/env python3
"""Closed-compound detection shared by the main + obscure dictionary builds.

A CLOSED COMPOUND is a single-token, pure-letter word that splits into two
real words -- "airport" = air + port, "mailbox" = mail + box. The headword
thinning that produced spellingDictionary20k-nocompound.txt stripped these out
(hence "-nocompound"); the main build re-admits them from its 6of12 lineage.

Every admitted word is gated by appearing in the source list, so it is always a
real word -- the split test only decides WHICH real words to re-admit (those
that look like compounds). Only the main tier needs this: the obscure tier is
mined wholesale from 2of12, which lists its compounds directly.
"""


def find_compounds(source, part_lexicon, exclude, minpart=3):
    """{compound: (part1, part2)} for every `source` word NOT in `exclude` that
    splits into exactly two `part_lexicon` words, each at least `minpart` long.
    The first (leftmost-longest-prefix) valid split wins; the parts are only for
    human inspection, the key is what matters."""
    found = {}
    for w in source:
        if w in exclude or len(w) < 2 * minpart:
            continue
        for i in range(minpart, len(w) - minpart + 1):
            if w[:i] in part_lexicon and w[i:] in part_lexicon:
                found[w] = (w[:i], w[i:])
                break
    return found
