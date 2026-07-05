#!/usr/bin/env python3
"""Shared 12dicts "Lemmatized" (2+2+3lem) parsing for the dictionary builds.

Both the main build (build_expanded_dictionary.py) and the obscure build
(build_obscure_dictionary.py) turn a set of base words into their full inflected
families using the same lemmatized list, so that logic lives here once.

Format of the lemmatized list: a lemma flush-left, its inflections on the next
line indented 4 spaces, comma-separated. Markers: trailing '!'/'%', and
cross-references "word -> [otherlemma]". British spellings appear inline as
inflections, so families pick them up automatically.
"""

import re

WORD_RE = re.compile(r"^[a-z]+$")


def is_word(w):
    """Keep pure lowercase alphabetic forms only (no hyphens, spaces,
    apostrophes) -- matching the game's pure-letter board."""
    return bool(WORD_RE.match(w))


def clean_token(tok):
    """Strip a 12dicts token down to a bare lowercase word. Removes cross-ref
    annotations ' -> [lemma]' and trailing markers '!','%','*','~'."""
    tok = re.sub(r"\s*->\s*\[[^\]]*\]", "", tok)
    tok = tok.strip().strip("!%*~ ").strip()
    return tok.lower()


def load_wordlist(path):
    """A flat 12dicts list as a set of bare lowercase words. Strips CRLF and the
    trailing 12dicts markers (# = & % ^ ! ~ *) and keeps pure-alphabetic tokens
    only -- so hyphenated / spaced / apostrophe entries are dropped, matching the
    game's pure-letter board."""
    words = set()
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            w = line.strip().strip("#=&%^!~* ").lower()
            if is_word(w):
                words.add(w)
    return words


class Lemmatizer:
    """Parsed lemmatized list, giving each base word its inflected family.

    families[lemma]  = set(forms)   (always includes the lemma itself)
    member_of[form]  = set(lemmas whose family contains this form)
    xref[form]       = lemma        (from "form -> [lemma]" pointer lines)
    """

    def __init__(self, lem_file):
        self.families = {}
        self.member_of = {}
        self.xref = {}
        self._parse(lem_file)

    def _add_member(self, lemma, form):
        if not is_word(form):
            return
        self.families.setdefault(lemma, set()).add(form)
        self.member_of.setdefault(form, set()).add(lemma)

    def _parse(self, lem_file):
        current_lemma = None
        with open(lem_file, encoding="utf-8") as f:
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
                            self._add_member(current_lemma, form)
                else:
                    # a lemma line, possibly a "word -> [target]" pointer
                    m = re.match(r"^(\S+)\s*->\s*\[([^\]]+)\]", line.strip())
                    if m:
                        form = clean_token(m.group(1))
                        target = clean_token(m.group(2))
                        if form and target:
                            self.xref[form] = target
                        current_lemma = None      # pointer opens no family block
                    else:
                        lemma = clean_token(line.split()[0])
                        current_lemma = lemma if lemma else None
                        if current_lemma:
                            self._add_member(current_lemma, current_lemma)
        # resolve cross-references: "form -> [target]" means form is target's kin
        for form, target in self.xref.items():
            self._add_member(target, form)

    def family_for_headword(self, h):
        """All forms related to base word h: h's own family (if h is a lemma),
        the families of any lemma that lists h as an inflection, and any xref
        target. Always includes h itself."""
        lemmas = set()
        if h in self.families:
            lemmas.add(h)
        lemmas |= self.member_of.get(h, set())
        if h in self.xref:
            lemmas.add(self.xref[h])
        forms = {h}
        for L in lemmas:
            forms |= self.families.get(L, set())
        return {w for w in forms if is_word(w)}
