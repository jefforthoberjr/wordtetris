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
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "sources")

HEADWORDS_FILE = os.path.join(HERE, "spellingDictionary20k-nocompound.txt")
LEM_FILE = os.path.join(SRC, "12dicts-2+2+3lem.txt")
BRITISH_POOL_FILE = os.path.join(SRC, "legacy-20kwords-with-conjugations.txt")

OUT_FLAT = os.path.join(HERE, "expandedAllowedWords.txt")
OUT_JSON = os.path.join(HERE, "headwordInflections.json")
OUT_TXT = os.path.join(HERE, "headwordInflections.txt")

WORD_RE = re.compile(r"^[a-z]+$")


def is_word(w):
    """Keep pure lowercase alphabetic forms only (matches the headword list:
    no hyphens, spaces, apostrophes, or compounds)."""
    return bool(WORD_RE.match(w))


def clean_token(tok):
    """Strip a 12dicts token down to a bare lowercase word.
    Removes cross-ref annotations ' -> [lemma]' and trailing markers '!','%'."""
    tok = re.sub(r"\s*->\s*\[[^\]]*\]", "", tok)
    tok = tok.strip().strip("!%*~ ").strip()
    return tok.lower()


# ---------------------------------------------------------------------------
# 1. Load headwords
# ---------------------------------------------------------------------------
with open(HEADWORDS_FILE, encoding="utf-8") as f:
    headwords = [line.strip().lower() for line in f if line.strip()]
headword_set = set(headwords)
print(f"headwords: {len(headwords)} ({len(headword_set)} unique)")


# ---------------------------------------------------------------------------
# 2. Parse the lemmatized list into per-lemma families + cross-references
# ---------------------------------------------------------------------------
# families[lemma] = set(forms)  (always includes the lemma itself)
# member_of[form] = set(lemmas whose family contains this form)
# xref[form] = lemma  (from "form -> [lemma]" pointer lines)
families = {}
member_of = {}
xref = {}


def add_member(lemma, form):
    if not is_word(form):
        return
    families.setdefault(lemma, set()).add(form)
    member_of.setdefault(form, set()).add(lemma)


current_lemma = None
with open(LEM_FILE, encoding="utf-8") as f:
    for raw in f:
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if line.startswith("    "):
            # inflection line for the current lemma
            if current_lemma is None:
                continue
            for item in line.split(","):
                form = clean_token(item)
                if form:
                    add_member(current_lemma, form)
        else:
            # a lemma line, possibly a "word -> [target]" pointer
            m = re.match(r"^(\S+)\s*->\s*\[([^\]]+)\]", line.strip())
            if m:
                form = clean_token(m.group(1))
                target = clean_token(m.group(2))
                if form and target:
                    xref[form] = target
                # pointer lines do not open a normal family block
                current_lemma = None
            else:
                lemma = clean_token(line.split()[0])
                current_lemma = lemma if lemma else None
                if current_lemma:
                    add_member(current_lemma, current_lemma)

# resolve cross-references: a "form -> [target]" means form belongs to target's family
for form, target in xref.items():
    add_member(target, form)

print(f"lemma families parsed: {len(families)}")


# ---------------------------------------------------------------------------
# 3. Build headword -> family forms, using the headword set as the keys
# ---------------------------------------------------------------------------
def family_for_headword(h):
    """All forms related to headword h: h's own family (if h is a lemma), the
    families of any lemma that lists h as an inflection, and any xref target."""
    lemmas = set()
    if h in families:
        lemmas.add(h)
    lemmas |= member_of.get(h, set())
    if h in xref:
        lemmas.add(xref[h])
    forms = {h}
    for L in lemmas:
        forms |= families.get(L, set())
    return {w for w in forms if is_word(w)}


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
# 5. Write outputs
# ---------------------------------------------------------------------------
# map: headword -> sorted extra forms (family minus the headword itself)
headword_map = {}
for h in sorted(headword_set):
    extras = sorted(f for f in hw_forms[h] if f != h)
    headword_map[h] = extras

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
