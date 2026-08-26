"""Roll a word-indexed emoji file up into an EMOJI-indexed one, for analysis.

    words_emoji.csv   word,image,emoji,fit     one row per WORD   (~21,900 rows)
    emoji_words.csv   emoji,...,words          one row per EMOJI  (~1,100 rows)

The question this answers is "which words all landed on the same picture" -- the
one the word-indexed file cannot show. It is the view that makes the abstract
sinks obvious: 🚫 and ✅ each swallow hundreds of words (abolish, boycott, taboo,
nonrefundable...), while 🦈 carries one. That imbalance is the whole argument for
the fit score, and for eventually splitting the big buckets across a richer symbol
set (thenounproject etc.).

Because the word count per emoji is variable, the words are ONE column holding a
';'-joined list rather than a ragged row of word1..wordN -- a shape a spreadsheet
and csv.reader both still read. There is no image column: this file is about the
emoji, and the word-indexed file is where per-word art belongs.

Re-runnable by design. Point it at any word-indexed file -- a bigger dictionary
pass, or a different emoji mapping entirely -- and it rebuilds:

    python tools/emoji_classify/rollup_by_emoji.py
    python tools/emoji_classify/rollup_by_emoji.py --min-fit 3
    python tools/emoji_classify/rollup_by_emoji.py \
        --input some/other_mapping.csv --output some/other_rollup.csv

This module is also imported by assemble.py, so the pipeline and the standalone
tool build the file exactly one way.

NOT wired into the game -- an analysis artifact. The game reads the word-indexed
file (idea_belt.deck / idea_belt.deck_format).
"""
import argparse
import collections
import csv
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
# The SHIPPED word file by default, not the pipeline's copy under out/ -- this is
# an analysis tool, so it should describe what the game is actually playing with.
WORDS_EMOJI = os.path.join(ROOT, "src", "assets", "idea_belt", "words_emoji.csv")
EMOJI_WORDS = os.path.join(HERE, "out", "emoji_words.csv")
RAW = os.path.join(HERE, "data", "emojibase_en.json")


def load_labels(path=None):
    """{bare emoji -> CLDR label}, for the human-readable column. Optional: a
    missing annotation file just means blank labels, so the rollup still runs
    against a mapping built without the CLDR download."""
    if path is None:
        path = RAW
    labels = {}
    if os.path.exists(path):
        for entry in json.load(open(path, encoding="utf-8")):
            emoji = entry.get("emoji") or ""
            if emoji:
                labels[emoji.replace("️", "")] = entry.get("label") or ""
    return labels


def load_word_rows(path, min_fit=1):
    """Read a word-indexed file into (word, emoji, fit) triples.

    Tolerant of the two column layouts in play: the shipped
    `word,image,emoji,fit` and the bare `word,emoji,fit` a repair batch writes.
    A row with no fit column counts as the best fit, matching how the game's own
    loader treats one."""
    rows = []
    for row in csv.DictReader(open(path, encoding="utf-8")):
        word = (row.get("word") or "").strip()
        emoji = (row.get("emoji") or "").strip()
        fit = (row.get("fit") or "").strip()
        value = 3
        if fit:
            value = int(fit)
        if word and emoji and value >= min_fit:
            rows.append((word, emoji, value))
    return rows


def group_by_emoji(rows):
    """{emoji -> [(word, fit)]}, each list best-fit-first then alphabetical, so
    the words most worth looking at lead every row."""
    grouped = collections.defaultdict(list)
    for word, emoji, fit in rows:
        grouped[emoji].append((word, fit))
    for emoji in grouped:
        grouped[emoji].sort(key=lambda pair: (-pair[1], pair[0]))
    return grouped


def write_emoji_index(rows, labels, path=None):
    """Write the emoji-indexed CSV. Rows are ordered by how MANY words landed on
    the picture, biggest first -- the overloaded buckets are the finding, so they
    belong at the top rather than buried in codepoint order.

    Returns (path, distinct emoji)."""
    if path is None:
        path = EMOJI_WORDS
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    grouped = group_by_emoji(rows)
    order = sorted(grouped, key=lambda e: (-len(grouped[e]), e))
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["emoji", "label", "word_count", "fit3_count",
                         "fit2_count", "fit1_count", "words"])
        for emoji in order:
            words = grouped[emoji]
            counts = collections.Counter(fit for word, fit in words)
            writer.writerow([emoji, labels.get(emoji.replace("️", ""), ""),
                             len(words), counts[3], counts[2], counts[1],
                             ";".join(word for word, fit in words)])
    return path, len(grouped)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=WORDS_EMOJI,
                        help="word-indexed CSV to roll up")
    parser.add_argument("--output", default=EMOJI_WORDS,
                        help="emoji-indexed CSV to write")
    parser.add_argument("--min-fit", type=int, default=1,
                        help="drop words below this fit (default 1, i.e. keep all)")
    args = parser.parse_args()
    rows = load_word_rows(args.input, args.min_fit)
    path, pictures = write_emoji_index(rows, load_labels(), args.output)
    counts = collections.Counter(fit for word, emoji, fit in rows)
    print("%d words over %d emoji (fit 3: %d, fit 2: %d, fit 1: %d)"
          % (len(rows), pictures, counts[3], counts[2], counts[1]))
    if pictures:
        print("%.1f words per emoji on average" % (len(rows) / float(pictures)))
    print("wrote %s" % path)


if __name__ == "__main__":
    main()
