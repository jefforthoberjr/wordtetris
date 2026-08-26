"""Reconstitute the emoji pass: validate the worker chunks, then write both CSVs.

Run after the swarm has filled run/out/. Three jobs:

  1. VALIDATE. Every chunk's rows must line up word-for-word, in order, with the
     chunk it was dealt (a worker that skips or reorders is the classic bulk-run
     failure), the fit must be 1-3, and the emoji must be a plain single emoji on
     the CLDR roster -- no ZWJ professions, no skin tones, no flags, however
     reasonable they look. Anything failing lands in run/repair/chunk_NN as a word
     list to re-run; nothing failing reaches the CSVs.
  2. INDEX BOTH WAYS. out/words_emoji.csv is alphabetical by WORD (what the game
     reads -- the stocking rules all start from a word). out/emoji_words.csv is
     indexed by EMOJI with the full word list per picture (the research view: what
     does the dictionary look like grouped into ~1,900 pictures).
  3. DIFF AGAINST CLDR. out/cldr_compare.csv scores the workers on the ~2,400
     words Unicode already annotated -- a free accuracy probe on a run nobody can
     hand-check.

    python tools/emoji_classify/assemble.py
"""
import collections
import csv
import json
import os

import rollup_by_emoji

HERE = os.path.dirname(os.path.abspath(__file__))
IN_DIR = os.path.join(HERE, "run", "in")
OUT_DIR = os.path.join(HERE, "run", "out")
REPAIR_DIR = os.path.join(HERE, "run", "repair")
EXTRA_DIR = os.path.join(HERE, "run", "out", "extra")
DATA = os.path.join(HERE, "data")
FINAL = os.path.join(HERE, "out")
RAW = os.path.join(DATA, "emojibase_en.json")
SEED = os.path.join(DATA, "cldr_seed.csv")


def is_plain(emoji):
    """One base emoji, no ZWJ sequence / skin tone / regional-indicator flag."""
    plain = True
    if "‍" in emoji:
        plain = False
    for char in emoji:
        point = ord(char)
        if 0x1F3FB <= point <= 0x1F3FF or 0x1F1E6 <= point <= 0x1F1FF:
            plain = False
    return plain


def load_roster():
    """{bare emoji -> (canonical emoji, CLDR label)} of everything a worker may
    emit. Keyed by the form with variation selectors STRIPPED, because a worker
    writing the text-style form and one writing the emoji-style form mean the same
    picture and both should match.

    The value keeps the CANONICAL form -- U+FE0F included where Unicode says the
    character needs it. That selector is what asks the font for the colour glyph:
    without it, characters like the umbrella and the chains come back as flat
    monochrome text in the game, so the canonical form is what gets written to the
    CSVs, never the worker's."""
    names = {}
    for entry in json.load(open(RAW, encoding="utf-8")):
        emoji = entry.get("emoji") or ""
        if emoji and is_plain(emoji):
            names[emoji.replace("️", "")] = (emoji, entry.get("label") or "")
    return names


def load_chunk_words(name):
    words = []
    for line in open(os.path.join(IN_DIR, name), encoding="utf-8"):
        word = line.strip().lower()
        if word:
            words.append(word)
    return words


def read_rows(path):
    rows = []
    if os.path.exists(path):
        for row in csv.reader(open(path, encoding="utf-8")):
            # Header test looks at the SECOND column, not the first: "word" is
            # itself a dictionary word, and keying off column 1 silently dropped
            # its row on every pass.
            if len(row) >= 3 and row[1].strip().lower() != "emoji":
                rows.append((row[0].strip().lower(), row[1].strip(),
                             row[2].strip()))
    return rows


def load_extra():
    """Loose `word,emoji,fit` rows from run/out/extra/*.csv, keyed by word.

    This is where REPAIR passes land. A repair batch is gathered from many chunks
    at once (the strays are a handful per chunk), so its output cannot be written
    back as a chunk file; instead it is dropped here and used to fill any word its
    own chunk is still missing. A repaired word therefore needs no edit to the
    original chunk CSV, and re-running a repair is idempotent."""
    extra = {}
    if os.path.isdir(EXTRA_DIR):
        for name in sorted(os.listdir(EXTRA_DIR)):
            if name.endswith(".csv"):
                for word, emoji, fit in read_rows(os.path.join(EXTRA_DIR, name)):
                    extra[word] = (emoji, fit)
    return extra


def validate_chunk(name, roster, extra):
    """Check one chunk and split it into (good rows, words needing a re-run).
    A missing output file sends the WHOLE chunk to repair, which is how an
    unfinished or killed worker shows up."""
    expected = load_chunk_words(name)
    rows = read_rows(os.path.join(OUT_DIR, name + ".csv"))
    # Start from the repair rows, then let the chunk override -- but ONLY where the
    # chunk's own answer is valid. The rejected row is exactly what the repair pass
    # was run to replace, so it must never win; and a word the chunk answered well
    # keeps that answer, so a stale repair file cannot overwrite good work.
    by_word = dict(extra)
    for word, emoji, fit in rows:
        bare = emoji.replace("️", "")
        if fit in ("1", "2", "3") and bare and bare in roster:
            by_word[word] = (emoji, fit)
    good = []
    broken = []
    for word in expected:
        entry = by_word.get(word)
        keep = False
        if entry is not None:
            emoji, fit = entry
            bare = emoji.replace("️", "")
            if fit in ("1", "2", "3") and bare and bare in roster:
                good.append((word, roster[bare][0], int(fit)))
                keep = True
        if not keep:
            broken.append(word)
    return good, broken, len(rows), len(expected)


def clear_repair():
    """Wipe last run's repair queue before writing this one. Without this a chunk
    that has since been fixed keeps its stale file, and the queue reads as work
    outstanding forever -- the folder must always mean "what is broken RIGHT NOW"."""
    if not os.path.isdir(REPAIR_DIR):
        os.makedirs(REPAIR_DIR)
    for name in os.listdir(REPAIR_DIR):
        os.remove(os.path.join(REPAIR_DIR, name))


def write_repair(name, words):
    if not os.path.isdir(REPAIR_DIR):
        os.makedirs(REPAIR_DIR)
    path = os.path.join(REPAIR_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(words) + "\n")


def write_word_index(rows):
    """Alphabetical by word -- the file the game reads. `image` is the empty
    column the idea belt's deck format already carries, so a hand-drawn or
    thenounproject icon can be dropped in per word later without a schema change."""
    path = os.path.join(FINAL, "words_emoji.csv")
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["word", "image", "emoji", "fit"])
        for word, emoji, fit in sorted(rows):
            writer.writerow([word, "", emoji, fit])
    return path


# The emoji-indexed file is built by rollup_by_emoji, so the pipeline and the
# standalone analysis tool cannot drift apart. That module is importable (its
# main() is guarded) precisely so this delegation works.


def write_emoji_index(rows, roster):
    """Indexed by emoji: every dictionary word that landed on that picture. See
    rollup_by_emoji, which owns the format and can also be re-run by hand against
    a different mapping."""
    labels = {}
    for bare in roster:
        labels[bare] = roster[bare][1]
    return rollup_by_emoji.write_emoji_index(rows, labels)


def write_cldr_compare(rows):
    """The workers vs Unicode, on the words CLDR annotates. `agree` is whether the
    worker's pick is among the emoji CLDR keys that word to -- a loose test on
    purpose (CLDR lists several emoji per keyword and any of them is defensible)."""
    seed = {}
    if os.path.exists(SEED):
        for row in csv.reader(open(SEED, encoding="utf-8")):
            if len(row) >= 2 and row[0] != "word":
                seed[row[0]] = row[1].split(";")
    path = os.path.join(FINAL, "cldr_compare.csv")
    agree = 0
    total = 0
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["word", "llm_emoji", "fit", "cldr_emojis", "agree"])
        for word, emoji, fit in sorted(rows):
            if word not in seed:
                continue
            # Compare with selectors stripped from BOTH sides -- the rows now carry
            # the canonical form, and ⛓️ vs ⛓ is the same picture, not a miss.
            cldr = [e.replace("️", "") for e in seed[word]]
            hit = emoji.replace("️", "") in cldr
            total = total + 1
            if hit:
                agree = agree + 1
            writer.writerow([word, emoji, fit, ";".join(seed[word]),
                             "true" if hit else "false"])
    return path, agree, total


def main():
    if not os.path.isdir(FINAL):
        os.makedirs(FINAL)
    clear_repair()
    roster = load_roster()
    extra = load_extra()
    names = sorted(os.listdir(IN_DIR))
    rows = []
    repaired = 0
    for name in names:
        good, broken, got, want = validate_chunk(name, roster, extra)
        rows.extend(good)
        if broken:
            write_repair(name, broken)
            repaired = repaired + len(broken)
            print("  %s: %d/%d rows, %d need a re-run" % (name, got, want,
                                                          len(broken)))
    fits = collections.Counter(fit for word, emoji, fit in rows)
    print("%d chunks, %d words classified, %d queued for repair"
          % (len(names), len(rows), repaired))
    print("fit 3: %d   fit 2: %d   fit 1: %d"
          % (fits[3], fits[2], fits[1]))
    print("wrote %s" % write_word_index(rows))
    path, pictures = write_emoji_index(rows, roster)
    print("wrote %s (%d distinct emoji)" % (path, pictures))
    path, agree, total = write_cldr_compare(rows)
    share = 0.0
    if total:
        share = 100.0 * agree / total
    print("wrote %s (%d/%d agree with CLDR, %.1f%%)"
          % (path, agree, total, share))


main()
