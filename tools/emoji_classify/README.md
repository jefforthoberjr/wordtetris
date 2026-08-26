# Emoji classification run

Assigns one emoji + a fit score (1-3) to every word in
`src/models/dictionaries/spellingDictionary20k-nocompound.txt` (21,874 words) so
the idea belt has far more picture prompts than the ~110-row hand-written
`default_ideas.csv`. Same swarm shape as `tools/dict_classify` (the plant-tier
pass): 750-word chunks, ~8 workers in parallel, 30 chunks.

## Why agentic at all

Checked first, so nobody re-derives it: there is no published word->emoji
dictionary at this scale. The open resources are emoji->keyword inventories --
Unicode CLDR's annotations (repackaged as emojibase), EmojiNet, EmoTag. Joined
against this dictionary CLDR covers **2,384 of 21,874 words (11%)**; the other
89% has to be classified. Those 2,384 are kept anyway, as a scoring key: the
workers classify them too, and `assemble.py` diffs the two.

## The fit score is the point

The emoji is easy; the honest question is whether the picture actually names the
word. `3` DEPICTS (shark -> shark), `2` SUGGESTS (imagine -> thought balloon),
`1` ARBITRARY (nonetheless -> shrug). The belt should stock fit-3 for beginners;
without the column the file would silently ask a child to spell NONETHELESS from
a shrug. See `emoji_rubric.md`.

## Run it

    ./tools/emoji_classify_session.sh          # lean session, effort low

    # or with an opening instruction, like the plant run:
    ./tools/emoji_classify_session.sh "probe the emoji-classifier on chunk_00"

### 1. Build the inputs (once per dictionary change)

    python tools/emoji_classify/seed_cldr.py
    # 1949 emoji annotations, 1410 plain in roster, 2384/21874 dictionary words seeded

    python tools/emoji_classify/chunk.py
    # 21874 words -> 30 chunks of <=750 in tools/emoji_classify/run/in

    python tools/emoji_classify/chunk.py --size 500     # smaller batches
    python tools/emoji_classify/chunk.py --words path/to/other_list.txt

### 2. Probe one chunk before spending the window

Ask for a single worker and read its output before fanning out:

    Read tools/emoji_classify/run/in/chunk_00 (750 lowercase words, one per
    line). Assign every word one emoji and a fit score per your rubric. Write
    the CSV (`word,emoji,fit`, no header) to
    tools/emoji_classify/run/out/chunk_00.csv. The output must have exactly
    750 rows, in the same order as the input.

Then `python tools/emoji_classify/assemble.py` and look at the fit-3 rows. One
chunk costs ~18.5k subagent tokens and ~80 seconds.

### 3. Fan out the rest

~8 `emoji-classifier` subagents at a time, one chunk each, same prompt with the
number changed. Pause between waves. Four waves covers chunks 01-29 (the last one
is short -- 124 words, so say 124 rows in its prompt, not 750).

### 4. Assemble, repair, repeat

    python tools/emoji_classify/assemble.py
    #   chunk_04: 750/750 rows, 9 need a re-run
    # 30 chunks, 21682 words classified, 192 queued for repair
    # fit 3: 2825   fit 2: 9563   fit 1: 9294
    # wrote .../out/words_emoji.csv
    # wrote .../out/emoji_words.csv (1114 distinct emoji)
    # wrote .../out/cldr_compare.csv (1301/2369 agree with CLDR, 54.9%)

Strays are a handful per chunk, so gather them into ONE batch rather than
re-running 28 chunks:

    cat tools/emoji_classify/run/repair/* | sort -u > tools/emoji_classify/run/repair_all.txt
    wc -l tools/emoji_classify/run/repair_all.txt

Hand that file to one worker, telling it WHY the words bounced (that is what
stops it repeating the same pick), and have it write to
`run/out/extra/repair_NN.csv`. Anything under `run/out/extra/` is read as loose
rows that fill whatever their own chunk is still missing -- no chunk file gets
edited, and re-running a repair is idempotent. Then assemble again:

    python tools/emoji_classify/assemble.py
    # 30 chunks, 21874 words classified, 0 queued for repair

Repeat until `run/repair/` is empty. The real run took two repair passes: 192
strays (ZWJ profession/family sequences), then 21 (Unicode symbols like the ankh
☥ and the hammer-and-sickle ☭, which are not emoji and render as flat text).

## Results of the 2026-08-26 run

21,874 words, 30 chunks, ~570k subagent tokens, ~25 minutes of wall clock in four
waves of 8. Fit distribution: **2,839 fit-3 / 9,621 fit-2 / 9,414 fit-1** (13%
depictable), landing on **1,116 distinct emoji**. Agreement with CLDR on the 2,384
overlapping words: **54.9%** -- read as a floor, since most disagreements are the
worker being better for this purpose (`access` 🔓 where CLDR says ♿).

The 2,839 fit-3 words are the belt-ready set: ~26x the 110-row hand-written
`default_ideas.csv`.

## What comes out (`out/`)

- **`words_emoji.csv`** — `word,image,emoji,fit`, alphabetical. The file the game
  reads: every stocking rule starts from a word. `image` is deliberately empty,
  ready for real icon art (thenounproject etc.) per word without a schema change.
- **`emoji_words.csv`** — `emoji,label,word_count,fit3_count,fit2_count,`
  `fit1_count,words`, ordered by how many words landed on that picture. The
  research view, and the answer to "show me every word that got this emoji". The
  word list is ONE `;`-joined column, because the count per emoji is variable
  (1 to 380) and a ragged word1..wordN row would be unreadable. No image column —
  this file is about the emoji; per-word art belongs in the word-indexed file.
  Built by `rollup_by_emoji.py`, which `assemble.py` calls so both routes produce
  the same bytes. Analysis only — the game reads the word-indexed file.
- **`cldr_compare.csv`** — `word,llm_emoji,fit,cldr_emojis,agree` over the CLDR
  words. Agreement is scored loosely (CLDR keys several emoji per word, any of
  them counts), so read it as a floor, not a grade.

## Re-rolling the emoji index by hand

`rollup_by_emoji.py` rebuilds `emoji_words.csv` from any word-indexed file, so a
bigger dictionary pass or an entirely different emoji mapping can be re-rolled
without re-running the swarm:

    python tools/emoji_classify/rollup_by_emoji.py
    # 21874 words over 1116 emoji (fit 3: 2839, fit 2: 9621, fit 1: 9414)
    # 19.6 words per emoji on average
    # wrote tools/emoji_classify/out/emoji_words.csv

    # just the belt-ready words:
    python tools/emoji_classify/rollup_by_emoji.py --min-fit 3
    # 2839 words over 897 emoji -- 3.2 words per emoji on average

    # a different mapping entirely:
    python tools/emoji_classify/rollup_by_emoji.py \
        --input some/other_mapping.csv --output some/other_rollup.csv

It defaults to reading the SHIPPED `src/assets/idea_belt/words_emoji.csv` rather
than the pipeline's copy, so it describes what the game is actually playing with.
The CLDR label column is optional — a missing `data/emojibase_en.json` just leaves
it blank, so a hand-built mapping still rolls up.

### What the roll-up shows

All 21,874 words land on **1,116 emoji — 19.6 words each on average**, but the
distribution is wildly uneven:

| emoji | label | words | of which fit-3 |
|---|---|---|---|
| 🚫 | prohibited | 380 | 6 |
| ✅ | check mark button | 277 | 5 |
| 🗣️ | speaking head | 222 | 7 |
| 🤝 | handshake | 219 | 10 |
| ⚖️ | balance scale | 210 | 11 |

139 emoji carry exactly one word. The big buckets are abstraction sinks — 🚫 is
where `nonrefundable`, `taboo` and `xenophobia` all end up — and they are almost
entirely fit-1/2, which is why the belt filters on fit rather than on the emoji.
Restricted to fit 3, the same data is 2,839 words over 897 emoji: **3.2 words per
picture**, which is the healthy shape.

## Validation the assembler enforces

Rows must line up word-for-word, in order, with the chunk they were dealt -- a
worker that skips or reorders is the classic bulk-run failure and is invisible in
a spot check. The emoji must be a plain single emoji on the CLDR roster: no ZWJ
profession/family sequences, no skin tones, no flags, however reasonable they
look, because the belt draws them as a single glyph. The fit must be 1-3.
Anything failing goes to `run/repair/` and never reaches the CSVs.
