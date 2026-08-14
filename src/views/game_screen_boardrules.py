"""Board, victory, phase-transition and select-gating rules extracted from GameScreen. A mixin -- every method runs with GameScreen's self. Holds the victory / fill-board / cell-overlap rules, the phase-change + end-state machine (_set_phase, _check_victory, _enter_*), and the select-trigger / typewriter-swap / isolated-skip / select-click rules. Kept out of game_screen.py to bound its size (see AGENTS.md)."""

import math

from views.game_phase import Phase
from config import select_rule, get_color, get_string, CONFIG
import session_log
import log_codes as L


class BoardRulesMixin:
    # --- victory rules (game_screen.victory) -----------------------------
    # Each returns True when its win condition is met against the current board.
    # Selected in __init__; consulted by _check_victory after every clear and
    # before each spawn.
    def _rule_victory_missions_cleared(self):
        # Win once every starting mission cell has been cleared, regardless of any
        # obstacle or player cells left on the board. _mission_cells shrinks as
        # cells clear (see _clear_paths) / get covered (see the overlap-action
        # rule), so empty == all gone. Guard against a mission-less board never
        # having had missions to clear.
        return len(self._mission_cells) == 0 and self.MISSION_COUNT > 0

    def _rule_victory_missions_and_obstacles_cleared(self):
        # Win once every starting mission AND obstacle cell has been cleared,
        # regardless of player cells left on the board. Both tracking sets must be
        # empty; guard against a board that started with neither.
        started_with_targets = self.MISSION_COUNT > 0 or self.OBSTACLE_COUNT > 0
        all_gone = len(self._mission_cells) == 0 and len(self._obstacle_cells) == 0
        return all_gone and started_with_targets

    def _rule_victory_obstacles_cleared(self):
        # Win once every starting obstacle cell has been cleared. _obstacle_cells
        # shrinks as cells clear (see _clear_paths), so empty == all gone. Guard
        # against an obstacle-less board never having had obstacles to clear.
        return len(self._obstacle_cells) == 0 and self.OBSTACLE_COUNT > 0

    def _rule_victory_grid_empty(self):
        # Win once the board holds no cells at all -- the whole-board-cleared
        # endgame (constellation with rule_remove_cells, no replenish; also the
        # jigsaw grid-empty win). An already-empty opening board can't win.
        return len(self._board.occupied_cells()) == 0

    def _rule_victory_grid_fossilized(self):
        # Win once every board cell is fossilized -- the whole-board-frozen
        # endgame (constellation / omniswap with rule_fossilize_cells). Mirrors
        # _rule_fill_board_all_fossilized but as a victory condition. Guards
        # against an empty board reading as trivially won.
        cells = self._all_board_cells()
        return bool(cells) and all(c in self._fossilized_cells for c in cells)

    def _rule_victory_none(self):
        # No victory condition: the game runs until the player quits (the
        # original endless behavior, preserved as a selectable option).
        return False

    # --- fill-board rules (game_screen.fill_board) -------------------------
    # Each returns True when the board counts as entirely "filled" -- the meaning
    # differs by mode. Consulted by _check_board_fill after every clear / settle;
    # the bonus fires once per game (see _fill_board_awarded).
    def _all_board_cells(self):
        """Every valid board cell coordinate (the whole rectangle; both grids'
        is_valid is a plain bounds check, so no cell is masked out). The same walk
        the uniform-fill formation uses."""
        return [(x, y)
                for y in range(self._board.height)
                for x in range(self._board.width)
                if self._board.is_valid(x, y)]

    def _rule_fill_board_all_fossilized(self):
        """Full when every board cell is fossilized (the fossilize modes: omniswap
        / typewriter, where a completed-word cell freezes until the whole board is
        frozen). Guards against an empty board reading as trivially full."""
        cells = self._all_board_cells()
        return bool(cells) and all(c in self._fossilized_cells for c in cells)

    def _rule_fill_board_all_occupied(self):
        """Full when every board cell holds a settled piece (the place/remove
        modes: jigsaw fills empty cells until none remain)."""
        cells = self._all_board_cells()
        return bool(cells) and len(self._board.occupied_cells()) >= len(cells)

    def _rule_fill_board_off(self):
        """No whole-board fill bonus."""
        return False

    def _check_board_fill(self):
        """Award the whole-board fill bonus the first time the active fill rule
        reports the board full (once per game). Idempotent after the award and
        rule-gated, so it is safe to call from every clear / settle site."""
        if self._fill_board_awarded or not self._fill_board_rule():
            return
        self._fill_board_awarded = True
        bonus = self._scorer.fill_board_bonus_rule()
        L.log_50002(bonus, len(self._all_board_cells()))
        self._refresh_score()

    # --- cell-overlap rules (game_screen.cell_overlap_player / _obstacle / _mission)
    # One independent allow/block pair per piece track. Each receives the full set
    # of occupied cells the piece would cover (`overlapped`) and filters to its own
    # track; _overlap_allowed ANDs all three. A covered obstacle/mission cell is
    # dropped from its tracking set by the overlap-action rule, so a player cell
    # never lingers at an obstacle/mission coordinate and the block rules stay in
    # sync with the victory rules. Player cells are the covered cells in neither
    # tracking set.
    def _players_covered(self, overlapped):
        # The covered cells belonging to neither the obstacle nor mission track.
        return overlapped - self._obstacle_cells - self._mission_cells

    def _rule_moveandplace_over_player_cell(self, overlapped):
        # Player-overlap rule: moving or placing over a player cell is always
        # permitted. `overlapped` is ignored.
        return True

    def _rule_block_moveandplace_over_player_cell(self, overlapped):
        # Player-overlap rule: a piece may not move onto or place over a player
        # cell. Permitted unless it would cover one.
        return len(self._players_covered(overlapped)) == 0

    def _rule_moveandplace_over_obstacle_cell(self, overlapped):
        # Obstacle-overlap rule: moving or placing over an obstacle cell is always
        # permitted. `overlapped` is ignored.
        return True

    def _rule_block_moveandplace_over_obstacle_cell(self, overlapped):
        # Obstacle-overlap rule: a piece may not move onto or place over an
        # obstacle cell. Permitted unless it would cover one.
        obstacles_covered = overlapped & self._obstacle_cells
        return len(obstacles_covered) == 0

    def _rule_moveandplace_over_mission_cell(self, overlapped):
        # Mission-overlap rule: moving or placing over a mission cell is always
        # permitted. `overlapped` is ignored.
        return True

    def _rule_block_moveandplace_over_mission_cell(self, overlapped):
        # Mission-overlap rule: a piece may not move onto or place over a mission
        # cell. Permitted unless it would cover one.
        missions_covered = overlapped & self._mission_cells
        return len(missions_covered) == 0

    def _rule_moveandplace_over_fossilized_cell(self, overlapped):
        # Fossilized-overlap rule: moving or placing over a fossilized cell is
        # always permitted. `overlapped` is ignored.
        return True

    def _rule_block_moveandplace_over_fossilized_cell(self, overlapped):
        # Fossilized-overlap rule: a fossilized cell is frozen -- a piece may not
        # move onto or place over one. Permitted unless it would cover one. (The
        # typewriter swap gates on _is_fossilized directly; this is the move/place
        # gate, so a fossilize+jigsaw combo is blocked too.)
        return len(overlapped & self._fossilized_cells) == 0

    def _rule_old_cells_get_delete(self, overlapped):
        # Cell-overlap action rule: the cells a placement covers are treated as
        # gone. The board already overwrote their contents in place(); this drops
        # any covered starting-obstacle / mission coordinates from their tracking
        # sets so a covered obstacle (or mission) counts as cleared for its
        # victory rule.
        self._obstacle_cells.difference_update(overlapped)
        self._mission_cells.difference_update(overlapped)
        # A covered cell counts as gone, so it stops tracking health too (else a
        # buried obstacle would sit in _cell_health forever). No-op when the
        # health feature is off. See views/game_screen_health.py.
        self._forget_cell_health(overlapped)

    # --- whole-game countdown (game_screen.game_timer_seconds) ------------
    # A single wall clock owned by GameScreen (not any one mode), so ANY mode can
    # be time-boxed -- the mode-agnostic sibling of the omniswap timer, which lives
    # inside OmniswapVsTimerMode. Runs across MOVING and SELECTING alike and ends
    # the game (FINISHED, no win check) at zero. Off (a no-op) when the config is 0.
    def _start_game_timer(self):
        """Arm the countdown to its full length as play begins (_finish_loading).
        No-op when the timer is off; harmless in modes that run their own clock."""
        if not self._game_timer_on:
            return
        self._game_timer_remaining = float(self._game_timer_seconds)
        self._game_timer_last_shown = None
        L.log_40001(int(self._game_timer_remaining))
        self._show_game_timer()

    def _tick_game_timer(self, dt):
        """Decrement the whole-game clock once per play frame (called from update()
        during MOVING and SELECTING; the menu-open / LOADING guards there pause it).
        At zero, end the game outright, like the omniswap race clock. Only ticks in
        the two play phases -- update() still runs in VICTORY (to draw the end
        panel), so without this the expired clock would re-fire _enter_endgame every
        frame and the FINISHED overlay could never be dismissed."""
        if not self._game_timer_on:
            return
        if self._phase not in (Phase.MOVING, Phase.SELECTING):
            return
        self._game_timer_remaining -= dt
        if self._game_timer_remaining <= 0:
            self._game_timer_remaining = 0
            self._show_game_timer()
            L.log_40002("game_timer", "ended_game")
            self._enter_endgame()
            return
        self._show_game_timer()

    def _show_game_timer(self):
        """Paint the whole seconds left onto whichever side pane is showing. Both
        panes are painted (in single-phase they are the same merged pane); a phase
        switch may have just overwritten the label, so _set_phase clears the cache
        to force a repaint next tick. Only pushes on a whole-second change."""
        secs = int(math.ceil(self._game_timer_remaining))
        if secs == self._game_timer_last_shown:
            return
        self._game_timer_last_shown = secs
        self._moving_side_pane.set_time_label(secs)
        if (self._selecting_side_pane is not None
                and self._selecting_side_pane is not self._moving_side_pane):
            self._selecting_side_pane.set_time_label(secs)

    def _set_phase(self, new_phase):
        """Single point for phase changes: log the transition (log_10001) then
        switch. Every `self._phase` assignment routes through here so the session
        log's phase track is complete and the format lives in one place. A no-op
        repeat (same phase) is not logged; the construction-time default is logged
        only as a no-session no-op."""
        old = getattr(self, "_phase", None)
        self._phase = new_phase
        if old is not new_phase:
            L.log_10001(old, new_phase)
            # A running whole-game timer paints the pane's top label; the phase
            # switch may have just rewritten that label (e.g. the pieces count on
            # entering MOVING), so force a repaint on the next tick.
            if getattr(self, "_game_timer_on", False):
                self._game_timer_last_shown = None
            # Leaving SELECT with the "select which one" chooser still open (e.g.
            # a timer forced the phase out from under it): drop its overlay +
            # prompt so no candidate lines linger into MOVING.
            if old == Phase.SELECTING and self._disambiguating():
                self._end_disambiguation()
            # Leaving MOVING clears the word-hunt field (and its highlight), so no
            # hunt lingers into SELECTING or the next MOVING phase.
            if old == Phase.MOVING and getattr(self, "_moving_side_pane", None):
                self._moving_side_pane.clear_hunt()

    def _check_victory(self):
        """If the active victory rule is satisfied, enter VICTORY and return
        True; otherwise return False. Already being in VICTORY counts as True so
        callers never spawn a piece past the win."""
        won = self._phase == Phase.VICTORY
        if not won and self._victory_rule():
            self._enter_victory()
            won = True
        return won

    def _enter_victory(self):
        """End the game on a win: show the end panel reading VICTORY."""
        self._enter_endstate(get_string("victory"))

    def _enter_endgame(self):
        """End the game with no win verdict -- the MOVING_TYPEWRITER cursor ran off
        the board, the omniswap race clock hit zero, or a losing condition fired
        (misspell-instadeath): show the end panel reading FINISHED, and swap the
        moving pane's top label to match (so the last countdown value isn't left
        frozen behind the overlay). No time bonus: a FINISHED end is never rewarded
        for time left on the clock (see _enter_endstate)."""
        self._moving_side_pane.set_finished_label()
        self._enter_endstate(get_string("finished"), award_time_bonus=False)

    def _enter_endstate(self, label_text, award_time_bonus=True):
        """Shared end transition: label the end panel `label_text`, settle the
        last placed piece (so no cell is left tinted) and stop play. Phase.VICTORY
        is the single frozen end-state -- the overlay is drawn by draw() and the
        right pane reverts to the cleared-word list (phase no longer SELECTING);
        the label is what distinguishes a win from a plain finish.
        `award_time_bonus` gates the leftover-clock bonus (True only on a win)."""
        self._victory_overlay.set_text(label_text)
        self._end_overlay_dismissed = False
        self._set_phase(Phase.VICTORY)
        self._settle_placed_cells()
        # Roll the end-of-game clip (fullscreen, over the end panel), if this mode
        # set game_screen.end_video. A no-op otherwise; it removes itself when done.
        self._end_video.play()
        if self._end_video.active:
            L.log_50003(self._end_video.name)
        # Restore the system cursor if the shooting-gallery crosshair was hiding it,
        # so the player can dismiss the end panel (phase is no longer MOVING).
        self._sync_shooting_cursor()
        # End-of-game bonus for time left on the clock (per whole second), awarded
        # ONLY on a win (award_time_bonus). A FINISHED end -- timer expiry, cursor
        # off-board, or a LOSING condition like misspell-instadeath -- earns nothing:
        # without this guard an early loss with most of the clock unspent banked a
        # huge unearned bonus (instadeath at ~16s of a 300s game -> +284). Read
        # whichever clock is active -- the whole-game timer (owned here) if on, else
        # the countdown mode's remaining seconds. Refresh the readout regardless so
        # the (possibly unchanged) score shows before the end panel freezes.
        if award_time_bonus:
            if getattr(self, "_game_timer_on", False):
                remaining = self._game_timer_remaining
            else:
                remaining = getattr(self._moving_mode, "_remaining", 0) or 0
            self._scorer.time_bonus_rule(remaining)
        self._refresh_score()
        # Close out the session: the final tally, then the session-end line, then
        # flush + close. on_exit finds nothing open afterward.
        L.log_50001(label_text, len(self._cleared_word_history),
                    len(self._obstacle_cells), len(self._mission_cells),
                    self._scorer.total)
        L.log_00002(label_text)
        session_log.close(reason=label_text)

    def _is_fossilized(self, cell):
        """Whether (x, y) `cell` has been fossilized by a formed word -- dead to
        word-finding and swapping, skipped by the typewriter cursor. Always False
        until a fossilize clear-action populates _fossilized_cells."""
        return cell in self._fossilized_cells

    # --- selection-trigger rules (game_screen.select_trigger) --------------
    # Decide whether the placement just made is a "selection turn". The counter
    # they share (_placements_until_select) is the number the moving pane shows.
    def _rule_select_every_placement(self):
        """Original behavior: every placed piece is a selection turn. The
        countdown is meaningless here, so pin it to 1 (always 'this piece')."""
        self._placements_until_select = 1
        return True

    def _rule_select_after_n_placements(self):
        """Selection turns come once every select_trigger_count placements. Tick
        the countdown down each placement; when it hits zero this placement is
        the selection turn and the counter resets for the next cycle."""
        self._placements_until_select -= 1
        if self._placements_until_select <= 0:
            self._placements_until_select = self._select_trigger_count
            return True
        return False

    # --- typewriter swap-placed rules (game_screen.typewriter_swap) ---------
    # On a MOVING_TYPEWRITER cursor<->cell swap, decide which of the two cells
    # count as placed (nucleation sites) this turn. Whatever isn't returned here
    # is left as a settled board cell.
    def _rule_swap_places_cursor_only(self, cursor, other):
        """Only the cursor cell is placed; the swapped-in cell settles, so a
        cleared word must nucleate around the cursor."""
        return [cursor]

    def _rule_swap_places_both(self, cursor, other):
        """Both swapped cells are placed (original behavior): a word may nucleate
        around either end of the swap."""
        return [cursor, other]

    # --- isolated-piece skip rules (game_screen.skip_select_isolated) -------
    # On a selection turn, decide whether to skip it because the placed pieces
    # are isolated (none touches the board, so no word can bridge them). Receives
    # the accumulated placed set, so a turn is skipped only when EVERY piece
    # placed this phase is stranded -- one adjacent piece keeps it.
    def _rule_skip_select_if_isolated(self, placed_positions):
        """Skip the selection stage when no placed piece touches anything on the
        board (original behavior, generalized to the accumulated set)."""
        return not self._piece_touches_existing(placed_positions)

    def _rule_never_skip_select(self, placed_positions):
        """Always run the selection stage, isolated pieces or not."""
        return False

    # --- select-phase board-click rules (game_screen.select_click) ----------
    # While SELECTING, decide what a left-click on a board cell does.
    def _rule_select_click_move_piece(self, x, y):
        """Route a SELECTING-phase board click to the active MOVING mode's board
        handler, so the player can rearrange cells (the omniswap swap, a jigsaw
        move, ...) without first leaving word entry -- the SELECTING/MOVING blur.
        The mode may change the board (a completed swap), so re-find the
        clearable words afterward; otherwise a word the player just made by
        swapping would still read as 'not on the board'. The pane's own button
        clicks are handled before this rule runs."""
        self._moving_mode.on_mouse_press(x, y, self._buttons["move_primary"])
        self._recompute_candidates()

    def _rule_select_click_none(self, x, y):
        """Board clicks do nothing while selecting (piece-moving disabled)."""
        pass
