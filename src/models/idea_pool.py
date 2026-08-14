"""The inventory behind the right-pane idea belt (game_screen.idea_belt).

The belt is a picture-prompt conveyor for young players: instead of the score and
the cleared-word list, the pane shows a slow loop of little pictures, and clicking
one types its word into the field. This module owns the WHAT (which pictures, in
which order); views/idea_belt.py owns the motion and the drawing.

Two layers:
  * the DECK -- assets/idea_belt/<idea_belt.deck>.csv, the whole inventory of ideas
    (image, emoji, word1, word2). Loaded once per pool build.
  * the POOL -- the fixed-size, pre-picked, ORDERED ring the belt runs on
    (idea_belt.pool_size items), dealt at game start much like PiecePool deals
    pieces. The belt never re-picks mid-game: both visible columns are sliding
    windows onto this one ring, so an item that leaves the top of the up column
    comes back around later, in the same order, every loop.

Picks route through the Source seam (source.rand) so a replay reproduces the same
belt.
"""
import csv
from pathlib import Path

from config import CONFIG, select_rule
from source import rand
import log_codes as L


class IdeaItem:
    """One item on the belt: a picture plus the single word a click types.

    A deck row with two words expands into two items sharing the same picture
    (unless the dedupe rule is on, which keeps one word per picture)."""

    def __init__(self, word, emoji, image, art):
        # The word a click sends to the typed field. Stored upper-case, matching
        # how the panes hold typed text and how the dictionary is keyed.
        self.word = word.upper()
        self.emoji = emoji
        # Image filename under assets/idea_belt/images/, or "" when the row has
        # none (first-cut deck: every row is emoji-only).
        self.image = image
        # What this item actually DRAWS as, resolved once at build time by the art
        # rule: an image filename, or the emoji. Also the dedupe key -- two items
        # showing the same picture are duplicates whichever art mode is on.
        self.art = art


def deck_path():
    """Resolved path of the active deck file (idea_belt.deck). Kept here rather
    than in config.py because it is the only asset directory a single feature
    owns; falls back to the shipped default when the rule is absent."""
    name = CONFIG.get("rules", {}).get("idea_belt.deck", "default_ideas.csv")
    return Path(__file__).parent.parent / "assets" / "idea_belt" / name


def images_dir():
    """Where image-art files live (image art mode). Sibling of the deck files."""
    return Path(__file__).parent.parent / "assets" / "idea_belt" / "images"


def load_deck(path=None):
    """Read a deck CSV into a list of {image, emoji, word1, word2} dicts.

    Lines starting with '#' are comments (the shipped deck documents its own
    columns that way) and the header row is skipped, so the file stays readable
    as a hand-edited inventory list."""
    if path is None:
        path = deck_path()
    rows = []
    with open(path, encoding="utf-8") as f:
        lines = []
        for line in f:
            if not line.strip().startswith("#"):
                lines.append(line)
        for row in csv.DictReader(lines):
            image = (row.get("image") or "").strip()
            emoji = (row.get("emoji") or "").strip()
            word1 = (row.get("word1") or "").strip()
            word2 = (row.get("word2") or "").strip()
            if emoji or image:
                rows.append({"image": image, "emoji": emoji,
                             "word1": word1, "word2": word2})
    return rows


class IdeaPool:
    """The pre-picked ring of belt items. Build once at game start; the belt view
    then only ever reads item_at(index) and asks for its size."""

    def __init__(self, size=None, deck=None):
        # size: how many items the ring holds (idea_belt.pool_size). deck: the
        # loaded deck rows, injected by tests; None loads the configured file.
        # Read at construction, NOT in the class body -- class-level CONFIG reads
        # freeze at import time, before a game mode is applied.
        rules = CONFIG.get("rules", {})
        if size is None:
            size = rules.get("idea_belt.pool_size", 50)
        self._size = max(1, int(size))
        self._deck = deck if deck is not None else load_deck()
        # How an item draws (and so what counts as a duplicate).
        art_rules = {
            "rule_idea_art_emoji": self._rule_art_emoji,
            "rule_idea_art_image": self._rule_art_image,
        }
        self._art_rule = select_rule("idea_belt.art", art_rules)
        # Whether one picture may appear more than once in the ring.
        dedupe_rules = {
            "rule_idea_dedupe_on": self._rule_dedupe_on,
            "rule_idea_dedupe_off": self._rule_dedupe_off,
        }
        self._dedupe_rule = select_rule("idea_belt.dedupe", dedupe_rules)
        # The order the ring is dealt in.
        order_rules = {
            "rule_idea_order_shuffled": self._rule_order_shuffled,
            "rule_idea_order_deck": self._rule_order_deck,
        }
        self._order_rule = select_rule("idea_belt.order", order_rules)

        self._items = []
        self._build()

    def _build(self):
        candidates = self._candidates()
        candidates = self._dedupe_rule(candidates)
        self._items = self._order_rule(candidates)
        L.log_06009(len(self._items), [item.word for item in self._items])

    def _candidates(self):
        """Every item the deck can offer: one per non-empty word on each row,
        with its art resolved by the art rule. Rows the art rule cannot draw
        (image mode, no image, no emoji either) contribute nothing."""
        items = []
        for row in self._deck:
            art = self._art_rule(row)
            if not art:
                continue
            for key in ("word1", "word2"):
                word = row.get(key) or ""
                if word:
                    items.append(IdeaItem(word, row["emoji"], row["image"], art))
        return items

    # --- art rules (idea_belt.art) ----------------------------------------
    def _rule_art_emoji(self, row):
        """Emoji placeholder art: the deck's emoji column, ignoring images."""
        return row["emoji"]

    def _rule_art_image(self, row):
        """Downloaded picture art: the row's image file, falling back to its
        emoji when the row has none -- so a half-filled images/ folder still
        plays instead of silently thinning the deck."""
        art = row["image"]
        if not art:
            art = row["emoji"]
        return art

    # --- dedupe rules (idea_belt.dedupe) ----------------------------------
    def _rule_dedupe_on(self, candidates):
        """One item per picture: the first word of each distinct art wins, so no
        two belt items ever show the same picture (in either column, since both
        windows read the same ring)."""
        seen = set()
        kept = []
        for item in candidates:
            if item.art not in seen:
                seen.add(item.art)
                kept.append(item)
        return kept

    def _rule_dedupe_off(self, candidates):
        """Every word is its own item, so one picture can appear twice (once per
        word) and, if the deck is smaller than the pool, repeat around the ring."""
        return candidates

    # --- order rules (idea_belt.order) ------------------------------------
    def _rule_order_shuffled(self, candidates):
        """A random ring: shuffle the candidates and take pool_size of them. When
        the deck offers fewer than pool_size, keep drawing reshuffled passes so the
        ring still fills (each pass shuffled separately, so repeats spread out)."""
        ordered = []
        while len(ordered) < self._size and candidates:
            batch = list(candidates)
            rand().shuffle(batch)
            ordered.extend(batch)
        return ordered[:self._size]

    def _rule_order_deck(self, candidates):
        """File order, cycled to fill the ring -- a stable belt for tuning a
        hand-curated deck (e.g. a themed set for a game mode)."""
        ordered = []
        index = 0
        while len(ordered) < self._size and candidates:
            ordered.append(candidates[index % len(candidates)])
            index = index + 1
        return ordered

    # --- read surface ------------------------------------------------------
    def size(self):
        """How many items the ring holds. 0 only if the deck was empty."""
        return len(self._items)

    def item_at(self, index):
        """The item at `index` on the ring, wrapping around in both directions
        (the belt is one connected loop, so a window may run off either end).
        None when the ring is empty."""
        item = None
        if self._items:
            item = self._items[index % len(self._items)]
        return item

    def words(self):
        """The ring's words in order -- for the session log and tests."""
        return [item.word for item in self._items]
