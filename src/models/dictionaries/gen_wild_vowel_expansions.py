"""Regenerate wild_vowel_expansions.txt from the word dictionary.

A wild-vowel cell can stand for a run of 1-3 vowels, but most of the 258
theoretical runs over {A,E,I,O,U,Y} never occur in real words. This scans the
dictionary and keeps only the vowel runs (length 1-3) that actually appear as a
contiguous substring of some word, so the pathfinder branches over a realistic
~100-entry set instead of all 258.

Run from the src/ directory:  python models/dictionaries/gen_wild_vowel_expansions.py
"""
import os

VOWELS = set("AEIOUY")
_HERE = os.path.dirname(__file__)
_DICT = os.path.join(_HERE, "spellingDictionary20k-nocompound.txt")
_OUT = os.path.join(_HERE, "wild_vowel_expansions.txt")


def main():
    found = set()
    with open(_DICT) as f:
        for line in f:
            word = line.strip().upper()
            if not word:
                continue
            n = len(word)
            for i in range(n):
                run = ""
                for k in range(3):
                    if i + k >= n or word[i + k] not in VOWELS:
                        break
                    run += word[i + k]
                    found.add(run)
    ordered = sorted(found, key=lambda s: (len(s), s))
    with open(_OUT, "w") as f:
        for run in ordered:
            f.write(run + "\n")
    print("wrote", len(ordered), "expansions to", _OUT)


main()
