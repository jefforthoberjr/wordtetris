# WHO I AM
I am a software developer with over 15 years experience. Most of my experience on the backend and infrastructure. I have less experience in frontend technologies.
I am the driver of requirements.

# WHO YOU ARE
You are my coding assistant. At times I will be asking for your opinion on tech decisions. At times you will be focused on coding. At times we are just focused on updating the status of the spec.

# PROJECT
We will be building a video game, piece by piece. 

My notes on the game's rules is in the spec folder.

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

When I ask you to refactor a feature, in a major way, ask me to confirm if I want to stash a copy of the old way in the code. I will be rare that I want to completely abandon an old feature.

Thus, our overall coding style will end up with many objects or logic rules in the game will be swappable/configurable. The code will be a lot like a 'rules engine' format.

Functions we extract as configurable features should have the word "rule" in it.

We want it so when I swap out the rules later, I only have to update one place. So little extra wrapper functions are ok for this.

Try to keep functions with rule selection in them toward the top of the .py files.

## WE BOTH EDIT THE CODE
Sometimes, between your edits of code, I will manually make some small changes. For example, add a line of commenting. Since you may not see these edits in your context, please re-read files that have an updated timestamp newer than when you touched them last.

When refactoring, try to preserve my manual comments in the code (unless of course, the relevant code is deleted).

## SPEC
This will contain many text decriptions on the rules of the game. This serves as documentation, and a TODO list.
This will contain many single line sentences about the logic / rules / physics of the game. It will also contain descriptions about how the UI works, and how files and data are handled.

This is not verbose; I want this as very concise sentences, to make it very scannable to the human eye.
For example:
"Blocks can do X"
"Player can move X to Y"
"Button will do Y"

As we add to the game, we should also update this spec to reflect changes. ASK ME each time you think we should update the spec. Sometimes I will ask you to add a new line to the spec.

In front of each line in the spec will be a status.
"[TODO]" or "[DONE]".

## NOTES
The notes folder is just for my personal notes. Do not refer to this at all. This is just brainstormed ideas that may contradict what is being developed.