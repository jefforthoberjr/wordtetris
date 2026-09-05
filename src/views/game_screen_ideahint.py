"""The right-click-for-an-idea cell hint (game_screen.idea_hint).

Clicking the same PLACED cell twice in a row paints a half-faded emoji behind its
letters: a picture of some word that cell's gram could help spell, given the rest
of the board. Clicking it twice again clears it.

WHY it exists. Players new to the game read words letter by letter and never think
to cut SHARK as SH + ARK, so the fat cells sit unused all game. The idea belt
teaches the same lesson from the other end (here is a word, go find its letters);
this teaches it cell-first (here is a cell, here is what it could become) and is
otherwise completely independent of the belt -- its own word file, its own fit
floor, its own rules.

WHAT COUNTS AS A HINT. The word must be spellable from the board's usable grams
with the clicked cell's gram as one of the SEGMENTS (see
starting_coverage.sample_words_using_gram) -- not merely a word containing those
letters. A hint the player cannot go and build is a lie, and this feature exists
for the audience least able to tell the difference.

This is a deliberate exception to the no-word-availability-hints rule, and a
bigger one than the belt's: the belt says "this word is makeable somewhere", while
this says "this word is makeable THROUGH this cell". It is off by default for
exactly that reason -- it is a young-player rule (see AGENTS.md, AUDIENCES).

THE DOUBLE CLICK is deliberately not a timed one: any two back-to-back left
clicks on the same cell, however slow. It also does NOT consume the click. Both
clicks still reach the mode underneath, so in the modes where left-click selects
a cell the second click un-selects it exactly as before and the hint appears as
well -- the feature is a passive OBSERVER of the click stream, which is what keeps
it from colliding with every mode's own click handling.

Extracted from views/game_screen.py to keep that file under the 2000-line limit.
"""
import pyglet

from config import CONFIG, get_color, select_rule
from models import idea_words
from source import rand
from starting_coverage import sample_words_using_gram
import log_codes as L


# The emoji fonts, per OS -- pyglet takes the first that resolves. Same list the
# idea belt uses (see TECH.md); duplicated rather than imported so this feature
# carries no dependency on the belt's view module.
EMOJI_FONTS = ("Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji")

# Shared batch for every hint glyph, drawn UNDER the gram labels so the letters
# stay readable on top of the picture. GameScreen.draw() draws it right after the
# board batch. Module-level like the hunt-highlight batch, so nothing has to be
# threaded through the piece constructors.
_batch = pyglet.graphics.Batch()


def get_idea_hint_batch():
    """The shared batch holding every cell's hint glyph."""
    return _batch


class IdeaHintMixin:
    # Default so bare __new__ test instances (which never run _setup_idea_hint)
    # resolve to the original paint-on-the-cell behavior; real games set it from
    # game_screen.idea_hint_display.
    _idea_hint_in_cell = True

    # --- which cells offer a hint (game_screen.idea_hint_digram / _trigram) ---
    # Two INDEPENDENT slots, one per gram size, because they are different
    # teaching moments. A digram (SH, EA) is the cut players miss most often and
    # the one worth prompting hardest; a trigram-or-larger (ARK, ING) is already
    # visually obvious as a chunk, so a mode may want the hint on digrams only.
    # Unigrams never qualify under either -- a single letter needs no idea, and
    # every word contains one.
    def _rule_idea_hint_digram_on(self, gram_text):
        """Two-letter cells offer a hint."""
        return len(gram_text) == 2

    def _rule_idea_hint_digram_off(self, gram_text):
        """Two-letter cells never offer a hint."""
        return False

    def _rule_idea_hint_trigram_on(self, gram_text):
        """Three-or-more-letter cells offer a hint (3+ is one category here, as
        everywhere else in the game)."""
        return len(gram_text) >= 3

    def _rule_idea_hint_trigram_off(self, gram_text):
        """Three-or-more-letter cells never offer a hint."""
        return False

    def _setup_idea_hint(self):
        """Resolve the hint's rules and clear its state. Called from
        GameScreen.__init__ -- per instance, never in a class body, so a game
        mode's overrides are in effect (see the class-attr config freeze note)."""
        rules = CONFIG.get("rules", {})
        digram_rules = {
            "rule_idea_hint_digram_on": self._rule_idea_hint_digram_on,
            "rule_idea_hint_digram_off": self._rule_idea_hint_digram_off,
        }
        self._idea_hint_digram_rule = select_rule("game_screen.idea_hint_digram",
                                                  digram_rules)
        trigram_rules = {
            "rule_idea_hint_trigram_on": self._rule_idea_hint_trigram_on,
            "rule_idea_hint_trigram_off": self._rule_idea_hint_trigram_off,
        }
        self._idea_hint_trigram_rule = select_rule("game_screen.idea_hint_trigram",
                                                   trigram_rules)
        # How faded the picture is behind the letters, 0-255. Half by default --
        # solid enough to read as a picture, faint enough that the gram on top of
        # it stays the thing the eye lands on.
        self._idea_hint_opacity = int(rules.get("game_screen.idea_hint_opacity", 128))
        # WHERE the hint is shown (game_screen.idea_hint_display). A binary knob, so
        # it resolves to a bool rather than a pair of rule functions (the same idiom
        # as game_screen.phase_model -> _single_phase). True paints the faded emoji
        # on the cell AND feeds the debug belt (the original, both-at-once behavior);
        # False paints nothing on the cell and leaves the belt as the whole hint --
        # two escalating hint levels the player opts into rather than one.
        self._idea_hint_in_cell = select_rule(
            "game_screen.idea_hint_display",
            {"rule_idea_hint_show_in_cell": True,
             "rule_idea_hint_belt_only": False})
        # {cell -> {"label": Label, "word": str}} for every cell showing a hint.
        # The word is kept for the log and for the toggle-off line, never shown.
        self._idea_hints = {}
        # Whether the hint-debug belt re-answers as the board changes
        # (idea_belt.hint_debug_refresh). Resolved even with the belt off or in
        # normal mode -- the rule reads state that stays empty there, so it costs a
        # None test per frame.
        refresh_rules = {
            "rule_idea_hint_debug_refresh_off":
                self._rule_idea_hint_debug_refresh_off,
            "rule_idea_hint_debug_refresh_on_board_change":
                self._rule_idea_hint_debug_refresh_on_board_change,
        }
        self._idea_hint_refresh_rule = select_rule("idea_belt.hint_debug_refresh",
                                                   refresh_rules)
        # The cell whose ideas the debug belt is currently showing, and the board
        # those ideas were computed against. Both None whenever the belt is empty.
        self._idea_hint_belt_cell = None
        self._idea_hint_belt_grams = None
        # The cell the LAST left-click landed on, which is the whole double-click
        # test: this click on the same cell as the previous one is a double.
        # Cleared after a toggle so a third click starts a fresh pair rather than
        # flickering the hint on every further click.
        self._idea_hint_last_cell = None

    def reset_idea_hints(self):
        """Take every hint off the board -- a new game, or a board rebuild. The
        labels must be deleted, not just hidden: they live in a module-level batch
        that outlives the board, so dropping the dict alone would leave last game's
        pictures drawn over the new one."""
        for state in self._idea_hints.values():
            if state["label"] is not None:   # belt-only hints carry no glyph
                state["label"].delete()
        self._idea_hints = {}
        self._idea_hint_last_cell = None
        self._idea_hint_belt_cell = None
        self._idea_hint_belt_grams = None

    # --- the click observer ------------------------------------------------
    def _note_idea_hint_click(self, x, y, button):
        """Watch the left-click stream for two clicks in a row on one placed cell.

        Never consumes the click -- the caller carries on into the mode/select
        handling regardless, so this cannot break a mode's own click semantics.
        Returns True when a hint was toggled, for the tests and the caller's
        clarity, not to gate anything."""
        toggled = False
        if button == self._buttons["move_primary"]:
            cell = self._board.cell_at(x, y)
            if cell is not None and cell == self._idea_hint_last_cell:
                toggled = self._toggle_idea_hint(cell)
                # Start a fresh pair either way: without this the third and every
                # later click on the cell would keep toggling.
                self._idea_hint_last_cell = None
            else:
                self._idea_hint_last_cell = cell
        return toggled

    def _toggle_idea_hint(self, cell):
        """Show a hint on `cell`, or clear the one it already has. Returns whether
        anything changed -- False for a cell no hint rule accepts, and for one the
        board can spell nothing through."""
        if cell in self._idea_hints:
            self._hide_idea_hint(cell)
            return True
        gram = self._board.gram_at(*cell)
        if gram is None or gram.is_wild or not gram.text:
            return False
        # The live piece is NOT a target: left-click is how a piece is moved, so a
        # double click there is ordinary movement. Placed cells only.
        if self._idea_hint_covered_by_piece(cell):
            return False
        text = gram.text.upper()
        if not (self._idea_hint_digram_rule(text)
                or self._idea_hint_trigram_rule(text)):
            return False
        words = self._idea_hint_words(text)
        self._feed_idea_hint_belt(cell, text, words)
        word = self._pick_idea_hint_word(words)
        if not word:
            L.log_20009("none", cell, text, "")
            return False
        self._show_idea_hint(cell, word)
        return True

    def _idea_hint_covered_by_piece(self, cell):
        """Whether the live (unplaced) piece sits over `cell`. It is drawn on top,
        so a click there is the player grabbing the piece, not asking about the
        board underneath.

        _current_piece is a METHOD on GameScreen, not an attribute -- reading it
        without calling it yields the bound method, which has no cell positions and
        silently reports every cell as uncovered. A bare __new__ test instance may
        not have it at all, hence the getattr; the modes that deal no visible piece
        (omniswap) return None from it."""
        covered = False
        getter = getattr(self, "_current_piece", None)
        if callable(getter):
            piece = getter()
            if piece is not None and hasattr(piece, "get_cell_positions"):
                covered = cell in piece.get_cell_positions()
        return covered

    def _idea_hint_words(self, gram_text, grams=None):
        """EVERY word the board can spell through a `gram_text` cell, in the hint
        file's order. The pool one hint is drawn from, and the whole list the
        hint-debug belt shows (idea_belt.source).

        `grams` is the board's usable-gram multiset; passed in by the refresh rule,
        which has already read it to decide the board changed at all, so the scan
        is not gathered twice."""
        if grams is None:
            grams = self._constellation_usable_grams()
        if not grams:
            return []
        candidates = idea_words.candidate_words()
        # No limit: an early exit would bias the draw toward whatever sorts first.
        return sample_words_using_gram(candidates, grams, gram_text,
                                       self._constellation_accept(),
                                       len(candidates))

    def _pick_idea_hint_word(self, words):
        """One of `words` at random -- the hint actually shown.

        Re-rolled on every toggle-on, so a player who wants another idea for the
        same cell just clicks again -- browsing several words for one gram is the
        point, and a stable pick would make the second click look broken.

        The draw goes through the Source seam (source.rand), so a replay reproduces
        the same hints."""
        if not words:
            return ""
        return rand().choice(words)

    # --- the glyph ---------------------------------------------------------
    def _show_idea_hint(self, cell, word):
        """Raise `word` as the hint on `cell`: under game_screen.idea_hint_display's
        show_in_cell rule that means painting the word's emoji behind the cell's
        letters, half faded; under belt_only it means recording the hint and
        painting nothing (the belt, already fed by the caller, IS the hint)."""
        if not self._idea_hint_in_cell:
            self._show_idea_hint_belt_only(cell, word)
            return
        emoji = idea_words.emoji_for(word)
        if not emoji:
            return
        px, py = self._board.cell_visual_center(*cell)
        # pyglet MULTIPLIES a label's color into the glyph, so an emoji must keep
        # all three channels at 255 or the color drains out of it (see TECH.md).
        # Only the ALPHA is lowered, which fades the picture without greying it.
        label = pyglet.text.Label(
            emoji, font_name=EMOJI_FONTS,
            font_size=self._cell_size * 0.72,
            x=px, y=py, anchor_x="center", anchor_y="center",
            color=(255, 255, 255, self._idea_hint_opacity), batch=_batch)
        gram_text = self._board.gram_at(*cell).text.upper()
        # The gram is stored, not just the word: a hint is an idea ABOUT THIS
        # GRAM, so it stops being true the moment the cell stops holding it (see
        # _prune_idea_hints).
        self._idea_hints[cell] = {"label": label, "word": word,
                                  "gram": gram_text}
        L.log_20009("show", cell, gram_text, word)

    def _show_idea_hint_belt_only(self, cell, word):
        """The belt-only half of _show_idea_hint: record the hint with NO label, so
        nothing is drawn on the cell but the rest of the feature behaves exactly as
        it does with a glyph -- a second double click toggles it off (and empties the
        belt), and _prune_idea_hints still takes it away when the cell's gram
        changes. Unlike the painted path this cannot fail on a word with no emoji:
        the belt already dropped those itself, and the picked `word` is only kept
        for the log here."""
        gram_text = self._board.gram_at(*cell).text.upper()
        self._idea_hints[cell] = {"label": None, "word": word, "gram": gram_text}
        L.log_20009("show_belt_only", cell, gram_text, word)

    def _hide_idea_hint(self, cell, action="hide"):
        """Take the hint off `cell`. `action` is what the log calls it -- a player
        toggling it off is "hide", the board taking it away is "clear"."""
        state = self._idea_hints.pop(cell, None)
        if state is not None:
            if state["label"] is not None:   # belt-only hints carry no glyph
                state["label"].delete()
            L.log_20009(action, cell, state["gram"], state["word"])
            # The debug belt tracks the LIVE hint, so a hint going away empties it
            # rather than leaving a list of ideas about a cell nobody is asking
            # about any more.
            self._feed_idea_hint_belt(None, state["gram"], [], why=action)

    # --- the hint-debug belt (idea_belt.source) ----------------------------
    def _feed_idea_hint_belt(self, cell, gram_text, words, grams=None,
                             why="click"):
        """Put every idea `gram_text` can give onto the idea belt, replacing what
        the belt was showing.

        A DEBUG view of this feature, and only that: it lays out the pool the hint
        just drew its one word from, so a picture that looks wrong on a cell can be
        checked against the whole set the pick came from. Ignored unless the belt is
        in hint-debug mode, so the young-player belt is untouched by it.

        Words with no emoji are dropped -- they can never be shown as pictures, so
        they are not part of what this cell can OFFER, only of what it can spell."""
        belt = getattr(self, "_idea_belt", None)
        if belt is None or not belt.hint_debug:
            return
        # WHICH cell the belt is now answering for, and the board state its answer
        # was computed against -- what the refresh rule re-reads. `cell` is None
        # when a hint went away, which is also when the belt goes empty.
        self._idea_hint_belt_cell = cell
        self._idea_hint_belt_grams = None
        if cell is not None:
            if grams is None:
                grams = self._constellation_usable_grams()
            self._idea_hint_belt_grams = dict(grams)
        word_art = []
        for word in words:
            emoji = idea_words.emoji_for(word)
            if emoji:
                word_art.append((word, emoji))
        # `why` separates a list dealt by a double click from one the board change
        # re-dealt (idea_belt.hint_debug_refresh) -- otherwise a replay shows a
        # stream of identical ring lines with no way to tell which is which.
        belt.show_hint_ideas(word_art, f"hint debug {why}: {gram_text}")

    # --- refreshing the debug belt (idea_belt.hint_debug_refresh) ----------
    # WHETHER the debug list keeps up with the board. The ideas a cell can give
    # depend on every OTHER cell too, so clearing a word elsewhere changes the
    # answer without touching the cell that was asked about -- and the list on the
    # belt silently becomes a statement about a board that no longer exists.
    def _rule_idea_hint_debug_refresh_off(self):
        """The list is a snapshot of the moment it was asked for: it stays put
        until the next double click. Cheapest, and the right rule when what is
        being checked is the pick itself rather than how the board moves it."""
        return False

    def _rule_idea_hint_debug_refresh_on_board_change(self):
        """Re-scan whenever the board's usable grams change, so the belt always
        answers for the board as it is NOW.

        The trigger is the gram MULTISET, not any particular event: cells stop and
        start supplying grams down a dozen roads (a clear, a grow, a shot, a
        fossilize, a relabel), and comparing state catches every one of them,
        including the ones added next. It also catches only real changes -- a piece
        merely moving around does not re-scan.

        Costs a gram gather per frame while a debug hint is up, and the full
        word-file scan only when that gather comes back different. Nothing at all
        when no hint is showing (the belt has no cell to answer for)."""
        cell = self._idea_hint_belt_cell
        if cell is None:
            return False
        state = self._idea_hints.get(cell)
        if state is None:
            # The hint came down some other way; _hide_idea_hint already emptied
            # the belt, so there is nothing to keep fresh.
            return False
        grams = self._constellation_usable_grams()
        if grams == self._idea_hint_belt_grams:
            return False
        words = self._idea_hint_words(state["gram"], grams)
        self._feed_idea_hint_belt(cell, state["gram"], words, grams,
                                  why="board change")
        return True

    def _refresh_idea_hint_belt(self):
        """Per-frame hook for the refresh rule. Ticked from update() right after
        _prune_idea_hints, in that order deliberately: pruning may take the hint
        (and so the belt) down, and there is no point re-scanning for a cell that
        is about to stop asking."""
        return self._idea_hint_refresh_rule()

    def _prune_idea_hints(self):
        """Drop every hint whose cell no longer holds the gram it was raised for.

        Ticked from update() rather than hooked into the clear pipeline, because a
        cell stops holding its gram down MANY roads -- the phase-end clear batch,
        clear-on-submit, a botanical grow, a shooting-gallery shot, a line blast, a
        cell-health release, a fossilize, a partial-gram relabel, or a right-click
        gram manipulation. Hooking each one means missing the next one added; a
        sweep over state is true by construction for all of them, present and
        future.

        The cost is nothing: self._idea_hints is empty in the overwhelming majority
        of frames (and in every mode with the hint off), and holds a handful of
        entries at worst, so this is a dict-empty test per frame.

        A CHANGED gram counts as gone, not just a cleared cell: after a partial
        clear leaves ARK as AR, the picture of SHARK is no longer an idea that cell
        can deliver, and leaving it up would be the one thing this feature must
        never do -- show the player a word they cannot build."""
        if not self._idea_hints:
            return
        for cell in list(self._idea_hints):
            gram = self._board.gram_at(*cell)
            text = ""
            if gram is not None and not gram.is_wild and gram.text:
                text = gram.text.upper()
            if text != self._idea_hints[cell]["gram"]:
                self._hide_idea_hint(cell, "clear")
