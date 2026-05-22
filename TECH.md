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

Setup for steam distribution
  1. Create a Steamworks developer account ($100 one-time fee)
  2. Create your app in Steamworks
  3. Set up depots for Windows and macOS
  4. Use Steamworks SDK's upload tool to push builds
  5. Configure store page, release