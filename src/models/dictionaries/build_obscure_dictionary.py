#!/usr/bin/env python3
"""Build the OBSCURE tier: real-but-uncommon words the main tier omits.

The main tier (build_expanded_dictionary.py) descends from 6of12 -- words in at
least 6 of 12 source dictionaries. This obscure tier is mined from 2of12 (words
in at least 2 of 12), the same 12dicts release, so it holds the long tail:
"revisionist", "aftercare", "acetonic" -- real words too rare for the main list.

Inputs (in ./sources/):
  - sources/12dicts-2of12.txt   : the flat 2of12 American word list (~41k). Its
        compounds are listed inline, so mining it wholesale keeps them -- no
        separate compound step (unlike the main build, which had to re-admit
        compounds its curated headword file had stripped).
  - sources/12dicts-2+2+3lem.txt : the shared lemmatized list, for inflecting
        each obscure headword (see lemmas.py). Reused from the main build.

Also reads the finished main tier (../expandedAllowedWords.txt) so the obscure
set can be made EXCLUSIVE: every 2of12 word (and inflection) NOT already in the
main tier. "Exclusive" is what the game keys the +2 obscurity surcharge and the
orange "new obscure word" highlight on -- a word in both tiers counts as main.

Outputs (alongside the main tier's files):
  - expandedAllowedWords_obscure.txt   : flat, sorted, one word per line. Every
        exclusively-obscure form. The game unions this with the main tier when
        dictionary.include_obscure is on (see models/word_dictionary.py).
  - obscureHeadwordInflections.json    : { obscure headword: [extra forms...] }.
  - obscureHeadwordInflections.txt     : same map, human-readable.

Run:  python3 build_obscure_dictionary.py
"""

import json
import os

from lemmas import Lemmatizer, load_wordlist

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "sources")

OBSCURE_SOURCE_FILE = os.path.join(SRC, "12dicts-2of12.txt")
LEM_FILE = os.path.join(SRC, "12dicts-2+2+3lem.txt")
MAIN_FLAT_FILE = os.path.join(HERE, "expandedAllowedWords.txt")

OUT_FLAT = os.path.join(HERE, "expandedAllowedWords_obscure.txt")
OUT_JSON = os.path.join(HERE, "obscureHeadwordInflections.json")
OUT_TXT = os.path.join(HERE, "obscureHeadwordInflections.txt")


# ---------------------------------------------------------------------------
# 1. Load the finished main tier and the obscure source
# ---------------------------------------------------------------------------
with open(MAIN_FLAT_FILE, encoding="utf-8") as f:
    main_set = {line.strip().lower() for line in f if line.strip()}
print(f"main tier words: {len(main_set)}")

source_2of12 = load_wordlist(OBSCURE_SOURCE_FILE)
# The obscure headwords: every 2of12 word the main tier does not already have.
obscure_headwords = {w for w in source_2of12 if w not in main_set}
print(f"2of12 words: {len(source_2of12)}   "
      f"not in main tier (obscure headwords): {len(obscure_headwords)}")


# ---------------------------------------------------------------------------
# 2. Inflect each obscure headword through the shared lemmatized families,
#    keeping only forms the main tier lacks (so the tier stays EXCLUSIVE).
# ---------------------------------------------------------------------------
LEM = Lemmatizer(LEM_FILE)
print(f"lemma families parsed: {len(LEM.families)}")


def obscure_family(h):
    """h's inflected family (from lemmas), restricted to forms not already in
    the main tier. Always includes h (an obscure headword is never in main)."""
    forms = {w for w in LEM.family_for_headword(h) if w not in main_set}
    forms.add(h)
    return forms


hw_forms = {h: obscure_family(h) for h in obscure_headwords}

allowed = set()
for forms in hw_forms.values():
    allowed |= forms
singletons = sum(1 for h in obscure_headwords if hw_forms[h] == {h})
print(f"exclusively-obscure forms: {len(allowed)}   "
      f"headwords with no extra inflections: {singletons}")


# ---------------------------------------------------------------------------
# 3. Write outputs (same shape + invariant as the main build)
# ---------------------------------------------------------------------------
# map: obscure headword -> sorted extra forms (family minus the headword). Keys
# that are themselves another headword's inflection still appear (as in the main
# build); the union of keys+values equals the flat list either way.
headword_map = {}
for h in sorted(obscure_headwords):
    headword_map[h] = sorted(f for f in hw_forms[h] if f != h)

with open(OUT_FLAT, "w", encoding="utf-8") as f:
    for w in sorted(allowed):
        f.write(w + "\n")

with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(headword_map, f, ensure_ascii=False, indent=0, sort_keys=True)

with open(OUT_TXT, "w", encoding="utf-8") as f:
    for h in sorted(headword_map):
        extras = headword_map[h]
        f.write(f"{h}: {', '.join(extras)}\n" if extras else f"{h}:\n")

# sanity: keys + values == flat, and the tier is disjoint from the main tier
map_union = set(headword_map.keys())
for v in headword_map.values():
    map_union |= set(v)
print(f"flat words: {len(allowed)}   map union: {len(map_union)}   "
      f"equal: {allowed == map_union}")
print(f"disjoint from main tier: {allowed.isdisjoint(main_set)}")
print(f"wrote:\n  {OUT_FLAT}\n  {OUT_JSON}\n  {OUT_TXT}")
