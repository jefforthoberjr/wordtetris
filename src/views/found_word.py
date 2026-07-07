from collections import namedtuple

# One dictionary word located on the board: the ordered cells it occupies
# (`path`), the exact gram/segment taken from each cell (`segments`, which
# records a wild cell's chosen run), and the resolved `word`. Shared by the
# word-finding, selection and mode code, so it lives here rather than on
# GameScreen (which imports it back into its own namespace for gs.FoundWord).
FoundWord = namedtuple("FoundWord", ["path", "segments", "word"])
