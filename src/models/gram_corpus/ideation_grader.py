"""OFFLINE first-pass grader for gram 'ideation' (not game runtime).

Produces cleaned3 with a heuristic first pass for every gram, applying the
rubric calibrated against Jeff's hand-labeled gold rows:

  HARDCODES
    - single letter            -> strong = y           (booster: single letter)
    - double letter (xx)       -> strong = n           (inhibitor: double letter)
    - vowel diphthong (2 vowels/glide) -> strong = n    (inhibitor: vowel diphthong)

  LEARNED RULES (multi-letter, non-hardcoded)
    - broad abstract morpheme suffix (-tion/-ment/...) -> strong = n  (huge but diffuse)
    - inverted-U: overly productive prefix (too much space) -> strong = m
    - tight rhyme family at the suffix                 -> strong = y  (booster: rime family)
    - concrete/distinct-root prefix cluster            -> strong = y  (booster: distinct roots)
    - thin candidate set                               -> strong = m / n

Gold rows (those already graded in cleaned2) are PRESERVED verbatim; only the
new ideation_boosters column is generated for them.

Word candidates gated on the 20k dictionary (Method C); "common" = Google
unigram rank <= COMMON_RANK (Method B, drunk-high-schooler vocab).
"""
import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DICTS = HERE.parents[0] / "dictionaries"
FREQ_CSV = DICTS / "unigram_freq.csv"   # vendored from wordmountain/v1/unigram_freq.csv
DICT_TXT = DICTS / "spellingDictionary20k-nocompound.txt"
SRC = HERE / "jpo_allGramsGreaterThan47InFreq_cleaned2.csv"
OUT = HERE / "jpo_allGramsGreaterThan47InFreq_cleaned3.csv"

COMMON_RANK = 12000
VOWELS = set("aeiou")
BROAD_SUFFIX = {  # abstract morphemes: high count but low concrete ideation
    "tion", "sion", " tion", "ment", "ing", "ion", "ous", "ity", "able", "ible",
    "ence", "ance", "ive", "ial", "ual", "tial", "ient", "ness", "less", "ful",
    "ory", "ary", "ize", "ise", "ism", "ist", "ical",
}


def is_double(g):
    return len(g) == 2 and g[0] == g[1]


def is_diphthong(g):
    if len(g) != 2:
        return False
    if g[0] in VOWELS and g[1] in VOWELS:
        return True
    return g in {"ay", "ey", "oy", "aw", "ew", "ow"}


def load_freq_rank():
    rank = {}
    with open(FREQ_CSV, newline="") as f:
        for i, row in enumerate(csv.reader(f), start=1):
            if row and row[0].strip():
                w = row[0].strip().lower()
                rank.setdefault(w, i)
    return rank


def load_dict():
    with open(DICT_TXT) as f:
        return {ln.strip().lower() for ln in f if ln.strip()}


def buckets(gram, words, rank):
    """common words by position; each entry (rank, word)."""
    g = gram
    P, M, S = [], [], []
    for w in words:
        if g not in w or w == g:
            continue
        r = rank.get(w)
        if r is None or r > COMMON_RANK:
            continue
        if w.startswith(g):
            P.append((r, w))
        if w.endswith(g):
            S.append((r, w))
        i = w.find(g, 1)
        if 0 < i < len(w) - len(g):
            M.append((r, w))
    for L in (P, M, S):
        L.sort()
    return P, M, S


def rhyme_count(gram, S):
    """tight rime members. A real rime is vowel-initial (vowel+coda), the
    members are short and genuinely common (rank<=8000)."""
    if gram[0] not in VOWELS:
        return 0
    n = 0
    for r, w in S:
        if len(w) <= 7 and (len(w) - len(gram)) <= 3:
            n += 1
    return n


def ideated_words(P, M, S, k=3):
    pool = sorted(set(P + M + S), key=lambda rw: (len(rw[1]), rw[0]))
    return [w for _, w in pool[:k]]


def grade(gram, words, rank):
    g = gram.lower()
    L = len(g)
    inhib, boost = [], []
    P, M, S = buckets(g, words, rank)
    p_n, m_n, s_n = len(P), len(M), len(S)
    own = g in words and L >= 2
    rh = rhyme_count(g, S)

    # ---- hardcodes --------------------------------------------------
    if L == 1:
        return dict(strong="y", pre="y", mid="y", suf="y",
                    inhib="", boost="single letter",
                    ideated="", note_conf="hardcode")
    if is_double(g):
        strong = "n"; inhib.append("double letter")
    elif is_diphthong(g):
        strong = "n"; inhib.append("vowel diphthong")
    else:
        strong = None

    # ---- position columns ------------------------------------------
    pre = "y" if p_n >= 4 else ("m" if p_n >= 1 else "n")
    suf = "y" if s_n >= 4 else ("m" if s_n >= 1 else "n")
    if p_n <= 1 and s_n <= 1:
        mid = "y" if m_n >= 4 else ("m" if m_n >= 1 else "n")
    else:
        mid = "n"

    short_concrete = sum(1 for r, w in P if len(w) <= 5)
    broad = (g in BROAD_SUFFIX) or (s_n >= 30 and rh < 4)
    overly_productive = p_n >= 15

    # ---- strong (only if not hardcoded n) --------------------------
    if strong is None:
        if broad:
            strong = "n"; inhib.append("broad morpheme")
        elif overly_productive:
            strong = "m"; inhib.append("overly productive prefix")
        elif rh >= 4 and s_n >= 25:
            # strong rime core but diluted by a heavy abstract morpheme (-ate/-age/-ure)
            strong = "m"; boost.append(f"rime family (-{g})")
            inhib.append("rime diluted by morpheme")
        elif rh >= 4:
            strong = "y"; boost.append(f"rime family (-{g})")
        elif p_n >= 4 and short_concrete >= 3:
            strong = "y"; boost.append("distinct roots")
        elif p_n >= 3 or s_n >= 4 or m_n >= 5 or rh == 3:
            strong = "m"
        elif (p_n + s_n + m_n) >= 2:
            strong = "m"
        else:
            strong = "n"
        # own-word damps a y unless a rime or concrete prefix truly carries it
        if own and strong == "y" and rh < 4 and short_concrete < 3:
            strong = "m"
    else:
        # hardcoded-n grams still get boosters/notes for context
        if rh >= 4:
            boost.append(f"rime family (-{g})")

    if own:
        inhib.append("its own word")

    return dict(strong=strong, pre=pre, mid=mid, suf=suf,
                inhib="; ".join(inhib), boost="; ".join(boost),
                ideated=", ".join(ideated_words(P, M, S)),
                note_conf="")


def main():
    rank = load_freq_rank()
    words = load_dict()
    rows = list(csv.reader(open(SRC, newline="")))
    header = rows[0]
    # extend header with the new boosters column (appended at end)
    out_header = header + ["ideation_boosters"]
    out_rows = [out_header]
    gold = 0
    for row in rows[1:]:
        row = row + [""] * (len(header) - len(row))  # pad short rows
        gram, freq = row[0], row[1]
        if row[2].strip():           # already graded -> preserve, add booster
            g = grade(gram, words, rank)
            out_rows.append(row + [g["boost"]])
            gold += 1
        else:
            g = grade(gram, words, rank)
            out_rows.append([
                gram, freq, g["strong"], g["pre"], g["mid"], g["suf"],
                g["inhib"], g["ideated"], "", g["boost"],
            ])
    with open(OUT, "w", newline="") as f:
        csv.writer(f).writerows(out_rows)
    print(f"wrote {OUT.name}: {len(out_rows)-1} grams ({gold} gold preserved)")


def calibrate():
    """Print predicted vs actual for the gold rows to check agreement."""
    rank = load_freq_rank()
    words = load_dict()
    rows = list(csv.reader(open(SRC, newline="")))
    hits = tot = 0
    print(f"{'gram':6} pred S/P/M/Su   gold S/P/M/Su   strong?")
    for row in rows[1:]:
        if len(row) < 7 or not row[2].strip():
            continue
        g = grade(row[0], words, rank)
        pred = f"{g['strong']}/{g['pre']}/{g['mid']}/{g['suf']}"
        gold = f"{row[2]}/{row[3]}/{row[4]}/{row[5]}"
        ok = "OK" if g["strong"] == row[2] else "XX"
        hits += g["strong"] == row[2]; tot += 1
        print(f"{row[0]:6} {pred:13} {gold:13} {ok}  inhib=[{g['inhib']}] boost=[{g['boost']}]")
    print(f"\nstrong-col agreement: {hits}/{tot}")


if __name__ == "__main__":
    if "--calibrate" in sys.argv:
        calibrate()
    else:
        main()
