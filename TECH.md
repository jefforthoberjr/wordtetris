
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