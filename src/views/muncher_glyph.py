"""The gram the word muncher is standing on, re-drawn ON TOP of the character.

The muncher is a character standing on the board, not a tile, so he covers the
cell he occupies -- including its letters. Mid-game that is survivable (you
remember what you walked onto), but two cases give the player no chance to have
seen it at all: the cell he SPAWNS on, and -- on a replenishing board -- a cell
that refills underneath him while he stands there after eating it.

WHY THIS IS AN OVERLAY AND NOT A DRAW-ORDER FIX. The obvious fix is to draw the
board after the character. That cannot work: a cell's opaque fill rectangle lives
in the SAME batch as its letters (see the idea-hint comment in
GameScreen.draw), so drawing that batch later paints the fill over the character
and hides him completely. Instead this re-draws just the ONE cell's glyph after
the sprite -- the same trick the word-hunt highlight uses to paint over settled
grams. Nothing is moved between batches and the board's own label is untouched;
it is simply drawn twice, once under the character and once over him.

The overlay mirrors the live cell label every frame rather than building its own
styling, so a glyph's font size (which varies with gram length) and its
score-gradient color stay exactly right with no second copy of those rules. Cells
whose "label" is a SPRITE rather than text -- the wild vowels -- are skipped:
there are no letters to rescue, and the muncher cannot eat a wild cell anyway.

Switched by game_screen.muncher_glyph_overlay; off leaves the character opaque.
"""

import pyglet


class MuncherGlyphOverlay:
    """One re-drawn glyph, following whichever cell the character occupies."""

    def __init__(self):
        # Built empty and restyled on every sync from the cell label it is
        # mirroring. No batch: it is drawn by hand, after the sprite.
        self._label = pyglet.text.Label(
            "", weight="bold", anchor_x="center", anchor_y="center")
        self._visible = False

    def sync(self, board, pos):
        """Match the glyph of the cell at `pos`, or go blank when there is nothing
        to re-draw -- an empty cell, a cell off the board, a wild cell (a sprite,
        not text), or a label the board itself has hidden (the hover preview hides
        the cell under the cursor, and the overlay must not put it back)."""
        source = None
        if pos is not None:
            cell = board.get_cell(*pos)
            if cell is not None and cell.label is not None:
                # A wild cell's "label" is a Sprite; only a real text Label has
                # .text / .font_size to copy.
                if getattr(cell.label, "visible", True) and hasattr(cell.label, "text"):
                    source = cell.label
        self._visible = source is not None and bool(source.text)
        if self._visible:
            self._copy_style(source)

    def _copy_style(self, source):
        """Take text, size, color and position straight off the board's own label,
        so the copy is pixel-identical to what is already drawn underneath."""
        label = self._label
        if label.text != source.text:
            label.text = source.text
        if label.font_size != source.font_size:
            label.font_size = source.font_size
        label.color = source.color
        label.x = source.x
        label.y = source.y

    def draw(self):
        if self._visible:
            self._label.draw()

    def delete(self):
        """Release the label (game teardown / mode restart)."""
        self._label.delete()
