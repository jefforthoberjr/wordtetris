# IDEATION STRENGTH — design notes, terminology, and algorithm history

> **Purpose of this document.** This is a living design log for the "ideation
> strength" scoring of grams. It is meant to be picked up by a future AI (or by
> Jeff) after long gaps. The work is inherently **subjective** and can only be
> validated by **playtesting + Jeff's hand-grading**, so the workflow is
> iterative: refine the algorithm → regenerate → blind-compare against Jeff's
> gold → diagnose → refine again. This file records *what we tried, why, what
> broke, and how we corrected it*, so nobody has to re-derive the reasoning.
>
> Read `AGENTS.md` and `TECH.md` first for the project's working rules (small
> chunks, pause for review, preserve old versions, "rule" naming, etc.).

---

## 1. The problem

The game (`wordtetris`) shows the player **grams** (letter chunks, 1–4 letters)
in cells; the player spells words from them. When the board first forms we want
to avoid crowding it with **"unexciting" grams** — grams that do *not* quickly
spark a word in the player's mind. A board full of unexciting grams overwhelms /
frustrates a player in the critical first seconds.

**Ideation strength** = a subjective measure of how quickly and easily an
*average* player thinks of ~3 real words containing a gram, within ~1 second.

- `CONF` → CONFIDENCE / CONFERENCE / CONFER instantly → **strong**.
- `UME` → ~2 s to reach FUME, then dry → **weak**.

### The core finding (why this is hard)

**Frequency is NOT a reliable proxy for ideation.** 
The gram distribution csv files contain `freq` columns, which was originally used
as a first pass to select gram candidates for the game. This was an objective first-pass, to get started with playtesting and subjective refinement.

`freq` is *type frequency* — how many dictionary words contain the gram
(with de-duping so a long gram is not double-counted as its sub-grams). High
`freq` grams (`ti`, `er`, `ate`) are often **unexciting** because they are
diffuse glue; low `freq` grams (`oke`) can be **strong** because they anchor a
tight rhyme family. So the whole effort is about finding signals *other than*
frequency. Jeff derived the original `freq` weights over ~a year; **we are not
auditing those** — they are an input.

---

## 2. Files and data

### CSVs (in `src/models/gram_corpus/`)

| file | role |
|---|---|
| `jpo_allGramsGreaterThan47InFreq_cleaned.csv` | **Original** input. Two columns: `gram,freq`. 613 grams, freq ≥ 47. |
| `jpo_allGramsGreaterThan47InFreq_cleaned2.csv` | **Jeff's gold file.** Same rows + the grading columns. Jeff hand-populates rows here; populated rows are "gold" (ground truth). The header here defines the schema. |
| `jpo_allGramsGreaterThan47InFreq_cleaned3.csv` | **AI-generated output.** Full grading for all 613 grams. Gold rows from `cleaned2` are copied verbatim; the rest are machine-graded. This is what gets blind-compared against Jeff's attempts. |
| `jpo_allGramsGreaterThan47InFreq_old.csv` | older snapshot, ignore. |

**Naming convention:** `cleaned2` = human gold, `cleaned3` = machine output. If
we spin a new algorithm wave we may write `cleaned4`, etc. Always write machine
output to a **new** number so Jeff's gold file is never clobbered.

## 3. Repeatability and Bias
As a solo developer, Jeff is using his singluar subjective analysis to bootstrap these algorithms.
At the moment, we're considering Jeff's input like a training set.
However, in the future, Jeff will recruit other people to give thier own person scoring, which may change or challenge the analysis. At the moment, we'll consider Jeff's input as "gold" for the source of truth on subjectiveness, otherwise, the gold could change.
DO NOT overly HARDCODE Jeff's opinions. 
Jeff is attempting to derive an average person's ideation. There may end up being different types of people, with different ideation profiles.

### Schema (current header of `cleaned2`, 9 cols; `cleaned3` appends a 10th)

```
gram,
freq,
strong_ideation,                                  # y / m / n   (overall)
prefix_ideation,                                  # y / m / n   (gut: mind autocompletes the START)
midfix_ideation,                                  # y / m / n   (gut: gram feels BURIED mid-word)
suffix_ideation,                                  # y / m / n   (gut: mind autocompletes the END)
notes_ideation_inhibitors,                        # free text: why ideation is suppressed
words_we_ideated,                                 # example words that DID contain the gram
words_that_ideated_that_are_spell_wrong_actually, # words the mind reached by SOUND but that don't actually contain the gram
ideation_boosters                                 # (cleaned3 only) free text: why ideation is helped
```

Values are **`y` = yes, `n` = no, `m` = maybe / a little**.

### Dictionaries / frequency data

- **20k dictionary (Method-C gate):**
  `src/models/dictionaries/spellingDictionary20k-nocompound.txt`
  ~21.8k words, **alphabetical** (NOT frequency-ordered), no compounds. It is
  itself a curated common-words list. A candidate word only "counts" if it is in
  here.
- **Frequency ranking (Method-B vocab):**
  `src/models/dictionaries/unigram_freq.csv` — the Google Web Trillion-Word
  unigram list: `word,count`, 333,333 rows, sorted by descending count. We use
  the **rank** (line number) as a commonness proxy. **Vendored** into the repo
  (4.9 MB) from `wordmountain/v1/unigram_freq.csv` so the tooling is
  self-contained — no external dependency. The Python scripts read it via a
  path relative to `src/models/dictionaries/`.

---

## 3. Terminology / glossary

- **Gram** — a letter chunk (1–4 letters) shown in a cell.
- **Ideation strength** — speed/ease of recalling ~3 words from a gram in ~1 s.
- **`strong_ideation`** — the overall y/m/n. Judged **first and holistically**:
  Jeff ideates 3–4 words and decides yes/no on *strength*; only afterward does
  he introspect on *which positions* his mind autocompleted. It is **NOT** a
  combined/union credit across positions — it's a gut overall call. Specifically, 
  this is a mind time driven score. A player could spend several seconds to pause
  and thing of words, however, a true strong spark of ideation must occur within the
  first second of thinking. Instinctual. Auto-complete, more than churning. In a game
  with a timer and time pressure, it's important to bin instinctual vs. churn as separate
  gameplay experiences.
- **prefix / midfix / suffix ideation** — the gut *direction* the mind
  autocompletes, **independent of strength**. A gram can have `strong=n` but
  `prefix=y` (e.g. `det` → DETERMINE). "Midfix" is about the gram *feeling
  buried* inside words, not strict letter position (see `ume` below). A gram
  can instincually feel like a midfix, but then upon more time to churn on it, a
  player may realize that it's actually more of a suffix. But we're not measuring
  churn-time analysis, we're measuring instinct-time analysis.
- **Rime / rhyme family** — a **vowel-initial coda** that yields many short
  rhyming words: `-ull` (full/pull/dull), `-ack` (back/pack/track), `-oke`
  (joke/poke/smoke). The single strongest `y` signal.
- **Broad morpheme** — an abstract, productive suffix (`-tion`, `-ment`,
  `-tial`, `-ient`). High word count but **low concrete ideation** → suppresses
  strength. `tial` has 11 common words yet Jeff scored it `n`.
- **Overly-productive prefix / inverted-U** — Jeff's insight: a morpheme that is
  *too* popular gives "**too much space to ideate**" → *weaker*, not stronger.
  So strength is an inverted-U in productivity: a moderately-focused prefix
  (`conf`) is strong; a hyper-productive one (`pre/pro/com/un`) is `m`.
- **Diluted rime** — a rhyme core swamped by an abstract morpheme. `ate` =
  concrete DATE/GATE/LATE **+** 67 abstract `-ate` words (create/private) → the
  morpheme dilutes the rime → `m`. Contrast `amp` (CAMP/LAMP, little baggage) →
  `y`. Detected as "rime present but total suffix-count ≫ rime-core size."
- **Its own word / dark ending** — if the gram is itself a standalone word
  (`van`, `gal`, `spa`), the player just *reads the word* instead of building
  one → dampens strength (unless a rime or vivid prefix carries it anyway).
- **Sound-vs-spelling misfire** — words the mind reaches by **sound** that don't
  actually contain the gram's letters: `tial` → SPECIAL/RACIAL (spelled -cial),
  `dist` → DESTROY, `exc` → EXECUTIVE. Captured in column 9. Jeff noted his
  ideation is partly phonetic and spelling variations "get in the way." Not
  computable from frequency data — needs a phonetic angle or human ear.
- **Distinct roots** — a prefix is strong when it launches words of *distinct
  meaning*, not inflections of one stem: `conf` → CONFER/CONFIDE/CONFIRM/
  CONFLICT/CONFUSE (`y`) vs `det` → only detail/detect/determine (`n`). Hard to
  compute; approximated by candidate count + judgment.
- **Vivid launch** — a simple consonant(+consonant)+vowel opening that fires
  concrete everyday words instantly: `ba`→BALL/BAT/BAD, `tr`→TREE/TRAIN/TRUCK.
- **Gold row** — a row Jeff has hand-graded in `cleaned2`. Ground truth;
  machine code must **preserve gold verbatim** and never override it.
- **Method A / B / C** — the three approaches we weighed (see §4).

---

## 4. The three methods (and which we use)

- **Method A — pure frequency formula.** Rejected. Jeff discovered through
  playtesting that frequency doesn't predict ideation, and the repo had no
  per-word frequency data anyway. A count-only formula mis-rates rhyme families
  and glue.
- **Method B — LLM-simulated recall.** The AI plays "average player": for a gram
  it emits the first words that leap to mind. Jeff's constraint: prompt the AI
  to **"think like a drunk high-schooler"** so vocabulary stays common, not
  erudite.
- **Method C — dictionary-gated.** A recalled word only counts if it is in the
  20k dictionary (`spellingDictionary20k-nocompound.txt`). This curbs
  obscure-word bias from both human and AI.

**We use a mix of B + C:** generate candidate words gated by the 20k dict
(C), ranked by real Google frequency, and apply common-vocab judgment (B) on
top. The frequency tool (`ideation_analysis.py`) grounds the judgment so it
isn't pure vibes.

---

## 5. Python tooling

All three live in `src/models/gram_corpus/`. They are **offline analysis
scripts, NOT game runtime.** Run with `python3 <file>.py` from that directory.

### `ideation_analysis.py` — the grounding tool
For any gram, lists the 20k-dict words containing it, **split by position**
(prefix / midfix / suffix), each ranked by Google frequency.
```
python3 ideation_analysis.py conf ume ull
```
Key constant: `COMMON_RANK` (currently 12000) — a word at/under this Google rank
is treated as "leaps to mind." Use this tool to *see the evidence* before
grading anything by hand.

### `ideation_grader.py` — heuristic first-pass → writes `cleaned3`
Generates a full grading for all 613 grams. **Preserves gold rows** from
`cleaned2` verbatim (rows where `strong_ideation` is already filled); grades the
rest. Has a `--calibrate` mode that prints predicted-vs-gold for every gold row
and an agreement score:
```
python3 ideation_grader.py --calibrate     # check against gold
python3 ideation_grader.py                 # (re)write cleaned3
```
**Decision logic (in priority order)** for a non-gold gram:
1. **Hardcodes:** single letter → `y`; double letter (`ss`,`ll`,…) → `n`
   (inhibitor "double letter"); vowel diphthong (2 vowels, or glide
   ay/ey/oy/aw/ew/ow) → `n` (inhibitor "vowel diphthong").
2. **Positions:** `prefix=y` if ≥4 common prefix words (`m` if ≥1); same for
   `suffix`; `midfix` only considered when both edges are weak (≤1 word each).
3. **Strong:** broad morpheme (curated set, or suffix-count ≥30 with no rime) →
   `n`; overly-productive prefix (≥15 common prefix words) → `m`; rime core but
   diluted (rime ≥4 **and** suffix-count ≥25) → `m`; clean rime (≥4 members) →
   `y`; concrete prefix (≥4 prefix words **and** ≥3 of them ≤5 letters) → `y`;
   else thin → `m`/`n`. Own-word damps a `y` to `m` unless a rime/concrete
   prefix carries it.
4. Emits `words_we_ideated` (3 shortest common words) and auto
   `ideation_boosters` / `notes_ideation_inhibitors`.

**`rhyme_count()` rule (important):** a real rime must be **vowel-initial**
(this is how we exclude consonant codas like `rce`/`nct` that Jeff rates `n`),
short words, short onset. This single rule fixed a lot.

### `apply_strong_overrides.py` — AI judgment pass on `strong` only
Holds a hand-authored `OV = {gram: "y"/"m"/"n"}` dict produced by the AI reading
the candidate-word worksheet and judging each gram (Method B). Run **after**
`ideation_grader.py`; it overrides only the `strong_ideation` column, only on
**non-gold** rows, leaving positions/notes/gold untouched.
```
python3 ideation_grader.py && python3 apply_strong_overrides.py
```
This exists because the strong/prefix boundary is **not** separable by counts
(see Wave 5) — semantic richness lives in the LLM's lexical sense, not the data.

---

## 6. The waves (chronological history of what we tried)

Each wave = a round of build → calibrate → Jeff-feedback → correct.

### Wave 0 — framing & data hunt
- Established that `freq` = de-duped type frequency, and that the 20k dict is
  alphabetical (so rank ≠ frequency) and the repo had **no** word-frequency
  data. Located the Google `unigram_freq.csv` in the sibling `wordmountain`
  project to serve as the commonness signal.

### Wave 1 — rubric extraction from the first 25 gold rows (freq 47–49)
Jeff hand-graded the 25 lowest-freq grams as examples. Extracted the
**non-obvious** rules a naive count would miss:
1. **Midfix is usually `n`** when the gram works as prefix or suffix — the mind
   doesn't think "buried." (`ull` has interior words like FULLY but midfix=`n`.)
2. **Strength is suppressed by abstractness** even at high counts (`tial`).
3. **Prefix `y` vs `m` = distinct concrete roots**, not inflection count
   (`conf` y vs `exc` m vs `det` n).
4. Jeff's "common vocab" is a touch wider than rank 9000 (he counts BLINK,
   BLISS) → nudged cutoff toward 12k.

### Wave 2 — built `ideation_analysis.py`
Per-gram candidate lister, dict-gated, freq-ranked. Confirmed e.g. `fume` sits
at rank ~34k (matches `ume` = weak).

### Wave 3 — built `ideation_grader.py`, first calibrations
- v1: **12/25** strong agreement. All *clear-mechanism* grams correct (rhyme
  families, broad morphemes, clear prefixes); all misses were the fuzzy `m`/`n`
  middle.
- Corrections: (a) rime must be **vowel-initial** + members genuinely common →
  fixed `rce`/`nct`/`ith`; (b) prefix→`y` needs short concrete words → separated
  `spa`/`kn` from `det`/`dist`; (c) **dilution rule** for `ate`/`amp`. → **14/25**.
- Generated `cleaned3` (distribution y=202, m=324, n=87).

### Wave 4 — Jeff enriches the schema + hardcodes
Jeff added: hardcodes (single→`y`, double→`n`, diphthong→`n`); the
`words_we_ideated` and `words_that_ideated_that_are_spell_wrong_actually`
columns; the **inverted-U** insight ("too-popular morpheme = too much space →
weaker"); and asked for an `ideation_boosters` column + the `ate`/`amp` cutoff.
Updated `ume` to `suffix=m` (kept `midfix=y` gut-feel). Folded all into the
grader and regenerated.

### Wave 5 — blind comparison exposes the real wall
Jeff added 6 new gold rows (`orn,mag,inv,rav,ped,vin`). **Strong agreement 1/6.**
Systematic bias: the grader **under-calls strong on prefix grams** — Jeff says
`y` for `mag/inv/rav/ped` (and earlier `conf`) where the heuristic hedged to
`m`. Tested the obvious fix (loosen prefix→`y`): **no aggregate improvement,
15/31 → 15/31** — the errors merely shift (`conf`/`mag` fixed, `dist`/`abo`
broken). **Conclusion:** the prefix y/m/n boundary is *not separable by
frequency counts at all* — it keys on semantic richness the data can't see.
Crucially, when the AI **judged** the 8 disputed grams itself, it matched Jeff
**5/5 on the `y`s** (vs the rule's 0/5). So the lever is *judgment*, not
threshold-tuning.

### Wave 6 — judgment pass (`apply_strong_overrides.py`)
Jeff chose option (b): AI re-judges the `strong` column for the ~318 non-gold
ambiguous grams. Built `apply_strong_overrides.py`. Judgment policy applied:
- **CV bigrams & vivid clusters → `y`** (literal 1-s test: `ba`→BALL/BAT/BAD).
- **Rescued rhyme families** the dilution rule wrongly demoted → `y`: `ip, ine,
  ast, ish, ass, ach, ace, ain, nk, ox`.
- **Glue / abstract morphemes → `n`:** `er, al, ic` (vowel-led glue), `-ify/-ize/
  -ism/-ial`, and launchless grams (`os, uct, erp, rov`).
- **Productive Latinate prefixes held at `m`:** `con, pre, pro, com, per, ex`.
- Result distribution **y=275, m=225, n=113.**
- Fixed a staleness bug: `cleaned3` had been generated before the 6 new gold
  rows existed, so we **regenerate then re-apply** (`grader` then `overrides`).

---

## 7. Calibration scoreboard (strong column vs gold)

| wave | rule | gold set | agreement | note |
|---|---|---|---|---|
| 3 | grader v1 | 25 | 12/25 | clear mechanisms 100%, fuzzy middle missed |
| 3 | grader refined | 25 | 14/25 | vowel-initial rime + dilution |
| 5 | grader | 31 | 15/31 | new gold rows all missed (1/6) |
| 5 | loosened prefix | 31 | 15/31 | errors just shift — counts can't separate |
| 5 | **AI judgment** on 8 disputed | 8 | ~6/8, **5/5 on the y's** | judgment > heuristic |
| 6 | judgment pass applied | — | (awaiting next blind compare) | distribution y275/m225/n113 |

The recurring lesson: the **clear mechanisms** (hardcodes, vowel-initial rime
families, broad morphemes) are reliably machine-gradable; the **prefix /
borderline middle** is irreducibly subjective and is best done by LLM judgment
or Jeff's hand.

---

## 8. Known open problems / next levers (for whoever picks this up)

1. **CV-bigram taste is unvalidated.** Wave 6 calls all consonant+vowel grams
   (`ba/ca/ra/…`) `y` on the literal "3 vivid words leap" test, but there is
   **zero gold** for these. If Jeff's gut is "CV bigrams are too diffuse → `m`,"
   flip them in `apply_strong_overrides.py` (one-line per gram) and rerun. **Get
   gold rows for a sample of CV bigrams first.**
2. **Positions were not re-judged in Wave 6.** `prefix/midfix/suffix` are still
   the grader's output, so on rescued rime rows (`ip`,`ain`,…) the `suffix`
   column may disagree with the new `strong=y`. A judgment pass on positions is
   the next natural step.
3. **Sound-vs-spelling misfires (column 9) are unfilled.** Needs a phonetic
   representation (e.g. the `phonicsDictionary20k` / `ISLEdict` files in
   `wordmountain`, or a grapheme→phoneme step) to detect SPECIAL-from-`tial`.
4. **Semantic richness / imageability is not computable** from current data.
   Options: vendor an imageability/concreteness lexicon (e.g. Brysbaert
   concreteness norms), or accept per-gram LLM judgment as the source of truth
   for the prefix middle.
5. **Distinct-roots detection is approximate** (count-based). A morphological
   stemmer (there is stemming output in `wordmountain/v6`) could make
   `conf`-vs-`exc` separable.
6. ~~The frequency file is an external dependency (`wordmountain`).~~ **Done** —
   `unigram_freq.csv` is now vendored into `src/models/dictionaries/`. The other
   `wordmountain` resources named in items 3 and 5 (`phonicsDictionary20k`,
   `ISLEdict`, the `v6` stemming output) are **not** vendored yet — they are
   large (~6.8 MB + ~13 MB) and only needed if/when we tackle column-9 phonetics
   or distinct-roots stemming. Copy them in at that point.

---

## 9. How to continue (quick start for a future AI)

```bash
cd src/models/gram_corpus

# 1. See the evidence for any grams you're unsure about
python3 ideation_analysis.py conf exc dist ba tr

# 2. Regenerate the machine grading (preserves Jeff's gold rows)
python3 ideation_grader.py
python3 apply_strong_overrides.py     # if iterating on strong judgments

# 3. Check agreement against gold
python3 ideation_grader.py --calibrate
```

**Workflow contract:**
- Never write over `cleaned2` (Jeff's gold). Write machine output to `cleaned3`
  (or a new number for a new wave).
- Always **preserve gold rows verbatim**; gold is ground truth.
- When Jeff adds gold rows, **regenerate `cleaned3` first** (so the grader picks
  up the new gold) **then** re-apply any overrides.
- Treat blank cells in Jeff's gold as `n` when comparing (he sometimes leaves
  `n` blank).
- This is iterative and subjective: expect to alternate with Jeff's playtesting.
  Diagnose *patterns* of disagreement (like Wave 5's "under-calls prefixes"),
  not individual rows. Record each new wave in §6.
