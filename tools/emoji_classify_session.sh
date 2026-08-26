#!/usr/bin/env bash
# emoji_classify_session.sh — launch a lean Claude Code session for the bulk
# word->emoji pass over the 20k spelling dictionary.
#
# Same shape as dict_classify_session.sh (see that file for why a dedicated
# launcher exists): --effort low is the biggest lever for keeping a 30-chunk run
# inside one 5-hour Max window, and it applies to THIS session only.
#
# Usage:
#   ./tools/emoji_classify_session.sh
#   ./tools/emoji_classify_session.sh "run the emoji probe on chunk_00"
#
# In the session, workers run on the `emoji-classifier` subagent (Sonnet,
# Read+Write only, effort low). 750 words per chunk, ~8 in parallel, 30 chunks.
#
# The whole pass, start to finish:
#   python tools/emoji_classify/seed_cldr.py    # CLDR scoring key (once)
#   python tools/emoji_classify/chunk.py        # 21874 words -> 30 chunks
#   ...fan out ~8 emoji-classifier subagents per wave, one chunk each...
#   python tools/emoji_classify/assemble.py     # validate + write both CSVs
#   cat tools/emoji_classify/run/repair/* | sort -u > tools/emoji_classify/run/repair_all.txt
#   ...one worker on repair_all.txt -> run/out/extra/repair_NN.csv, assemble again...
#
# Full walkthrough with expected output: tools/emoji_classify/README.md
cd "$(dirname "$0")/.." || exit 1   # always launch from repo root
exec claude --effort low "$@"
