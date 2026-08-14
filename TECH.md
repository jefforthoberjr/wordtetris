
# TECH STACK and DEV OPS
We are using python3.

We are using the "C" version of python (i.e. not Java or .Net)

I am editing in vscode, with minimal plugins

We are using venv and pip to manage libs/dependencies.
Example commands:
`python3.12 -m venv venv`

`source venv/bin/activate`
`pip install -r requirements.txt`
`pipreqs ./src`

We are keeping the set of local build command very simple. We are only doing local development, with minimum distributed components.

`python ./src/main.py`

I am storing everything in a git repo. DO NOT add/commit with git. I am in charge of adding and commiting. I will be committing often.

I have unit tests.
`pytest`
`pytest tests/test_main.py`

Eventually when we do release builds
Produce an .exe for windows, and a .app for mac
Bundling in python interpreter and all its libs
Bundling as .pyc files
using pyinstaller
`pyinstaller --onedir --windowed main.py`


# PYTHON STYLE
Avoid python decorators. No need to the syntax sugar.

Avoid multiple return statements in a function. This will make embedding wrappers more easily during future refactors.

Prefer clear multiline loops over "list comprehension"

Avoid "//" operator, use math.floor instead

Avoid formal polymorphism typing; just use duck typing

Avoid raw pixel math; instead things should be relative to screen size.

# PYGLET STYLE

Note: On a Retina window, window.width reports the physical framebuffer size

## COLOR EMOJI (the idea belt's placeholder art)

pyglet 2.1.14 renders COLOR emoji correctly on macOS -- a plain
`pyglet.text.Label` with `font_name="Apple Color Emoji"` comes back as a full-color
glyph texture, no image files and no extra library needed. Two gotchas:

  * pyglet MULTIPLIES a label's color into the glyph, so an emoji label must be
    drawn at `(255, 255, 255, 255)`. Any other tint drains the color out of it.
  * The font differs per OS, so pass a LIST of names and let pyglet take the first
    that resolves: Apple Color Emoji / Segoe UI Emoji / Noto Color Emoji (see
    `views/idea_belt.EMOJI_FONTS`). A machine with none of them falls back to
    monochrome glyphs rather than crashing.

Emoji glyphs also sit smaller inside their em box than a normal letter does, so a
belt item sizes its emoji off a bigger fraction of the circle than a real image
would use (EMOJI_FRACTION vs ART_FRACTION).

# SOUND / AUDIO

First sound arrived 2026-07-21 (the end-of-game video's soundtrack). Audio on pyglet
has TWO independent layers -- get them straight before touching sound:

1. DECODER: turns a file into raw PCM. Per-format, per-platform. `pyglet.media.load(path)`
   auto-picks one; you can force one (e.g. `decoder=FFmpegDecoder()`).
2. OUTPUT DRIVER: pushes PCM to the speakers. Chosen from `pyglet.options['audio']`.
   On macOS the ONLY real output is **OpenAL** (the list is xaudio2/directsound/
   openal/pulse/silent -- first two are Windows, pulse is Linux). There is no
   CoreAudio *output* driver.

## Hard-won lessons (macOS, pyglet 2.1.14, Homebrew FFmpeg 8.1)
- **Do NOT decode audio with pyglet's FFmpeg decoder here.** Against FFmpeg 8.x
  (libavcodec 62) pyglet's FFmpeg *audio* path reads the format header correctly
  (2ch/16-bit/44100) but returns ZERO audio bytes. The OpenAL player reads 0 bytes as
  instant end-of-stream and dispatches `on_eos` ~10 ms in -- which tore the whole end
  video down after one black frame. (FFmpeg *video* decode is fine; only audio is
  broken.) This was misdiagnosed twice -- see ONGOING_BUGS.md "End video does not
  play". Root cause is the decoder, NOT the OpenAL implementation.
- **openal-soft was a red herring for this bug** but is still worth having. Both the
  deprecated Apple `OpenAL.framework` AND Homebrew `openal-soft` play correctly once
  the audio is actually decoded (via a native decoder). We installed openal-soft
  during the investigation; it is optional. pyglet hardcodes `framework='OpenAL'` on
  mac, so it uses Apple's framework unless you redirect `ctypes.util.find_library`.
- **Native decoders work great.** `wave` (WAV, cross-platform) and macOS `coreaudio`
  (.wav/.m4a/.mp4/.aac...) both stream full PCM with no premature eos. Windows has
  `wmf`, Linux has `gstreamer`. These are the ones to use.

## Rules of thumb
- **Sound effects / music:** ship **WAV** and let pyglet's native `wave` decoder play
  it. Cross-platform, no FFmpeg, no external dep. (Compressed formats -- mp3/ogg/m4a
  -- route through ffmpeg or a platform decoder; WAV is the safe universal path.)
- **The end video (`EndVideoOverlay`)** is a special case: video and audio are decoded
  SEPARATELY from the same .mp4 -- video via forced FFmpeg (audio track dropped),
  audio via the platform-native decoder (`pyglet.media.load` with no decoder ->
  CoreAudio on mac). Two Players started together stay in sync over the clip. Audio is
  best-effort (a failure just plays silent).
  - DISLIKED / TWO-PLAYER WORKAROUND: driving one clip with two Players is ugly --
    it risks A/V drift, doubles the teardown/lifecycle bookkeeping, and only works
    because the halves happen to stay in step over a short clip. It exists solely
    because pyglet's FFmpeg *audio* decode is broken on FFmpeg 8.x (see above).
    **TODO (future): replace with a SINGLE-player video+audio solution.** Candidates:
    a pyglet/FFmpeg version combo whose FFmpeg audio decode actually returns bytes;
    a different single-decoder media path that does both streams; or swapping the
    video-playback library entirely. Collapse the two Players back into one once a
    single decoder plays both tracks.

## Steam / self-contained packaging (future)
- OpenAL output: bundle **openal-soft** (small, redistributable dylib/dll/so) rather
  than trusting the OS -- Apple's framework is deprecated and could vanish. Standard
  for shipped pyglet games.
- Audio decoding: staying on **WAV + native decoders** means NO ffmpeg dependency for
  sound at all -- good for a self-contained build.
- FFmpeg is currently required only for VIDEO (the end clip), and it is NOT
  self-contained yet -- it relies on the Homebrew FFmpeg shared libs in
  /opt/homebrew/lib. For a Steam build we must either bundle the FFmpeg dylibs (large)
  or drop to a lighter video path. Revisit when we do release builds (see pyinstaller
  note above).

# CLIPPING END VIDEOS (FFmpeg)

End clips (`EndVideoOverlay`, `game_screen.end_video`) live in `src/assets/video/`.

Use the tool -- do NOT hand-run ffmpeg each time:

```
python tools/clip_end_video.py --probe ~/Desktop/source.mp4   # analyze a new source
python tools/clip_end_video.py mario_flag_ending              # clip a registered source
```

`tools/clip_end_video.py` probes the source UP FRONT, then clips it into
`src/assets/video/<name>.mp4` and re-encodes to a **standardized, decode-friendly
output format** (there is no need to preserve the source's resolution/fps/profile):
720p, 30fps, Main profile, no B-frames, yuv420p, faststart -- the traits of the
known-good `goldeneye.mp4`. Anything heavier is auto-normalized; the tool prints why.

To add a new source: `--probe` it, add an entry to the `SOURCES` dict (in/out points
+ any per-source special case), then run it by name. Per-source special-casing lives
in that dict because filmed/ripped sources differ and a one-size command does not
work (see the smear lesson below). Then point a mode at the result:
`game_screen.end_video: <name>.mp4` in its game_modes yaml.

The equivalent raw ffmpeg (output seeking + normalize), for reference:

```
ffmpeg -y -i ~/Desktop/source.mp4 -ss 6 -to 20 \
  -vf "scale=-2:720,fps=30" \
  -c:v libx264 -profile:v main -level 3.1 -bf 0 -refs 1 -preset medium -crf 20 -pix_fmt yuv420p \
  -c:a aac -movflags +faststart \
  src/assets/video/my_clip.mp4
```

Hard-won lessons:
- **Match the source to a profile pyglet can decode in real time -- this is the big
  one.** `EndVideoOverlay` decodes via pyglet's threaded FFmpeg decoder and blits each
  frame stretched fullscreen. A heavy source (a 1080p60, High-profile, B-frame clip)
  overruns the decoder and it displays torn / smeared / "broken pixel" frames -- even
  though the source plays perfectly in QuickTime. Downscale + simplify to match the
  known-good `goldeneye.mp4`: **720p, 30fps, `-profile:v main`, `-bf 0` (no B-frames),
  `yuv420p`.** `scale=-2:720` keeps aspect with an even width; `fps=30` halves 60fps
  sources. If a clip smears, re-encode SMALLER/SIMPLER before anything else.
- **Use OUTPUT seeking, not input seeking, for the clip start.** `-ss` BEFORE `-i`
  (input seeking) is fast but jumps to the nearest keyframe and can emit a
  smeared/broken FIRST frame (a P/B frame decoded without its reference). `-ss` after
  `-i` decodes from the beginning, so the first output frame is always a clean
  I-frame. Slower, but the clips are short so it doesn't matter.
- **Do NOT force keyframes to "fix" a smear.** `-force_key_frames "expr:gte(t,0)"`
  is true for *every* frame (t is always >= 0), turning the whole clip into I-frames
  and bloating the file ~25x (a 14s clip went 2 MB -> 56 MB). Output seeking already
  gives a clean start; a smear mid-clip is the decode-load issue above, not keyframes.
- `-pix_fmt yuv420p` keeps it broadly decodable; `-movflags +faststart` moves the
  moov atom to the front for smooth playback start; `-crf 20` is a good quality knob
  (lower = better/bigger).
- Diagnose by comparing a bad clip against the known-good `goldeneye.mp4`:
  `ffprobe -v error -select_streams v:0 -show_entries stream=profile,width,height,r_frame_rate,has_b_frames,pix_fmt -of default=noprint_wrappers=1 clip.mp4`
  Verify the first frame is a keyframe (should print `I`):
  `ffprobe -v error -select_streams v:0 -show_entries frame=pict_type -read_intervals "%+#1" -of csv=p=0 clip.mp4`

# RUN GAME

python src/main.py

# RUN SESSION REPLAY
For debbugging purposes

python src/replay.py -0 --speed 3.0
python src/replay.py -1 --speed 3.0

python src/replay.py -0 --export progress.mp4
python src/replay.py -0 --export progress.mp4 --fps 10 --speed 3.0 --scale 0.5
#NOTE: playback during export mode whips through much faster

python replay.py sessions/<id>.log [--speed 2.0] [--invisible]
Example:
python src/replay.py sessions/2026-06-21T14-28-44_46ae.log 


# DIAGNOSING CLICK / COORDINATE BUGS FROM THE LOG

The session .log records not just raw input but what the game DID with it, so a
misbehaving click is usually readable straight from the log (grep by code) with
no need to re-run/replay. Codes are defined in src/log_codes.py.

grep '\[20003\]' sessions/<id>.log   raw mouse click: pixel (x,y) AND the board
                                      cell it resolved to (cell=). If clicks stop
                                      landing on the cell under the cursor, that's
                                      a coordinate-scale desync.
grep '\[20004\]' sessions/<id>.log   right-click gram-manipulate OUTCOME: cell,
                                      old->new gram, reason (applied / off_board /
                                      fossilized / empty / rule_noop). A no-op
                                      double shows its reason here.
grep '\[20005\]' sessions/<id>.log   omniswap OUTCOME: picked / swapped / canceled
                                      / invalid_target / word_piece / ignored,
                                      with the cell and swap source.
grep -E '\[0001[01]\]' sessions/<id>.log   window focus (00010) + resize (00011),
                                      each with physical size + pixel ratio. The
                                      focus timeline (a resignKey/focus_lost with
                                      no matching becomeKey/focus_gained) is the
                                      lead for the alt-tab freeze -- see below.
grep '\[00012\]' sessions/<id>.log   liveness heartbeat (~every 2s). Heartbeats
                                      that STOP with no END footer = the loop
                                      froze; heartbeats that CONTINUE past the
                                      last input = only event delivery died.

Known limit: timed modes (omniswap_vs_timer) drift slightly on replay because we
log wall-clock timestamps, not the per-frame dt sequence -- so prefer reading the
outcome codes above over re-playing to reproduce an exact click.

NOTE: the "clicks landing on the wrong cell = Retina scale desync after alt-tab"
theory is DISPROVEN for the freeze seen so far (scale stayed constant, clicks
were correct but stopped being delivered). Open bugs and their evidence live in
ONGOING_BUGS.md -- read it before chasing a focus/coordinate click bug.


# CONFIG REFERENCE

src/assets/config.yaml is the single edit point for playtest tuning, kept
scannable: a flat wall of keys, the commented-out toggle alternatives, and a
terse one-line label per knob. The FULL prose for every knob lives in
CONFIG_REFERENCE.md, keyed by the same dotted name (e.g. game_screen.mode) --
search that file for a key to get the details.

When you add or change a rule: put the short label in config.yaml and the
explanation in CONFIG_REFERENCE.md under a matching heading. Do NOT grow
multi-paragraph comments back into config.yaml.


# SCRIPTS FOR JUDGING WORD IDEATION

Two offline scripts in gram_corpus/ (not game runtime):
- ideation_analysis.py — for any gram, dumps the 20k-dict words by position ranked by real Google frequency (the grounding tool).
- ideation_grader.py — generates cleaned3 end-to-end; rerun anytime, tweak thresholds at the top. The rubric is documented in its docstring.

# CLI TOOL FOR SPELLING HINTS SPELLCHECKER
Exercising the in-game spelling hints feature

python3 src/spell_check_cli.py CENTRO
python3 src/spell_check_cli.py CENTRO --top 30
python3 src/spell_check_cli.py REVISIONIST


# REGENERATE THE INFLECTION-EXPANDED DICTIONARY

Offline build (not game runtime). Expands the 21.9k headword list
(spellingDictionary20k-nocompound.txt) into inflected + British forms.

cd src/models/dictionaries
python3 build_expanded_dictionary.py

Inputs are vendored in src/models/dictionaries/sources/ (12dicts-2+2+3lem.txt is
the authority; British spellings are already inline in it). Outputs, written
alongside the current dictionary:
- expandedAllowedWords.txt   flat "all words" set (~55k)
- headwordInflections.json   map headword -> [extra forms] (keys ∪ values == flat)
- headwordInflections.txt    same map, human-readable

Invariant: every allowed word derives from a kept headword (families are built
only for the 21.9k headwords). Rerun anytime; it is deterministic.


# BULK DICTIONARY CLASSIFICATION (e.g. plant-bonus tiers)

Offline pass that tags each of the ~24k headwords with a topic-bonus tier
(1/2/3), for a themed scoring bonus. Runs inside a dedicated lean Claude Code
session on the Max subscription ($0 marginal cost), NOT the pay-per-token API.

Launch (always from the repo root; the flag scopes config to this session only):

  ./tools/dict_classify_session.sh
  ./tools/dict_classify_session.sh "run the plant-classifier probe on 100/250/500/750"

What the launcher does and why:
- Runs `claude --effort low` — drives per-step thinking to its floor, the main
  lever for fitting a full run inside one 5-hour window. Per-session only, so
  normal coding sessions are unaffected (Claude Code binds .claude/settings.json
  to the git root, so a subdir settings.json can't scope this — the CLI flag can).
- Launches from the repo root so the session sees the dictionaries, the
  plant-classifier subagent, and CLAUDE.md/AGENTS.md.

Pieces:
- .claude/agents/plant-classifier.md — the worker subagent (Sonnet, Read+Write
  only, effort low, rubric baked into its system prompt).
- tools/dict_classify/ — task folder for the rubric and output CSVs.

Runbook: fan out ~8 plant-classifier subagents in parallel, each classifying a
<=750-word slice to its own chunk CSV (batches >750 words have stalled). Then
`cat` the chunk CSVs together and let build_expanded_dictionary.py's headword
lineage propagate each tier across inflections to cover the full ~60k word set.
Sonnet is the worker model; keep the main session model irrelevant to output.

## Wave-based run pattern (validated on the 21.9k headword set)

Proven end-to-end on the full spellingDictionary20k-nocompound.txt (~4 min of
agent walltime, 351 tier-3 / 329 tier-2 / 21194 tier-1, zero integrity errors):

1. Probe first. Run 100/250/500/750-word batches before committing to a size.
   Confirms the classifier holds row integrity as batches grow and finds the
   real stall point. 750 completes cleanly in ~55s; that's the working ceiling.
2. Chunk deterministically with `split`, into a temp subfolder the workers own:
     mkdir -p run/in run/out
     split -l 750 -d -a 2 <source> run/in/chunk_
   750 words -> 30 chunks (last one partial). One input file per subagent.
3. Fan out in WAVES of 8 (Claude Code caps concurrency ~10; 8 leaves headroom).
   Launch all 8 agents of a wave in a single message so they run concurrently;
   wait for the whole wave to report before launching the next. 30 chunks = 4
   waves (8/8/8/6). Each wave takes ~55-60s regardless of chunk contents.
4. Each subagent writes ONLY to its own run/out/chunk_NN.csv. No shared output
   file -> no write contention, and any single chunk can be re-run in isolation.
5. Verify from the CSVs, NOT the agents' spoken summaries. The subagents'
   self-reported tier counts are routinely wrong (miscounts, and a trailing
   newline makes them say "751" for a 750-word chunk) -- but the written files
   are exact. After each wave check: input line count == CSV data-row count, and
   every tier value is in {1,2,3}. Trust the file, distrust the prose.
6. Combine in chunk order (`grep ',' out/chunk_* >> plant_tiers.csv`), then do
   the one final integrity gate that matters: `diff` the CSV's word column
   against the source dictionary -- it must match byte-for-byte, in order. That
   proves no drops, dupes, reordering, or drift across all 30 chunks at once.

Notes on subagent prompting / chunking (the levers that make this work):
- <=750 words per chunk is a hard practical ceiling. Sonnet chokes on ~2000
  ("the thinking cliff" -- big batches blow the ~64k output-token cap and drift).
  Smaller chunks also help each response land inside the 5-min cache TTL window.
- Walltime is linear and batch-size-independent: ~1 min / 150 words (~7.5 min
  per 1k single-threaded). Parallelism is the only real speedup; ~10 concurrent
  turns a ~2-hour serial pass into ~15 min.
- The win of subagents is context ISOLATION, not caching. Each Read of a chunk
  and each Write of a CSV would otherwise bloat the main transcript; subagents
  keep all of that out of the main session, which only sees "wrote N rows".
  (Don't count on shared prefix caching between simultaneously-fired workers --
  they all write the cache at once and all miss it.)
- Keep the worker prompt MECHANICAL: rubric baked into the agent's system
  prompt, Read+Write only, effort low, thinking off. The per-invocation prompt
  is just the input path + output path + "classify every word, write the CSV".
- Classification is loose at the top tier -- expect a few false tier-3s
  (anaconda, angora, dwarf slipped through). If tier-3 precision matters, the
  tier-3 list is small enough (~350) to eyeball in one manual pass.