from config import get_color


class DisambiguationHighlight:
    """The SELECT-phase "Select which one:" chooser drawn as cell highlighting
    rather than blue polylines (the game_screen.disambig_display sibling of
    views.disambiguation_lines.DisambiguationLines).

    Two layers, matching the two things the player needs to see:
      * TEXT highlight -- every cell that ANY candidate would clear has its whole
        gram lit in the hunt-highlight color, reusing the cells' existing per-gram
        overlays (the same set_matched path the MOVING word-hunt drives). This is
        the union of all candidate paths, so it stays put while the player cycles.
      * BACKGROUND tint -- only the CURRENTLY-selected candidate's cells get a pale
        lime fill, so left/right cycling moves the fill from one spelling to the
        next. Each tinted cell's PRIOR color is captured and restored on revert, so
        the fill layers cleanly over whatever the cell already showed (settled,
        obstacle/mission, a fossil or an already-pending green) without needing to
        recompute a resting color.

    A transient overlay like DisambiguationLines: rebuilt on every cycle via show()
    and fully undone on confirm / cancel via clear(). It owns no draw batch -- it
    mutates the board cells' own squares and overlays, which the board's batches
    already draw -- so draw() is a no-op kept only for interface symmetry.

    Only ever active under game_screen.disambig_display: rule_disambig_display_
    highlight; the lines rule leaves this untouched (and vice-versa)."""

    FILL_COLOR = get_color("board.disambig_highlight_fill")

    def __init__(self):
        # Overlays currently lit, so a re-show or clear() can turn them back off.
        self._lit_overlays = []
        # coord -> (square, prior_color) for every cell currently tinted, so a
        # cycle / clear restores each to exactly what it showed before.
        self._tinted = {}

    def show(self, options, selected, board):
        """Light the union of all candidate cells' text and tint the selected
        candidate's cells. `options` is the ordered FoundWord list, `selected`
        indexes the active one, `board` resolves cells (the view is stateless about
        the board between calls, matching DisambiguationLines)."""
        involved = set()
        for fw in options:
            involved.update(fw.path)
        self._light_text(board, involved)
        selected_cells = (
            set(options[selected].path) if 0 <= selected < len(options) else set()
        )
        self._tint_background(board, selected_cells)

    def _light_text(self, board, involved):
        """Light the whole gram of every involved cell via its hunt overlay, and
        drop any overlay lit last frame that is no longer involved."""
        lit = []
        for (x, y) in involved:
            cell = board.get_cell(x, y)
            if cell is None:
                continue
            overlay, gram = cell.overlay, cell.gram
            if overlay is None or gram is None or gram.is_wild or not gram.text:
                continue
            overlay.set_matched([True] * len(gram.text))
            lit.append(overlay)
        for overlay in self._lit_overlays:
            if overlay not in lit:
                overlay.clear()
        self._lit_overlays = lit

    def _tint_background(self, board, selected_cells):
        """Fill the selected candidate's cells lime, reverting cells that dropped
        out of the selection to their captured prior color."""
        for coord in list(self._tinted):
            if coord not in selected_cells:
                square, prior = self._tinted.pop(coord)
                square.color = prior
        for coord in selected_cells:
            if coord in self._tinted:
                continue
            cell = board.get_cell(*coord)
            if cell is None or cell.square is None:
                continue
            # Capture the true prior color BEFORE tinting, so revert is exact.
            self._tinted[coord] = (cell.square, cell.square.color)
            cell.square.color = self.FILL_COLOR

    def clear(self):
        """Undo both layers: unlight every overlay and restore every tinted cell to
        its captured prior color (the chooser closed)."""
        for overlay in self._lit_overlays:
            overlay.clear()
        self._lit_overlays = []
        for (square, prior) in self._tinted.values():
            square.color = prior
        self._tinted = {}

    def draw(self):
        """No own batch -- the board draws the mutated squares/overlays."""
        pass
