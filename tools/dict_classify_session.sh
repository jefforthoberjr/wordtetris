#!/usr/bin/env bash
# dict_classify_session.sh — launch a lean Claude Code session for bulk
# dictionary word-classification passes (e.g. the plant-bonus tiering).
#
# Why a dedicated launcher:
#   - --effort low drives per-step thinking/token spend to its floor. This is
#     the biggest lever for keeping a big classification run inside one 5-hour
#     Max window. It applies to THIS session only (a CLI arg, not a settings
#     file), so your normal coding sessions are unaffected.
#   - Launching from the repo root (not a subdir) means the session sees the
#     whole repo: the dictionaries under src/models/dictionaries/, the
#     plant-classifier subagent in .claude/agents/, CLAUDE.md/AGENTS.md, and
#     the task folder tools/dict_classify/.
#
# Note: Claude Code binds .claude/settings.json to the git ROOT, so you cannot
# scope config by cd-ing into a subdir. Per-session isolation comes from this
# flag instead.
#
# Usage:
#   ./tools/dict_classify_session.sh
#   ./tools/dict_classify_session.sh "run the plant-classifier probe on 100/250/500/750"
#
# In the session, the workers run on the `plant-classifier` subagent (Sonnet,
# Read+Write only, effort low). Keep each batch <= ~750 words — larger batches
# have stalled. Fan out ~8 in parallel; reconstitute the chunk CSVs afterward.

cd "$(dirname "$0")/.." || exit 1   # always launch from repo root
exec claude --effort low "$@"
