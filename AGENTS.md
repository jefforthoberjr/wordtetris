# WHO I AM
I am a software developer with over 15 years experience. Most of my experience on the backend and infrastructure. I have less experience in frontend technologies.
I am the driver of requirements.

# WHO YOU ARE
You are my coding assistant. At times I will be asking for your opinion on tech decisions. At times you will be focused on coding.

# THE PROJECT - THE GAME
We will be building a video game, piece by piece. 

In this game, players are spelling out words. The player manipulate 'pieces' and 'cells'. Pieces are comprised of one or more cells. Cells contain word chunks with one or more letters in each cell (aka "grams"). 

The game_screen.py transitions between "phases" (e.g. MOVING and SELECTING). The game_screen has some major ways in which its gameplay is configured (see config.yaml), including "grid" square vs. hex grid (game_screen.grid), and different game "modes" (game_screen.mode). The different game modes defines about roughly half of the logic, UI and player's controls that get used at runtime. These are the biggest aspects of the game to clarify/specify when adding new rules to the game.

As we experiment with adding more rules, I playtest, commenting in/out different rule combinations in config.yaml.


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
Then, as we refactor code, to add more complexity to the feature, I was to preserver the more primative version of the feature in the code (in case I want to uncomment it / restore it in the future). 

When refactoring code, keep the old version of the feature in the code, but disabled (or in an uncalled function).

When I ask you to refactor a feature, in a major way, ask me to confirm if I want to stash existing logic, as a commented out rule in config.yaml, a copy of the old way in the code. I will be rare that I want to completely abandon an old feature.

Thus, our overall coding style will end up with many objects or logic rules in the game will be swappable/configurable. The code will be a lot like a 'rules engine' format.

Functions we extract as configurable features should have the word "rule" in it.

We want it so when I swap out the rules later, I only have to update one place. So little extra wrapper functions are ok for this.

Try to keep functions with rule selection in them toward the top of the .py files.

# SESSIONS AND REPLAY FEATURE
We capture logs as sessions, which I can use later to replay a previous session.
The session uses/shares the logic of the main game.
Anytime you make a change or feature add to the main game, make sure there is sufficient logging etc. to see the new feature in the replay.

## WE BOTH EDIT THE CODE
Sometimes, between your edits of code, I will manually make some small changes. For example, add a line of commenting. Since you may not see these edits in your context, please re-read files that have an updated timestamp newer than when you touched them last.

When refactoring, try to preserve my manual comments in the code (unless of course, the relevant code is deleted).

## NOTES
The notes folder is just for my personal notes. Do not refer to this at all. This is just brainstormed ideas that may contradict what is being developed.