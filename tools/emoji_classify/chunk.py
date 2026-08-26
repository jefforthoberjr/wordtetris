"""Split the 20k spelling dictionary into worker-sized chunks for the emoji pass.

Mirrors the plant-tier run's layout: run/in/chunk_NN holds one lowercase word per
line, and the emoji-classifier subagent writes the matching run/out/chunk_NN.csv.
750 words per chunk is the tuned size -- larger batches have stalled.

    python tools/emoji_classify/chunk.py [--size 750]
"""
import argparse
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
WORDS = os.path.join(ROOT, "src", "models", "dictionaries",
                     "spellingDictionary20k-nocompound.txt")
IN_DIR = os.path.join(HERE, "run", "in")


def load_words(path):
    """The dictionary as a de-duplicated, alphabetical, lowercase list."""
    words = set()
    for line in open(path, encoding="utf-8"):
        word = line.strip().lower()
        if word:
            words.add(word)
    return sorted(words)


def write_chunks(words, size, out_dir):
    """One file per chunk, zero-padded so ls and the worker fan-out agree on
    order. Returns the chunk names written."""
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    count = math.ceil(len(words) / size)
    names = []
    for index in range(count):
        name = "chunk_%02d" % index
        batch = words[index * size:(index + 1) * size]
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
            f.write("\n".join(batch) + "\n")
        names.append(name)
    return names


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=750,
                        help="words per chunk (default 750)")
    parser.add_argument("--words", default=WORDS, help="word list to split")
    args = parser.parse_args()
    words = load_words(args.words)
    names = write_chunks(words, args.size, IN_DIR)
    print("%d words -> %d chunks of <=%d in %s"
          % (len(words), len(names), args.size, IN_DIR))


main()
