"""Fetch the CLDR emoji annotations and pre-join them against the dictionary.

Unicode's CLDR gives every emoji an English name plus ~10 keywords (repackaged by
the emojibase project as one JSON file). Joined against the 20k dictionary that
covers only ~2,500 words -- 11% -- which is why the rest of this folder exists.
Those 2,500 are still worth having: they are human-curated, so after the swarm
runs, assemble.py diffs the workers against them as a free quality probe.

    python tools/emoji_classify/seed_cldr.py

Writes data/emojibase_en.json (the download, cached) and data/cldr_seed.csv
(`word,emojis` where emojis is a ';'-joined list -- CLDR keywords are many-to-many).
Uses urllib from the stdlib; no new dependency.
"""
import collections
import csv
import json
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
WORDS = os.path.join(ROOT, "src", "models", "dictionaries",
                     "spellingDictionary20k-nocompound.txt")
DATA = os.path.join(HERE, "data")
RAW = os.path.join(DATA, "emojibase_en.json")
SEED = os.path.join(DATA, "cldr_seed.csv")
SOURCE = ("https://raw.githubusercontent.com/milesj/emojibase/master/"
          "packages/data/en/data.raw.json")


def fetch(url, path):
    """Download once and cache -- the file is ~1.2 MB and never changes for a
    given release."""
    if not os.path.isdir(DATA):
        os.makedirs(DATA)
    if not os.path.exists(path):
        urllib.request.urlretrieve(url, path)
    return json.load(open(path, encoding="utf-8"))


def is_plain(emoji):
    """A single base emoji: no ZWJ sequence, no skin tone, no regional-indicator
    flag. The same bar the rubric puts on the workers, so both sides of the
    comparison are drawn from one roster."""
    plain = True
    if "‍" in emoji:
        plain = False
    for char in emoji:
        point = ord(char)
        if 0x1F3FB <= point <= 0x1F3FF or 0x1F1E6 <= point <= 0x1F1FF:
            plain = False
    return plain


def roster(data):
    """{emoji -> CLDR label} for every plain emoji in the annotation file. The
    validation roster assemble.py checks worker output against."""
    names = {}
    for entry in data:
        emoji = entry.get("emoji") or ""
        if emoji and is_plain(emoji):
            names[emoji] = entry.get("label") or ""
    return names


def seed(data, words):
    """{word -> [emoji]} for dictionary words that appear as a CLDR label or
    keyword. Multi-word labels ("nerd face") also contribute their tokens, which
    is what lifts coverage from ~1,600 exact hits to ~2,500."""
    hits = collections.defaultdict(list)
    for entry in data:
        emoji = entry.get("emoji") or ""
        if not emoji or not is_plain(emoji):
            continue
        terms = [entry.get("label") or ""] + list(entry.get("tags") or [])
        seen = set()
        for term in terms:
            text = term.strip().lower()
            for token in [text] + text.replace("-", " ").split():
                if token in words and token not in seen:
                    seen.add(token)
                    hits[token].append(emoji)
    return hits


def main():
    words = set()
    for line in open(WORDS, encoding="utf-8"):
        word = line.strip().lower()
        if word:
            words.add(word)
    data = fetch(SOURCE, RAW)
    hits = seed(data, words)
    with open(SEED, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["word", "emojis"])
        for word in sorted(hits):
            writer.writerow([word, ";".join(hits[word])])
    print("%d emoji annotations, %d plain in roster, %d/%d dictionary words seeded"
          % (len(data), len(roster(data)), len(hits), len(words)))
    print("wrote %s" % SEED)


main()
