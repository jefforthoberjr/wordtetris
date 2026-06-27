
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

python src/replay.py -0
python src/replay.py -1 --speed 3.0

python replay.py sessions/<id>.log [--speed 2.0] [--invisible]
Example:
python src/replay.py sessions/2026-06-21T14-28-44_46ae.log 


# SCRIPTS FOR JUDGING WORD IDEATION

Two offline scripts in gram_corpus/ (not game runtime):
- ideation_analysis.py — for any gram, dumps the 20k-dict words by position ranked by real Google frequency (the grounding tool).
- ideation_grader.py — generates cleaned3 end-to-end; rerun anytime, tweak thresholds at the top. The rubric is documented in its docstring.