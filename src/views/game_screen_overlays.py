"""Board OVERLAY presentation rules, extracted from views/game_screen.py.

Everything here answers "what else is drawn over the board, besides the cells":

  * the MODE TITLE along the top (game_screen.mode_title)
  * cleared-word PATH TRAILS and how they fade (game_screen.word_trail,
    game_screen.word_trail_fade)
  * the word-HUNT HIGHLIGHT pass that lights the grams of a word being typed in
    the MOVING pane

They travel together because they are all pure presentation layered on a board
that has already been decided: none of them changes what the player may do, only
what they can see about it. Splitting them out keeps game_screen.py under the
2000-line limit (see AGENTS.md); OverlayMixin runs with GameScreen's `self`, so
the board, config rules and side panes are reached exactly as before.
"""

from config import active_mode


class OverlayMixin:
    # Mode-title rule (game_screen.mode_title): whether the current game mode's
    # name is shown as a single line along the top of the board (see draw /
    # self._mode_title_label). Resolved once at construction.
    def _rule_mode_title_on(self):
        """Show the active mode's label (blank if on the bare base config)."""
        active = active_mode()
        self._mode_title_label.text = active[1] if active else ""

    def _rule_mode_title_off(self):
        """No title (leave the label blank so it draws nothing)."""
        self._mode_title_label.text = ""

    # Word-trail rule (game_screen.word_trail): whether a cleared word leaves a
    # path trail overlaid on the board (see _clear_paths / views.word_trail).
    def _rule_word_trail_on(self, accepted):
        """Record a path trail for each cleared word, center to center. Tagged
        with the word's cells, so a trail can later be dropped when those cells
        leave the board -- which is how an attacking word's line disappears with
        the target it was attacking (see CellHealthMixin._release_dead_cells).
        Uses the grid's VISUAL center, so a line into a jumbo hexagon meets it in
        the middle rather than at its anchor triangle."""
        for fw in accepted:
            points = [self._board.cell_visual_center(x, y) for (x, y) in fw.path]
            self._word_trail.add_path(points, cells=fw.path,
                                      fade_seconds=self._trail_fade_rule(fw))

    def _rule_word_trail_off(self, accepted):
        """No path trails (the original behavior)."""
        pass

    # Trail-fade rule (game_screen.word_trail_fade): how long a freshly drawn
    # trail stays before fading itself off the board. Each returns the fade time
    # for ONE word's trail in seconds, or None for "never fades" (it then leaves
    # only with its cells, per _drop_trails_rule). Ticked in views.word_trail's
    # update(); the duration is game_screen.word_trail_fade_seconds, deliberately
    # a game_screen knob rather than an animation.yaml one, since it is a gameplay
    # readability choice per mode and not a piece of the shared animation kit.
    def _rule_word_trail_fade_off(self, fw):
        """Trails never fade: they accumulate for the whole game (the original
        behavior)."""
        return None

    def _rule_word_trail_fade_all(self, fw):
        """Every trail fades out over word_trail_fade_seconds, attacker lines
        included. The board self-cleans; a health target's trail may vanish before
        the target falls."""
        return self._word_trail_fade_seconds

    def _rule_word_trail_fade_nonattacker(self, fw):
        """Fade only the trails that clear plain board cells, and leave a trail
        that runs through a health-carrying cell (obstacle / mission) up. Those
        attacker lines are information -- they show which words are committed to a
        target -- and they already disappear when the target falls, so this fades
        exactly the leftover lines from words spelled away from the targets.
        Identical to rule_word_trail_fade_all when cell health is off (no cell
        carries health, so no word is an attacker)."""
        attacking = False
        for cell in fw.path:
            if cell in self._cell_health:
                attacking = True
        if attacking:
            fade = None
        else:
            fade = self._word_trail_fade_seconds
        return fade

    # Bare-instance defaults for the fade, in the same spirit as CellHealthMixin's
    # block: a __new__ test instance (no __init__, so no select_rule pass) reads the
    # feature as OFF instead of raising. Named methods, not lambdas, so instance
    # access still binds self. __init__ overwrites both.
    _trail_fade_rule = _rule_word_trail_fade_off
    _word_trail_fade_seconds = 0.0

    def _on_hunt_change(self, text):
        """The MOVING-phase hunt field changed (typed / backspaced / cleared):
        re-light every board + active-piece gram involved in the typed word."""
        self._refresh_hunt_highlight(text)

    def _apply_hunt_to_overlay(self, overlay, gram, text):
        """Light `overlay`'s letters per the active match rule, or clear it. Wilds
        (no letters) and empty grams never light."""
        if overlay is None:
            return
        if not text or gram is None or gram.is_wild or not gram.text:
            overlay.clear()
            return
        overlay.set_matched(self._hunt_match_rule(gram.text, text))

    def _refresh_hunt_highlight(self, text=None):
        """Re-apply the word-hunt highlight for `text` (default: the current hunt
        field) across every settled board cell and the visible active piece. Wilds
        are skipped (they render as a sprite, not a label). Empty text clears all.
        Called on each keystroke, on a fresh piece spawn, and after a gram is
        relabeled -- each a cheap per-glyph color pass, no allocation."""
        if text is None:
            text = self._moving_side_pane.hunt_text()
        for (x, y) in self._board.occupied_cells():
            cell = self._board.get_cell(x, y)
            if cell is not None:
                self._apply_hunt_to_overlay(cell.overlay, cell.gram, text)
        # The live piece too (only when it's actually floating on the board -- e.g.
        # omniswap never deals a visible piece, so its current piece is skipped).
        piece = self._current_piece()
        if piece is not None and not piece.placed and piece.visible:
            for _gx, _gy, _c, _l, gram, overlay in piece.get_cell_data():
                self._apply_hunt_to_overlay(overlay, gram, text)
