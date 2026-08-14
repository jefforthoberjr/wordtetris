"""Piece control: the live piece's movement, rotation, hover and placement.

Extracted from views/game_screen.py (which had grown past the 2000-line limit).
PieceControlMixin is mixed into GameScreen, so every method here still runs with
GameScreen's `self` -- it reaches the board, the piece pool, the cell-overlap
rules and the selection pipeline exactly as before.

Two groups live here:

  * The per-grid MOVEMENT RULES (game_screen.movement, wired up in
    game_screen_setup._rule_use_*_grid): each maps the controls.yaml move keys
    onto the grid's actual neighbor directions -- square nudges, hex up/down
    diagonals, triangle flips, and the JUMBO_HEX compound steps.
  * The grid-agnostic PIECE MECHANICS the rules drive: the move/rotate/place
    gate (_move_allowed), the hover hide/restore, and _place_current_piece,
    which hands off to the SELECT pipeline.
"""

from models.hex_domino import hex_neighbor
from models.hex_domino import HEX_UP, HEX_DOWN
from models.hex_domino import HEX_UP_LEFT, HEX_DOWN_LEFT
from models.hex_domino import HEX_UP_RIGHT, HEX_DOWN_RIGHT
from models.piece_placement import place_piece_cells
from models.triangle_domino import triangle_neighbor, triangle_points_up
from models.triangle_domino import TRIANGLE_LEFT, TRIANGLE_RIGHT, TRIANGLE_BASE
from controls import control_keys, control_modifier


class PieceControlMixin:
    """Movement rules + piece mechanics for GameScreen (see module docstring)."""

    # --- movement rules (game_screen.movement) -----------------------------
    # One per grid geometry; each returns whether it handled the key.

    def _rule_square_movement(self, symbol, modifiers):
        """Square grid: A/D/W/S nudge the piece by one cell. Returns handled."""
        handled = True
        if symbol in self._keys["move_left"]:
            self._move_piece(-1, 0)
        elif symbol in self._keys["move_right"]:
            self._move_piece(1, 0)
        elif symbol in self._keys["move_up"]:
            self._move_piece(0, 1)
        elif symbol in self._keys["move_down"]:
            self._move_piece(0, -1)
        else:
            handled = False
        return handled

    def _rule_hex_movement_holdshift(self, symbol, modifiers):
        """Flat-top hex: A=up-left, Shift+A=down-left, D=up-right,
        Shift+D=down-right, W=up, S=down. Returns handled. (The hold modifier is
        controls.yaml game.hex_down_modifier; A/D/W/S are game.move_*.)"""
        shift = (modifiers & control_modifier("game.hex_down_modifier")) != 0
        handled = True
        if symbol in self._keys["move_left"]:
            self._move_piece_hexdir(HEX_DOWN_LEFT if shift else HEX_UP_LEFT)
        elif symbol in self._keys["move_right"]:
            self._move_piece_hexdir(HEX_DOWN_RIGHT if shift else HEX_UP_RIGHT)
        elif symbol in self._keys["move_up"]:
            self._move_piece_hexdir(HEX_UP)
        elif symbol in self._keys["move_down"]:
            self._move_piece_hexdir(HEX_DOWN)
        else:
            handled = False
        return handled

    def _rule_hex_movement_arrows(self, symbol, modifiers):
        """Flat-top hex, arrow-key chords: up+A=up-left, down+A=down-left,
        up+D=up-right, down+D=down-right, W=up, S=down. A/D alone do nothing.
        Returns handled."""
        # Held-key chord: only the first key bound to each arrow is consulted.
        up = self._key_state[control_keys("game.hex_arrow_up")[0]]
        down = self._key_state[control_keys("game.hex_arrow_down")[0]]
        handled = True
        if symbol in self._keys["move_left"]:
            if up:
                self._move_piece_hexdir(HEX_UP_LEFT)
            elif down:
                self._move_piece_hexdir(HEX_DOWN_LEFT)
            else:
                handled = False
        elif symbol in self._keys["move_right"]:
            if up:
                self._move_piece_hexdir(HEX_UP_RIGHT)
            elif down:
                self._move_piece_hexdir(HEX_DOWN_RIGHT)
            else:
                handled = False
        elif symbol in self._keys["move_up"]:
            self._move_piece_hexdir(HEX_UP)
        elif symbol in self._keys["move_down"]:
            self._move_piece_hexdir(HEX_DOWN)
        else:
            handled = False
        return handled

    def _rule_triangle_movement_flipkey(self, symbol, modifiers):
        """Triangle grid: LEFT/RIGHT step sideways, UP or DOWN cross the
        horizontal edge. (Keys are controls.yaml game.move_*.)

        A triangle has only three edges, so there are only three moves. Left and
        right always work (they stay in the row). The third move is the "flip":
        it lands on the cell sharing the horizontal edge, which is BELOW the piece
        when it points up and ABOVE it when it points down -- so W and S are bound
        to the same flip rather than to fixed screen directions. Every second flip
        therefore returns the piece to where it started, and a piece walks up the
        board by alternating flip and a sideways step. Returns handled."""
        handled = True
        if symbol in self._keys["move_left"]:
            self._move_piece_tridir(TRIANGLE_LEFT)
        elif symbol in self._keys["move_right"]:
            self._move_piece_tridir(TRIANGLE_RIGHT)
        elif symbol in self._keys["move_up"] or symbol in self._keys["move_down"]:
            self._move_piece_tridir(TRIANGLE_BASE)
        else:
            handled = False
        return handled

    def _rule_triangle_movement_strict_updown(self, symbol, modifiers):
        """Triangle grid, screen-true vertical keys: LEFT/RIGHT step sideways, and
        UP / DOWN cross the horizontal edge ONLY when that edge is the one they
        point at -- UP works on a point-down cell (its neighbor is above), DOWN on
        a point-up cell (its neighbor is below); the other key is inert on that
        cell. Truer to the key's arrow, but half the vertical presses do nothing.
        The alternative to _rule_triangle_movement_flipkey; swap in
        _rule_use_triangle_grid. Returns handled."""
        piece = self._current_piece()
        points_up = triangle_points_up(piece.grid_x, piece.grid_y)
        handled = True
        if symbol in self._keys["move_left"]:
            self._move_piece_tridir(TRIANGLE_LEFT)
        elif symbol in self._keys["move_right"]:
            self._move_piece_tridir(TRIANGLE_RIGHT)
        elif symbol in self._keys["move_up"]:
            if points_up:
                handled = False   # base neighbor is below; W is inert here
            else:
                self._move_piece_tridir(TRIANGLE_BASE)
        elif symbol in self._keys["move_down"]:
            if points_up:
                self._move_piece_tridir(TRIANGLE_BASE)
            else:
                handled = False   # base neighbor is above; S is inert here
        else:
            handled = False
        return handled

    def _rule_triangle_movement_jumbo(self, symbol, modifiers):
        """Triangle grid, tuned for the JUMBO_HEX cell: LEFT/RIGHT reach the
        up-left/up-right neighboring hexagon positions, holding the down modifier
        with them reaches down-left/down-right, and UP/DOWN go straight up/down.
        Returns handled.

        Why a rule of its own: a hexagon cell's center sits on a lattice VERTEX,
        and the vertices form a HEXAGONAL lattice, not the triangular one the
        cells sit on. Two consequences, both measured from jumbo_hex_center:

          * The BASE flip does not move the piece at all -- it re-anchors the SAME
            hexagon on its other parity. It is a free toggle, not a move.
          * A sideways step moves the hexagon DIAGONALLY, and which diagonal is
            decided by the anchor's parity: it rises from a point-up anchor and
            falls from a point-down one.

        So a diagonal press is "toggle parity if needed (free), then step
        sideways", and the modifier picks the downward diagonal -- the hex board's
        scheme (_rule_hex_movement_holdshift), which reads the same under the
        hand. Straight up/down is one rising (or falling) step each way, which
        cancels the sideways drift and nets exactly one hexagon height.

        Keys are unchanged (controls.yaml game.move_* + the hex down modifier).
        Ordinary small pieces in the same pool keep the plain triangle movement --
        for them a flip IS a move, so the compound steps here would be wrong."""
        piece = self._current_piece()
        if not getattr(piece, "jumbo_cell", False):
            return self._rule_triangle_movement_flipkey(symbol, modifiers)
        shift = (modifiers & control_modifier("game.hex_down_modifier")) != 0
        handled = True
        if symbol in self._keys["move_left"]:
            self._move_piece_jumbo_diagonal(TRIANGLE_LEFT, want_down=shift)
        elif symbol in self._keys["move_right"]:
            self._move_piece_jumbo_diagonal(TRIANGLE_RIGHT, want_down=shift)
        elif symbol in self._keys["move_up"]:
            self._move_piece_jumbo_vertical(want_down=False)
        elif symbol in self._keys["move_down"]:
            self._move_piece_jumbo_vertical(want_down=True)
        else:
            handled = False
        return handled

    def _move_piece_jumbo_diagonal(self, sideways, want_down):
        """One diagonal step of a JUMBO_HEX cell. A sideways step rises from a
        point-up anchor and falls from a point-down one, so when the diagonal the
        player asked for disagrees with the current parity, flip first -- which
        costs no movement -- and then step."""
        piece = self._current_piece()
        rises = triangle_points_up(piece.grid_x, piece.grid_y)
        if rises == want_down:
            self._move_piece_tridir(TRIANGLE_BASE)
        self._move_piece_tridir(sideways)

    def _move_piece_jumbo_vertical(self, want_down):
        """Move a JUMBO_HEX cell straight up or down by one hexagon: one step
        along each diagonal on that side (right then left), whose sideways halves
        cancel and whose vertical halves add."""
        self._move_piece_jumbo_diagonal(TRIANGLE_RIGHT, want_down)
        self._move_piece_jumbo_diagonal(TRIANGLE_LEFT, want_down)

    def _move_piece_tridir(self, direction):
        """Move the piece to its triangle neighbor in the given direction index.
        The BASE step depends on the piece's current parity, so it is resolved
        from the piece's live position (a piece that just moved sideways has
        flipped orientation)."""
        piece = self._current_piece()
        nx, ny = triangle_neighbor(piece.grid_x, piece.grid_y, direction)
        self._move_piece(nx - piece.grid_x, ny - piece.grid_y)

    def _move_piece_hexdir(self, direction):
        """Move the piece to its hex neighbor in the given direction index."""
        piece = self._current_piece()
        nx, ny = hex_neighbor(piece.grid_x, piece.grid_y, direction)
        self._move_piece(nx - piece.grid_x, ny - piece.grid_y)

    # --- piece mechanics ---------------------------------------------------

    def _current_piece(self):
        # A live word-piece (game_screen.player_word_piece) overrides the pool's
        # current piece until it's placed and _advance_piece clears the override.
        if self._override_piece is not None:
            return self._override_piece
        return self._piece_pool.current_piece()

    def _update_hover_visibility(self):
        piece = self._current_piece()
        if piece.placed:
            return
        positions = piece.get_cell_positions()
        self._board.hide_cells_for_hover(positions)

    def _clear_hover_visibility(self):
        piece = self._current_piece()
        positions = piece.get_cell_positions()
        self._board.restore_cells_from_hover(positions)

    def _piece_on_board(self, piece):
        """True only if every cell the piece occupies is on the grid. Off-board
        cells return None from get_cell, so this rejects a piece hanging off any
        edge. One half of the move/rotate/place gate; see _move_allowed."""
        return all(
            self._board.get_cell(x, y) is not None
            for (x, y) in piece.get_cell_positions()
        )

    def _overlapped_cells(self, piece):
        """The occupied board cells the piece currently sits on -- the cells a
        placement would cover. The piece's own cells aren't on the board yet, so
        this reports only settled obstacle / player cells. is_cell_occupied is
        common to the square and hex boards, so it stays grid-agnostic."""
        overlapped = set()
        for (x, y) in piece.get_cell_positions():
            if self._board.is_cell_occupied(x, y):
                overlapped.add((x, y))
        return overlapped

    def _overlap_allowed(self, overlapped):
        """Whether `overlapped` (the occupied cells a position would cover) is
        permitted by ALL FOUR independent overlap slots -- player
        (game_screen.cell_overlap_player), obstacle (..._obstacle), mission
        (..._mission) and fossilized (..._fossilized). A position holds only if
        none of them blocks it -- so a player-allowing, obstacle-blocking config
        still refuses to cover an obstacle. The single gate every move/place
        runs through."""
        return (
            self._cell_overlap_player_rule(overlapped)
            and self._cell_overlap_obstacle_rule(overlapped)
            and self._cell_overlap_mission_rule(overlapped)
            and self._cell_overlap_fossilized_rule(overlapped)
        )

    def _move_allowed(self, piece):
        """The shared move/rotate/place gate: a position is allowed only if every
        cell is on the grid AND the cells it covers satisfy the active cell-
        overlap rules. Driving the overlap rules here -- not just at placement --
        lets a blocking rule stop the piece from being moved onto a forbidden
        cell in the first place, so the player never drags it over one."""
        return self._piece_on_board(piece) and self._overlap_allowed(
            self._overlapped_cells(piece)
        )

    def _move_piece(self, dx, dy):
        piece = self._current_piece()
        self._clear_hover_visibility()
        piece.move(dx, dy)
        # Reject a move that would hang a cell off the grid or violate the cell-
        # overlap rule, restoring the prior position before refreshing the hover.
        if not self._move_allowed(piece):
            piece.move(-dx, -dy)
        self._update_hover_visibility()

    def _handle_move_click(self, x, y):
        """Left-click control (MOVING phase). Clicking a cell the current piece
        occupies rotates it clockwise; clicking any other on-board cell jumps the
        piece there. Clicks off the board, or while the piece is already placed,
        do nothing. The grid maps the pixel to a cell (cell_at), so this works
        the same on the square and hex boards."""
        piece = self._current_piece()
        cell = self._board.cell_at(x, y)
        if not piece.placed and cell is not None:
            if cell in piece.get_cell_positions():
                self._rotate_piece_cw()
            else:
                self._jump_piece_to(cell)

    def _jump_piece_to(self, cell):
        """Translate the current piece so its anchor cell lands on `cell` -- a
        direct jump, not a step-by-step walk through the cells in between. The
        anchor (grid_x, grid_y) is an occupied cell of every piece, so the click
        ends up under the piece. Routed through _move_piece, so an invalid
        landing (off board or a forbidden overlap) is rejected and the piece
        stays put, exactly like a keyboard move."""
        piece = self._current_piece()
        target_x, target_y = cell
        self._move_piece(target_x - piece.grid_x, target_y - piece.grid_y)

    def _rotate_piece_cw(self):
        piece = self._current_piece()
        self._clear_hover_visibility()
        piece.rotate_cw()
        if not self._move_allowed(piece):
            piece.rotate_ccw()  # off the grid or onto a forbidden cell; undo it
        self._update_hover_visibility()

    def _rotate_piece_ccw(self):
        piece = self._current_piece()
        self._clear_hover_visibility()
        piece.rotate_ccw()
        if not self._move_allowed(piece):
            piece.rotate_cw()
        self._update_hover_visibility()

    def _place_current_piece(self):
        piece = self._current_piece()
        # A piece can't be placed while any cell hangs off the grid; ignore the
        # place until the player brings it fully back on-board.
        if not self._piece_on_board(piece):
            return
        # Cells already on the board this placement would cover.
        overlapped = self._overlapped_cells(piece)
        # Cell-overlap rules: may the piece be placed when it covers those cells?
        # A blocking rule (obstacle or mission) refuses and aborts the place
        # (movement is gated the same way, so a blocked piece should never reach
        # here covering them).
        if not self._overlap_allowed(overlapped):
            return
        self._clear_hover_visibility()
        piece.place()

        # One cell per coordinate for an ordinary piece; ONE cell owning the whole
        # footprint for a jumbo-cell piece (see models/piece_placement).
        placed_positions = [(gx, gy) for gx, gy, _gram
                            in place_piece_cells(self._board, piece)]
        # _begin_selection recolors these cells from the live piece's darker
        # active tint to the lighter placed tint and keeps them lit -- through
        # every further placement this moving phase -- to remind the player where
        # words nucleate, until they settle once selection leaves them behind
        # (see _mark_placed_cells / _settle_placed_cells).

        # Cell-overlap action rule: handle the cells just covered (e.g. drop a
        # covered obstacle from the obstacle-cell tracking so it counts as gone).
        self._cell_overlap_action_rule(overlapped)

        # Runs stages 1-3: auto selectors clear and advance immediately;
        # interactive ones enter the SELECTING phase and withhold the next piece
        # until the player hits Next piece (see _end_selection).
        self._begin_selection(placed_positions)
