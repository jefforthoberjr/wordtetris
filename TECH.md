
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



