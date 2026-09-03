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
        # {cell -> {"label": Label, "word": str}} for every cell showing a hint.
        # The word is kept for the log and for the toggle-off line, never shown.
        self._idea_hints = {}
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
            state["label"].delete()
        self._idea_hints = {}
        self._idea_hint_last_cell = None

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
        word = self._pick_idea_hint_word(text)
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

    def _pick_idea_hint_word(self, gram_text):
        """A word the board can spell THROUGH a `gram_text` cell, drawn at random.

        Re-rolled on every toggle-on, so a player who wants another idea for the
        same cell just clicks again -- browsing several words for one gram is the
        point, and a stable pick would make the second click look broken.

        The draw goes through the Source seam (source.rand), so a replay reproduces
        the same hints. Scans the hint's word file (a few thousand rows), not the
        dictionary."""
        grams = self._constellation_usable_grams()
        if not grams:
            return ""
        words = sample_words_using_gram(idea_words.candidate_words(), grams,
                                        gram_text, self._constellation_accept(),
                                        # No limit: an early exit would bias the
                                        # draw toward whatever sorts first.
                                        len(idea_words.candidate_words()))
        if not words:
            return ""
        return rand().choice(words)

    # --- the glyph ---------------------------------------------------------
    def _show_idea_hint(self, cell, word):
        """Paint `word`'s emoji behind the cell's letters, half faded."""
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

    def _hide_idea_hint(self, cell, action="hide"):
        """Take the hint off `cell`. `action` is what the log calls it -- a player
        toggling it off is "hide", the board taking it away is "clear"."""
        state = self._idea_hints.pop(cell, None)
        if state is not None:
            state["label"].delete()
            L.log_20009(action, cell, state["gram"], state["word"])

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
