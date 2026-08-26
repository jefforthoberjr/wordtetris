# Word -> Emoji Classification Rubric

You assign ONE emoji to each single English word, plus a FIT score saying how
honest that pairing is. The emoji becomes picture-prompt art on a word game's
"idea belt": a young player sees the picture and tries to spell the word.

## The emoji

- Exactly ONE emoji per word.
- Use a PLAIN, WIDELY-SUPPORTED emoji: no skin-tone modifiers, no ZWJ
  combinations (family/profession sequences), no country flags, no keycaps.
  If in doubt, pick the older, simpler emoji -- it renders everywhere.
- Prefer the emoji a person would draw for the word, not a clever rebus.
  BOOK -> a book, not an open scroll. SHARK -> the shark, not a fish.
- Different words MAY share an emoji. There are ~1,900 usable emoji and far more
  words; do not distort a choice just to keep it unique.
- Never leave the emoji blank. Every word gets one, however loose -- the FIT
  score is where you record that it is loose.

**The ZWJ trap.** The single most common mistake in this task is reaching for a
person-plus-object sequence for a job or a family: accountant, adviser, abbot,
adopt. Those are ZWJ sequences and they are REJECTED by the assembler. Use the
OBJECT or the plain face instead -- accountant 💼, adviser 🏫, abbot ⛪,
adopt 👪, accompany 🚶. Likewise never emit bare ASCII punctuation (`&`, `@`) --
it is not an emoji; ampersand is 🔣.

## The fit score

- **3 -- DEPICTS.** The emoji shows the thing the word means. A player seeing the
  picture could plausibly say the word. SHARK 🦈, LADDER 🪜, RAIN 🌧️, ANGRY 😠,
  SLEEP 😴, PIZZA 🍕. Concrete nouns, common animals, plain actions and plain
  emotions land here.
- **2 -- SUGGESTS.** A defensible metaphor or a strong association, but nobody
  would name the word from the picture alone. IMAGINE 💭, SERIAL 🔢, FRAGILE 🥚,
  URGENT ⏰, WEALTH 💰, LOGIC 🧩.
- **1 -- ARBITRARY.** Filler. The word has no picture -- function words, abstract
  connectives, grammatical machinery. NONETHELESS 🤷, THUS ➡️, ADJUNCT 📎,
  OF 🔗, WHEREAS ⚖️.

Score honestly and default DOWN. A 3 you had to argue for is a 2. The game only
puts fit-3 words in front of beginners, so inflating scores is the one failure
that actually breaks the feature -- an over-scored word means a child staring at
a shrug emoji trying to spell NONETHELESS.

## Discipline (critical)

- This is a MECHANICAL task. Do NOT deliberate at length, do NOT reason
  word-by-word in prose, do NOT explain your choices.
- Classify EXACTLY the words given, in the same order. Never skip, merge, drop,
  invent, or reorder. The output row count MUST equal the input word count.
- Output format: CSV, one row per word, `word,emoji,fit` -- no header, no
  surrounding prose, no code fences. The emoji column holds the emoji character
  itself, not a name or a shortcode.
