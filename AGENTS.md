# WHO I AM
I am a software developer with over 15 years experience. Most of my experience on the backend and infrastructure. I have less experience in frontend technologies.
I am the driver of requirements.

# WHO YOU ARE
You are my coding assistant. At times I will be asking for your opinion on tech decisions. At times you will be focused on coding.

# THE PROJECT - THE GAME
We will be building a video game, piece by piece. 

In this game, players are spelling out words. The player manipulate 'pieces' and 'cells'. Pieces are comprised of one or more cells. Cells contain word chunks with one or more letters in each cell (aka "grams"). 

The game_screen.py transitions between "phases" (e.g. MOVING and SELECTING). The game_screen has some major ways in which its gameplay is configured (see config.yaml), including "grid" square vs. hex grid (game_screen.grid), and different game "modes" (game_screen.mode). The different game modes defines about roughly half of the logic, UI and player's controls that get used at runtime. These are the biggest aspects of the game to clarify/specify when adding new rules to the game.


# AUDIENCES
I am experimenting with two audience types, and some rules exist to serve one and
not the other.

The first is ADULT WORD EXPERTS. Much of my early philosophy assumed this
audience: never reveal whether a word can still be formed, let the player
discover it. The size of the player's dictionary is a braggable metagame element,
so I also want to prevent players from lazily farming their dictionary.

The second is YOUNG PLAYERS, still learning vocabulary and still learning to
spell. A young player who cannot immediately think of a word would get
discouraged and stop playing the game. For the younger players, it is more of a
"lead a horse to water": word idea -> here's how it's spelled -> find the letters
-> wow look how many you collected this round -> type them (and trick them into
practicing spelling in the process). The idea belt features are focused on this
audience, which is why the belt is allowed to break the no-word-availability-hints
rule that still holds everywhere else.

# CONFIG FILES
YOU CAN EDIT config.yaml
config.yaml represents a master list of all the possible rules we've developed

YOU CANNOT EDIT the subconfiguration yaml files in game_modes/ dir
These files represent the hand-picked variations I am experimenting with.

After you've created a new rule/config (and have just added it to config.yaml), you can output a suggestion for which subconfig files the new rule should be added to, and display some copy/paste text, otherwise it's an important exercise for me as the human to do the copy and paste. This is a forced moment for me to reflect and learn about the newly created option, and forces me to re-audit how a newly added feature may/maynot be used in the various modes.

As we experiment with adding more rules, I will playtest, commenting in/out different rule combinations at the root config.yaml (for things I believe should apply to all game modes).

To keep config.yaml scannable, its knobs carry only a terse one-line label; the full explanation for each lives in CONFIG_REFERENCE.md (keyed by the same dotted name). When you add or change a rule, put the short label in config.yaml and the prose in CONFIG_REFERENCE.md -- do NOT grow multi-paragraph comments back into config.yaml. See TECH.md.


# OUTPUT LANGUAGE
All output — chat responses, code, comments, commit messages, and docs — must be
in English. Do not substitute non-English words even when they're synonyms
(e.g. no "никогда" for "never"). Before finishing a response, glance back over it
and fix any stray non-English token. If you ever notice you emitted one, correct
the line in plain English rather than leaving it.

# WORKING RULES
I will instruct you on high level game rules and low level opinions on coding style. 

## CODING
While you may know some of the final goals/output of the game, I am purposefully building it slowly, piece by piece, for the benfit of my eduation and understanding of the code. There final product may have a lot of code, but I only want to generate code in chunks of about 200 lines at a time. If I ask you to do a task that you predict will take more than 200 lines of code, PAUSE, take a moment to ask me how to break it down into smaller tasks, or maybe we agree to proceed. PAUSE after the completion of each task, to give me time to review the code and/or playtest. I will often have you refactor the code. The project will have many files. If a file gets longer than 2000 lines of code, ALERT me about it, and we'll take some time to refactor it into separate smaller files.

We will likely be importing and using many libraries. Any time you want to import a new library, PAUSE, and let's engage in discussion to justify the libary (and to give time for me to quickly read up on some examples of it). I will not approve importing a library until I understand it.

Refer to document TECH.md for other opinions on coding style.

Do not automatically update a library/dependency version unless you ask first.

## REFACTOR CODE - RULES ENGINE
When we first implement a feature, it will be usualy be very basic (e.g. low animation, low physics, low logic). 
Then, as we refactor code, to add more complexity to the feature, I was to preserve the more primative version of the feature in the code (in case I want to uncomment it / restore it in the future). 

When refactoring code, keep the old version of the feature in the code, but disabled (or in an uncalled function).

When I ask you to refactor a feature, in a major way, ask me to confirm if I want to stash existing logic, as a commented out rule in config.yaml, a copy of the old way in the code. I will be rare that I want to completely abandon an old feature.

Thus, our overall coding style will end up with many objects or logic rules in the game will be swappable/configurable. The code will be a lot like a 'rules engine' format.

The resulting core code is thus heavily feature flagged.

Functions we extract as configurable features should have the word "rule" in it.

We want it so when I swap out the rules later, I only have to update one place. So little extra wrapper functions are ok for this.

Try to keep functions with rule selection in them toward the top of the .py files.

Anytime we add something new to config.yaml, also update the core code logic to use it.

# SESSIONS AND REPLAY FEATURE
We capture logs as sessions, which I can use later to replay a previous session.
The session uses/shares the logic of the main game.
Anytime you make a change or feature add to the main game, make sure there is sufficient logging etc. to see the new feature in the replay.
I'll often refer to this as "see my most recent play session" for you to look in the sessions dir and read the logs.

## WE BOTH EDIT THE CODE
Sometimes, between your edits of code, I will manually make some small changes. For example, add a line of commenting. Since you may not see these edits in your context, please re-read files that have an updated timestamp newer than when you touched them last.

When refactoring, try to preserve my manual comments in the code (unless of course, the relevant code is deleted).

## NOTES
The notes folder is just for my personal notes. Do not refer to this at all. This is just brainstormed ideas that may contradict what is being developed.