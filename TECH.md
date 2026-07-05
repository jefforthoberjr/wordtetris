
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
                                      each with physical size + pixel ratio. A
                                      scale change here (e.g. after alt-tab / Space
                                      switch on Retina) right before bad clicks is
                                      the fingerprint of the focus coordinate desync.

Known limit: timed modes (omniswap_vs_timer) drift slightly on replay because we
log wall-clock timestamps, not the per-frame dt sequence -- so prefer reading the
outcome codes above over re-playing to reproduce an exact click.


# SCRIPTS FOR JUDGING WORD IDEATION

Two offline scripts in gram_corpus/ (not game runtime):
- ideation_analysis.py — for any gram, dumps the 20k-dict words by position ranked by real Google frequency (the grounding tool).
- ideation_grader.py — generates cleaned3 end-to-end; rerun anytime, tweak thresholds at the top. The rubric is documented in its docstring.

# CLI TOOL FOR SPELLING HINTS SPELLCHECKER
Exercising the in-game spelling hints feature
venv/bin/python src/spell_check_cli.py CENTRO
venv/bin/python src/spell_check_cli.py CENTRO --top 30

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