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
import math
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
        # Struck off the belt because the player spelled this word on the board
        # (idea_belt.match). The item KEEPS its place on the ring -- clearing it
        # out would slide every later item up and shuffle both columns mid-scroll
        # -- it simply stops drawing, so the picture leaves as a moving gap and
        # the conveyor's rhythm is untouched. Reset per game with the ring.
        self.cleared = False


def deck_path():
    """Resolved path of the active deck file (idea_belt.deck). Kept here rather
    than in config.py because it is the only asset directory a single feature
    owns; falls back to the shipped default when the rule is absent."""
    name = CONFIG.get("rules", {}).get("idea_belt.deck", "default_ideas.csv")
    return Path(__file__).parent.parent / "assets" / "idea_belt" / name


def images_dir():
    """Where image-art files live (image art mode). Sibling of the deck files."""
    return Path(__file__).parent.parent / "assets" / "idea_belt" / "images"


# --- deck formats (idea_belt.deck_format) -----------------------------------
# Two shapes of deck file, both loaded into the SAME internal row
# ({image, emoji, word1, word2}) so nothing downstream knows which one it got.
#
#   PICTURE ROWS -- the original hand-written default_ideas.csv: one row per
#   picture, carrying up to two words that picture can prompt. ~110 rows, curated
#   by eye, every one of them a good prompt.
#
#   WORD ROWS -- the generated words_emoji.csv: one row per WORD, with the emoji
#   the classification pass assigned it and a FIT score for how honestly that
#   picture names the word (see tools/emoji_classify). ~21,900 rows, of which
#   ~2,800 are fit 3. Filtered by idea_belt.min_fit at load, because a fit-1 row
#   (nonetheless -> shrug) is exactly the prompt the belt must never show a child.
def rule_idea_deck_picture_rows(reader, min_fit):
    """One row per picture: image, emoji, word1, word2."""
    rows = []
    for row in reader:
        image = (row.get("image") or "").strip()
        emoji = (row.get("emoji") or "").strip()
        word1 = (row.get("word1") or "").strip()
        word2 = (row.get("word2") or "").strip()
        if emoji or image:
            rows.append({"image": image, "emoji": emoji,
                         "word1": word1, "word2": word2})
    return rows


def rule_idea_deck_word_rows(reader, min_fit):
    """One row per word: word, image, emoji, fit. Rows below `min_fit` are dropped
    HERE rather than filtered later, so every layer above -- the board scans, the
    ring, deck_words() -- sees only prompts that are fair to show. A row with no
    fit column counts as the best fit, which keeps a hand-edited word list usable
    without one."""
    rows = []
    for row in reader:
        word = (row.get("word") or "").strip()
        emoji = (row.get("emoji") or "").strip()
        image = (row.get("image") or "").strip()
        fit = (row.get("fit") or "").strip()
        keep = True
        if fit:
            keep = int(fit) >= min_fit
        if word and (emoji or image) and keep:
            rows.append({"image": image, "emoji": emoji,
                         "word1": word, "word2": ""})
    return rows


def load_deck(path=None):
    """Read the active deck file into a list of {image, emoji, word1, word2}.

    Lines starting with '#' are comments (the hand-written deck documents its own
    columns that way) and the header row is skipped, so a deck stays readable as a
    hand-edited inventory list. Which COLUMNS are expected is the deck_format rule
    -- resolved per call, never cached at import, so a game mode's override is
    honored."""
    if path is None:
        path = deck_path()
    rules = CONFIG.get("rules", {})
    min_fit = int(rules.get("idea_belt.min_fit", 3))
    format_rules = {
        "rule_idea_deck_picture_rows": rule_idea_deck_picture_rows,
        "rule_idea_deck_word_rows": rule_idea_deck_word_rows,
    }
    format_rule = select_rule("idea_belt.deck_format", format_rules)
    with open(path, encoding="utf-8") as f:
        lines = []
        for line in f:
            if not line.strip().startswith("#"):
                lines.append(line)
        rows = format_rule(csv.DictReader(lines), min_fit)
    return rows


# --- stocking categories (idea_belt.stock_category_weight.*) ----------------
# The ring is a MIX of categories rather than one kind of pick: each category is a
# different answer to "which pictures should this belt show", weighted against the
# others, and GameScreen runs one board scan per category with a non-zero weight.
#
# Listed MOST SPECIFIC FIRST. A word can qualify for several categories at once
# (every multigram-using word is also gram-supplied), so the blend hands each word
# to the FIRST category here that claimed it -- otherwise a narrow category's
# quota would be silently paid out of a broad one's matches.
STOCK_CATEGORIES = [
    "spellable_multigram",
    "spellable_by_path",
    "spellable_any_gram",
]
# Not a scan: the leftover slots, dealt at random from the whole deck. Always last
# and always takes the slack when a scanned category cannot fill its quota, so the
# ring is never short and never goes blank.
BLIND_CATEGORY = "blind"


class IdeaPool:
    """The pre-picked ring of belt items. Build once at game start; the belt view
    then only ever reads item_at(index) and asks for its size."""

    def __init__(self, size=None, deck=None, reason="opening", stock=None):
        # size: how many items the ring holds (idea_belt.pool_size). deck: the
        # loaded deck rows, injected by tests; None loads the configured file.
        # reason: why this ring was dealt (opening / new game), for the log only --
        # two rings for one game is the signature of the belt showing a ring the
        # pool has already replaced. stock: {category -> the deck words that
        # category matched on the BOARD}, one entry per stocking category the
        # board scan ran (see STOCK_CATEGORIES); None or empty stocks the whole
        # ring blind, the original behavior. The pool never scans the board
        # itself -- it is handed the answers, so it stays a plain inventory.
        # Read at construction, NOT in the class body -- class-level CONFIG reads
        # freeze at import time, before a game mode is applied.
        rules = CONFIG.get("rules", {})
        if size is None:
            size = rules.get("idea_belt.pool_size", 50)
        self._size = max(1, int(size))
        self._reason = reason
        self._stock = {}
        # Filled in by _blend_stock: category -> ring slots it ended up filling.
        self._stocked = {}
        if stock:
            for category, words in stock.items():
                if words:
                    self._stock[category] = {word.upper() for word in words}
        # How many ring slots each stocking category is worth, as RELATIVE weights
        # (idea_belt.stock_category_weight.*) -- they need not sum to 100, and
        # zeroing one drops that category from the ring entirely. The blind
        # category is one of them, which is what keeps the belt from becoming a
        # solution list: give it weight and that share of the conveyor stays
        # pictures the board cannot make yet.
        self._weights = {}
        for category in STOCK_CATEGORIES + [BLIND_CATEGORY]:
            key = "idea_belt.stock_category_weight." + category
            self._weights[category] = max(0.0, float(rules.get(key, 0)))
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
        # The same answer as a plain flag. The blend needs to know whether one
        # picture may repeat, not just how to thin a list, because it claims art
        # ACROSS categories -- see _blend_stock.
        self._dedupe_on = (rules.get("idea_belt.dedupe", "rule_idea_dedupe_on")
                           == "rule_idea_dedupe_on")
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
        if not self._stock:
            self._items = self._order_rule(self._dedupe_rule(candidates))
        else:
            # NOT deduped here. Dedupe keeps the FIRST word of each picture, and on
            # a word-indexed deck (one row per word, alphabetical) that first word
            # is arbitrary -- deduping up front would throw away the very words the
            # board can make and keep ABACUS because it sorts early. The blend
            # dedupes inside each category instead, once the board has had its say.
            self._items = self._blend_stock(candidates)
        L.log_06009(len(self._items), [item.word for item in self._items],
                    self._reason)

    def _quotas(self):
        """How many ring slots each stocking category gets, from the relative
        weights (idea_belt.stock_category_weight.*). Largest-remainder, so the
        quotas add up to the ring size EXACTLY rather than drifting a slot or two
        off with rounding -- the same approach the opening formation's gram-length
        mix uses. Categories with no weight, and (whatever their weight) ones the
        board scan did not run, are left out entirely.

        All-zero weights, or nothing scanned, returns {} -- the caller reads that
        as a fully blind ring."""
        weights = {}
        for category in STOCK_CATEGORIES:
            if category in self._stock and self._weights[category] > 0:
                weights[category] = self._weights[category]
        if not weights:
            return {}
        weights[BLIND_CATEGORY] = self._weights[BLIND_CATEGORY]
        total = sum(weights.values())
        quotas = {}
        remainders = []
        for category, weight in weights.items():
            exact = self._size * weight / total
            quotas[category] = math.floor(exact)
            remainders.append((exact - math.floor(exact), category))
        # Hand the slots the flooring lost to the biggest fractional parts first.
        remainders.sort(reverse=True)
        short = self._size - sum(quotas.values())
        for index in range(short):
            quotas[remainders[index % len(remainders)][1]] += 1
        return quotas

    def _blend_stock(self, candidates):
        """Deal a ring that MIXES the stocking categories in their configured
        weights (idea_belt.stock_category_weight.*), then INTERLEAVES the scanned
        picks through the blind ones: the ring is a conveyor the player watches a
        few items of at a time, so appending one block to another would give a long
        run of makeable pictures followed by a long run of impossible ones.

        Each category is capped at how many DISTINCT pictures it matched -- never
        cycled to fill its quota. A board that can make three deck words would
        otherwise deal a ring of those same three pictures over and over; the blind
        slots take the slack instead. When the board matched nothing at all, the
        whole ring is blind, so the belt never goes blank.

        Words are claimed most-specific-category-first (see STOCK_CATEGORIES), so a
        word that is both multigram-using and plainly gram-supplied is spent on the
        multigram quota only."""
        quotas = self._quotas()
        claimed = set()
        # Pictures already spent. Only used when dedupe is on, and it spans
        # CATEGORIES: two categories matching two different words of the same
        # picture would otherwise put that picture on the ring twice.
        claimed_art = set()
        per_category = []
        # Slots filled per category, recorded HERE rather than counted back off the
        # finished ring: a blind pick can land on the same word a category matched
        # (small decks repeat), and reading provenance off the words would credit
        # that slot to the category twice over.
        self._stocked = {}
        for category in STOCK_CATEGORIES:
            want = quotas.get(category, 0)
            if want <= 0:
                continue
            words = self._stock.get(category, set())
            available = self._eligible(candidates, claimed, claimed_art, words)
            chosen = self._order_rule(available)[:min(want, len(available))]
            for item in chosen:
                claimed.add(item.word)
                claimed_art.add(item.art)
            per_category.append(chosen)
            self._stocked[category] = len(chosen)
        picked = self._round_robin(per_category)
        blind = self._eligible(candidates, claimed, claimed_art, None)
        # The blind side fills everything the scanned categories did not, cycling
        # as usual (its candidate list is the whole deck minus the matches, so it
        # is rarely short).
        rest = self._order_rule(blind)[:self._size - len(picked)]
        return self._interleave(picked, rest)

    def _eligible(self, candidates, claimed, claimed_art, words):
        """The items still up for grabs: not already spent, not showing a picture
        already spent (when dedupe is on), and -- when `words` is given -- matching
        that category's board scan. `words` None is the blind side, which takes
        anything left.

        Deduping HERE rather than over the whole deck is what lets a word-indexed
        deck work: the thinning happens after the board filter, so each picture is
        represented by a word the board can actually make."""
        available = []
        for item in candidates:
            if item.word in claimed:
                continue
            if self._dedupe_on and item.art in claimed_art:
                continue
            if words is not None and item.word not in words:
                continue
            available.append(item)
        return self._dedupe_rule(available)

    def _round_robin(self, lists):
        """One list taking from each of `lists` in turn, keeping each list's own
        order. Merges the per-category picks before they are spread through the
        blind ones, so a ring holding both multigram and plain-spellable pictures
        alternates between them rather than showing all of one kind first."""
        merged = []
        depth = 0
        deepest = max((len(part) for part in lists), default=0)
        while depth < deepest:
            for part in lists:
                if depth < len(part):
                    merged.append(part[depth])
            depth = depth + 1
        return merged

    # --- SUPERSEDED (kept per the rules-engine style): the single-target blend
    # the belt used before stocking became a weighted mix of categories. One
    # target list, one share knob (the old idea_belt.target_share), targeted
    # picks interleaved through blind ones. _blend_stock does this and more --
    # this is the shape to come back to if the weights turn out to be overkill.
    def _blend_targets_legacy(self, candidates, targets, target_share):
        targeted = [item for item in candidates if item.word in targets]
        blind = [item for item in candidates if item.word not in targets]
        share = min(1.0, max(0.0, target_share))
        want = min(int(round(self._size * share)), len(targeted))
        picked = self._order_rule(targeted)[:want] if want else []
        rest = self._order_rule(blind)[:self._size - len(picked)]
        return self._interleave(picked, rest)

    def _interleave(self, picked, rest):
        """Spread `picked` evenly through `rest`, keeping each list's own order.
        Walks the combined length and takes from `picked` whenever its share of the
        positions filled so far has fallen behind, so 10 targets among 40 blind
        picks land roughly every fourth slot instead of in one block."""
        total = len(picked) + len(rest)
        merged = []
        taken = 0
        for slot in range(total):
            wants_target = taken * total < (slot + 1) * len(picked)
            if wants_target and taken < len(picked):
                merged.append(picked[taken])
                taken = taken + 1
            elif len(merged) - taken < len(rest):
                merged.append(rest[len(merged) - taken])
            elif taken < len(picked):
                merged.append(picked[taken])
                taken = taken + 1
        return merged

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

    # --- board match (idea_belt.match) -------------------------------------
    def clear_word(self, word):
        """Strike every ring item whose word is `word` off the belt, and return
        their art (one entry per item struck, empty when the ring was not showing
        that word at all -- the caller's test for "did the board just answer a
        picture prompt").

        Every picture of that word goes at once: a deck can name the same word on
        two rows (two different pictures), and leaving the second up would ask a
        player to spell a word they had just spelled. A ring that repeats -- deck
        smaller than pool_size -- holds the SAME item object at each of its
        positions, so one strike blanks all of them and reports one entry.
        Idempotent: a word cleared twice strikes nothing the second time, so a
        repeat clear pays no second bonus."""
        struck = []
        for item in self._items:
            if not item.cleared and item.word == word.upper():
                item.cleared = True
                struck.append(item.art)
        return struck

    def targeted_count(self):
        """How many ring items came from a board scan rather than a blind pick
        (idea_belt.stock_category_weight.*). 0 when nothing was scanned -- for the
        stocking log and tests, never shown to the player."""
        return sum(self.stock_counts().values())

    def stock_counts(self):
        """{category -> how many ring slots it stocked}, in most-specific-first
        order -- how the blend actually spent the quotas, recorded as it dealt.
        Only categories that were scanned AND carried weight appear; {} for a
        fully blind ring. The stocking log's breakdown."""
        return dict(self._stocked)

    def active_count(self):
        """How many ring items are still showing (not struck off). The belt's
        "all prompts answered" read; also what tells a full ring from one the
        player has picked clean."""
        return sum(1 for item in self._items if not item.cleared)
