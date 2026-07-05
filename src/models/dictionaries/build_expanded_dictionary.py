#!/usr/bin/env python3
"""
Build an inflection-expanded word list from the headword dictionary.

Inputs (in ./sources/):
  - ../spellingDictionary20k-nocompound.txt : the ~21.9k curated HEADWORDS (the
        thinned, no-compound, no-morpheme list the game uses today).
  - sources/12dicts-2+2+3lem.txt            : 12dicts 6.0.2 "Lemmatized" list.
        Format: a lemma flush-left, its inflections on the next line indented 4
        spaces, comma-separated. Markers: trailing '!'/'%', and cross-references
        "word -> [otherlemma]". NOTE: this list ALREADY contains British spellings
        inline as inflections (e.g. color's family lists colour, coloured,
        colourful, colours...), so families pick them up automatically.
  - sources/legacy-20kwords-with-conjugations.txt : a previously-built expansion.
        Used only as a belt-and-suspenders candidate pool for any British/variant
        form 2+2+3lem might miss; a candidate is admitted only if its rule-based
        Americanization lands in one of our headword families, so the "every
        allowed word derives from a kept headword" invariant holds. In practice
        2+2+3lem already covers these, so this step adds ~0 net words.
  - sources/12dicts-6of12.txt : the main tier's own 6of12 lineage, mined for
        CLOSED COMPOUNDS the headword thinning stripped ("-nocompound"). A word
        is re-admitted only if it splits into two already-allowed words (see
        compound.py), then inflected through the same 2+2+3lem families as a
        headword (airport -> airports, airman -> airmen). See obscure tier build
        in build_obscure_dictionary.py.

Outputs (alongside the current dictionary):
  - expandedAllowedWords.txt   : flat, sorted, one word per line. Every inflected
        / British form of every headword. This is the "all words" set.
  - headwordInflections.json   : { headword: [extra forms...] } for all 21.9k
        headwords. Keys = the headword set (a player_dictionary can use just the
        keys); keys + values (deduped) == expandedAllowedWords.txt.
  - headwordInflections.txt    : same map, human-readable ("headword: a, b, c").

Run:  python3 build_expanded_dictionary.py
"""

import json
import os

import compound
from lemmas import Lemmatizer, is_word, load_wordlist

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "sources")

HEADWORDS_FILE = os.path.join(HERE, "spellingDictionary20k-nocompound.txt")
LEM_FILE = os.path.join(SRC, "12dicts-2+2+3lem.txt")
BRITISH_POOL_FILE = os.path.join(SRC, "legacy-20kwords-with-conjugations.txt")
# The 6of12 list (the main tier's own lineage) is the pool we mine CLOSED
# COMPOUNDS from -- single-token words like "airport" the headword thinning
# dropped (the "-nocompound" in the headwords filename). See compound.py.
COMPOUND_SOURCE_FILE = os.path.join(SRC, "12dicts-6of12.txt")

OUT_FLAT = os.path.join(HERE, "expandedAllowedWords.txt")
OUT_JSON = os.path.join(HERE, "headwordInflections.json")
OUT_TXT = os.path.join(HERE, "headwordInflections.txt")

# ---------------------------------------------------------------------------
# 1. Load headwords
# ---------------------------------------------------------------------------
with open(HEADWORDS_FILE, encoding="utf-8") as f:
    headwords = [line.strip().lower() for line in f if line.strip()]
headword_set = set(headwords)
print(f"headwords: {len(headwords)} ({len(headword_set)} unique)")


# ---------------------------------------------------------------------------
# 2. Parse the lemmatized list into per-lemma families (shared -- see lemmas.py)
# ---------------------------------------------------------------------------
LEM = Lemmatizer(LEM_FILE)
family_for_headword = LEM.family_for_headword
print(f"lemma families parsed: {len(LEM.families)}")


# ---------------------------------------------------------------------------
# 3. Build headword -> family forms, using the headword set as the keys
# ---------------------------------------------------------------------------
# headword -> set of forms (including the headword itself, for now)
hw_forms = {h: family_for_headword(h) for h in headword_set}

# the American allowed set = every form reachable from a headword
allowed = set(headword_set)
for forms in hw_forms.values():
    allowed |= forms

absent = [h for h in headword_set if hw_forms[h] == {h}]
print(f"American allowed forms: {len(allowed)}")
print(f"headwords with no inflections found (singletons): {len(absent)}")


# ---------------------------------------------------------------------------
# 4. Admit British spellings from the legacy pool (gated by Americanization)
# ---------------------------------------------------------------------------
# Reverse-British rules: British spelling -> candidate American spelling(s).
# Aggressive is safe: a candidate is only accepted if it is already an allowed
# American form, so wrong transforms simply fail to match.
def americanize(w):
    cands = set()

    def add(x):
        if x != w and is_word(x):
            cands.add(x)

    add(w.replace("our", "or"))                 # colour -> color
    add(w.replace("ise", "ize"))                # organise -> organize
    add(w.replace("isa", "iza"))                # organisation -> organization
    add(w.replace("yse", "yze"))                # analyse -> analyze
    add(w.replace("ae", "e"))                   # anaemia -> anemia
    add(w.replace("oe", "e"))                   # foetus -> fetus
    if w.endswith("re"):
        add(w[:-2] + "er")                      # centre -> center
    if w.endswith("res"):
        add(w[:-3] + "ers")                     # centres -> centers
    if w.endswith("ogue"):
        add(w[:-4] + "og")                      # catalogue -> catalog
    if w.endswith("ogues"):
        add(w[:-5] + "ogs")
    if w.endswith("ence"):
        add(w[:-4] + "ense")                    # defence -> defense
    if w.endswith("ences"):
        add(w[:-5] + "enses")
    if w.endswith("mme"):
        add(w[:-3] + "m")                       # programme -> program
    if w.endswith("mmes"):
        add(w[:-4] + "ms")
    for a, b in (("lled", "led"), ("lling", "ling"), ("ller", "ler"),
                 ("llor", "lor"), ("llous", "lous"), ("lment", "llment"),
                 ("lful", "llful")):
        if w.endswith(a):
            add(w[: -len(a)] + b)               # travelled -> traveled, etc.
    # combined our+inflection already covered by global replace above
    return cands


british_pool = set()
with open(BRITISH_POOL_FILE, encoding="utf-8") as f:
    for line in f:
        w = line.strip().lower()
        if is_word(w):
            british_pool.add(w)

british_added = 0
for w in british_pool:
    if w in allowed:
        continue
    hit_forms = [c for c in americanize(w) if c in allowed]
    if not hit_forms:
        continue
    allowed.add(w)
    british_added += 1
    # attach w to every headword whose family contains a hit form
    hit_set = set(hit_forms)
    for h, forms in hw_forms.items():
        if forms & hit_set:
            forms.add(w)

print(f"British spellings admitted: {british_added}")
print(f"total allowed forms: {len(allowed)}")


# ---------------------------------------------------------------------------
# 4.5 Re-introduce closed compounds from 6of12 (the "-nocompound" headword
#     thinning had stripped these; mine them back from the main tier's own
#     lineage). A compound seed is admitted only if it splits into two
#     already-allowed words, so every seed is a real 6of12 word (see
#     compound.py). Each seed is then inflected through the SAME lemmatized
#     families as a headword, so "airport" pulls in "airports" etc. -- no
#     rule-based over-generation.
# ---------------------------------------------------------------------------
source_6of12 = load_wordlist(COMPOUND_SOURCE_FILE)
compound_seeds = set(compound.find_compounds(source_6of12, allowed, exclude=allowed))
comp_families = {c: family_for_headword(c) for c in compound_seeds}
compound_forms = set()
for fam in comp_families.values():
    compound_forms |= fam
# Each seed is its own compound headword, keyed to its family's other forms.
# (6of12 lists only bare compounds, so a seed is never another seed's inflection
# -- no cross-keying to dedupe.)
compound_map = {c: sorted(f for f in fam if f != c)
                for c, fam in comp_families.items()}
allowed |= compound_forms
print(f"compounds re-introduced from 6of12: {len(compound_forms)} "
      f"(under {len(compound_map)} base headwords)")
print(f"total allowed forms (with compounds): {len(allowed)}")


# ---------------------------------------------------------------------------
# 5. Write outputs
# ---------------------------------------------------------------------------
# map: headword -> sorted extra forms (family minus the headword itself)
headword_map = {}
for h in sorted(headword_set):
    extras = sorted(f for f in hw_forms[h] if f != h)
    headword_map[h] = extras
# fold in the compound headwords (their keys are disjoint from the headword set)
for h, extras in compound_map.items():
    headword_map[h] = sorted(set(headword_map.get(h, [])) | set(extras))

with open(OUT_FLAT, "w", encoding="utf-8") as f:
    for w in sorted(allowed):
        f.write(w + "\n")

with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(headword_map, f, ensure_ascii=False, indent=0, sort_keys=True)

with open(OUT_TXT, "w", encoding="utf-8") as f:
    for h in sorted(headword_map):
        extras = headword_map[h]
        f.write(f"{h}: {', '.join(extras)}\n" if extras else f"{h}:\n")

# sanity: keys + values == flat
map_union = set(headword_map.keys())
for v in headword_map.values():
    map_union |= set(v)
print(f"flat words: {len(allowed)}   map union: {len(map_union)}   equal: {allowed == map_union}")
print(f"wrote:\n  {OUT_FLAT}\n  {OUT_JSON}\n  {OUT_TXT}")
