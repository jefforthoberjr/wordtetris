"""OFFLINE analysis helper (not game runtime) for grading gram 'ideation'.

For a gram, list the 20k-dictionary words that contain it, split by position
(prefix / midfix / suffix), each ranked by real-world usage frequency from the
Google Web Trillion-Word unigram list. This grounds the subjective y/n/m
ideation grading in objective word candidates + frequency.

Method C gate: a word only counts if it is in spellingDictionary20k-nocompound.
Method B lens: "common" = Google freq rank <= COMMON_RANK (everyday vocab).
"""
import csv
import sys
from pathlib import Path

DICTS = Path(__file__).resolve().parents[1] / "dictionaries"
FREQ_CSV = DICTS / "unigram_freq.csv"            # word,count  (sorted desc). Vendored from wordmountain/v1.
DICT_TXT = DICTS / "spellingDictionary20k-nocompound.txt"

COMMON_RANK = 9000   # words at/under this Google rank are treated as "leaps to mind"


def load_freq_rank():
    """word -> 1-based frequency rank (lower = more common)."""
    rank = {}
    with open(FREQ_CSV, newline="") as f:
        for i, row in enumerate(csv.reader(f), start=1):
            if not row:
                continue
            w = row[0].strip().lower()
            if w and w not in rank:
                rank[w] = i
    return rank


def load_dict():
    with open(DICT_TXT) as f:
        return {line.strip().lower() for line in f if line.strip()}


def classify(gram, word):
    """Return set of positions {'prefix','midfix','suffix'} the gram occupies."""
    g, positions = gram.lower(), set()
    if word.startswith(g):
        positions.add("prefix")
    if word.endswith(g):
        positions.add("suffix")
    # interior occurrence strictly inside (not touching either edge)
    start = word.find(g, 1)
    if 0 < start < len(word) - len(g):
        positions.add("midfix")
    return positions


def analyze(gram, dict_words, rank, limit=12):
    gram = gram.lower()
    buckets = {"prefix": [], "midfix": [], "suffix": []}
    for w in dict_words:
        if gram in w and w != gram:
            r = rank.get(w)               # None if not in Google list at all
            for pos in classify(gram, w):
                buckets[pos].append((r if r is not None else 10**9, w))
    out = {"gram": gram, "is_word": gram in dict_words}
    for pos, lst in buckets.items():
        lst.sort()
        common = [w for r, w in lst if r <= COMMON_RANK]
        out[pos] = {
            "n_common": len(common),
            "top": [(w, r if r < 10**9 else None) for r, w in lst[:limit]],
        }
    return out


def fmt(a):
    head = f"\n=== {a['gram'].upper()}  (is_own_word={a['is_word']}) ==="
    lines = [head]
    for pos in ("prefix", "midfix", "suffix"):
        d = a[pos]
        words = ", ".join(f"{w}({r})" if r else f"{w}(-)" for w, r in d["top"])
        lines.append(f"  {pos:7s} common<= {COMMON_RANK}: {d['n_common']:2d} | {words}")
    return "\n".join(lines)


if __name__ == "__main__":
    rank = load_freq_rank()
    dict_words = load_dict()
    grams = sys.argv[1:] or ["conf", "ume", "ull", "tial", "van", "ound"]
    for g in grams:
        print(fmt(analyze(g, dict_words, rank)))
