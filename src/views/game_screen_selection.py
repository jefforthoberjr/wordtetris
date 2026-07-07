"""Selection / word-clearing pipeline extracted from GameScreen: begin_selection, recompute_candidates, clear_paths and the clear-action / clear-timing / disambiguation-chooser / word-limit / player-word-piece rules, plus submission error wording, scoring glue and advance/end-selection. A mixin -- every method runs with GameScreen's self; the __init__ registries resolve these by name. Kept out of game_screen.py to bound its size (see AGENTS.md)."""

from views.game_phase import Phase
from models.gram import Gram
from models.word_dictionary import (
    is_word, is_prefix, is_obscure, select_maximal_paths, all_words)
from config import select_rule, get_color, get_string, CONFIG
import log_codes as L
from source import rand


class SelectionMixin:
    def _request_select(self):
        """The player asked to open SELECTING now (the moving pane's Select
        button). Delegates to the active mode's request_select hook so each mode
        decides how to leave MOVING -- the default commits an empty placed set
        (nucleate anywhere), omniswap reuses its ENTER/timer path."""
        self._moving_mode.request_select()

    def _begin_selection(self, placed_positions):
        """Called after each placement. Add the new piece to the accumulated
        placed set (kept lit in the placed tint), recompute the move's
        candidates, then let the phase-transition rules decide what happens.

        Two rules gate the selection stage. The trigger rule
        (game_screen.select_trigger) decides whether this placement ends the
        moving phase -- and advances the moving-pane countdown either way, so it
        runs every placement. On a non-selection turn the piece simply stays lit
        and play moves to the next piece, the placed cells accumulating until the
        trigger fires. On a selection turn the skip rule
        (game_screen.skip_select_isolated) drops it when no placed piece touches
        the board (no word can bridge one); otherwise the auto selector clears
        instantly or the interactive selector enters the SELECTING phase (next
        piece withheld). Every placed piece since the last selection settles
        together once the turn resolves."""
        self._mark_placed_cells(placed_positions)
        self._recompute_candidates()
        is_select_turn = self._select_trigger_rule()
        # Reflect the (possibly reset) countdown in the moving pane now, so the
        # right label is correct the moment that pane is next shown.
        self._moving_side_pane.set_phase_label(self._placements_until_select)
        if not is_select_turn:
            # Still mid-phase: leave the placed pieces lit and advance the turn.
            self._moving_mode.advance()
            return
        # Selection turn: skip it if none of the placed pieces touch the board.
        # The accumulated set (not just the last piece) is the adjacency test, so
        # a word bridging any placed piece keeps the turn.
        if self._skip_select_rule(self._move_placed):
            self._settle_placed_cells()
            self._moving_mode.advance()
            return
        if not self._selector.interactive:
            self._clear_paths(self._selector.choose(self._candidates))
            self._settle_placed_cells()
            # The clear may have met the victory condition; only spawn the next
            # piece if it didn't.
            if not self._check_victory():
                self._moving_mode.advance()
        else:
            # UX shortcut: carry any word already typed in the MOVING word-hunt
            # field into the SELECT typed-word field, so opening SELECT (ENTER)
            # with a hunted word pre-loads it. Grab it before _set_phase clears the
            # hunt field (see clear_hunt in _set_phase).
            hunted = self._moving_side_pane.hunt_text()
            self._set_phase(Phase.SELECTING)
            # Fresh batch for this selection phase (no-op in clear-on-submit mode).
            self._pending = []
            self._words_submitted_this_select = 0
            self._selecting_side_pane.begin()
            if hunted:
                self._selecting_side_pane.prefill(hunted)
            self._dictionary_count_rule(self._selecting_side_pane, len(self._player_dict))
            # Show the current running total on the freshly-begun selecting pane.
            self._selecting_side_pane.set_score_label(self._scorer.total)
            # Auto-submit the carried word (game_screen.select_autosubmit_hunt) so
            # the SAME ENTER that opened SELECT lands on the blue-path confirm --
            # no dead middle ENTER to submit a word already in the field. A junk /
            # too-short hunt just rejects (ghost + reason, field cleared). Off:
            # leave it pre-loaded for a manual confirm/edit (original behavior).
            if hunted and self._select_autosubmit_hunt:
                self._on_submit_word(hunted)

    def _recompute_candidates(self):
        """Re-run stages 1-2 against the current board and refresh the word sets
        a typed submission is checked against. Also builds the wider sets the
        error diagnosis needs to tell apart 'too short' from 'didn't involve the
        placed piece' from 'isn't on the board':

          _board_words_any  -- every dictionary word on the board, ignoring the
                               length minimum (so a too-short word still shows up)
          _length_ok_words  -- those that also meet the length rule
          _candidate_words  -- length-OK words that nucleate around the move's
                               still-present placed cells (the clearable set),
                               mapped word -> path (first path wins a tie)

        Constellation mode never enumerates the board (a word is matched on
        submit), so it takes the cheap branch that just clears these maps.
        """
        if self._constellation:
            self._recompute_candidates_constellation()
            return
        live_placed = {
            p for p in self._move_placed if self._board.gram_at(*p) is not None
        }
        found_any = self._find_words(apply_length=False)
        self._board_words_any = {fw.word for fw in found_any}
        found = [fw for fw in found_any if self._word_length_rule(fw.word, fw.path)]
        self._length_ok_words = {fw.word for fw in found}
        # Stage 2: nucleate, then apply the independent placed-cell requirement,
        # then the independent fossil requirement.
        nucleated = self._nucleation_rule(found, live_placed)
        placed_ok = self._placed_cell_rule(nucleated, live_placed)
        # Words that clear the pipeline up to (but not counting) the fossil
        # requirement, so _submission_error can tell a fossil-only rejection apart
        # from a placed-piece one (equal to the candidate set when the fossil
        # requirement is optional).
        self._pre_fossil_words = {fw.word for fw in placed_ok}
        self._candidates = self._fossil_requirement_rule(placed_ok)
        # Of several ways to spell the same word (different paths, or different
        # wild-vowel expansions), keep the one covering the fewest cells, so a
        # typed word makes the most compact clear -- e.g. a single wild as "OA"
        # over two wilds as "O"+"A" -- leaving more cells in play.
        by_word = {}
        for fw in self._candidates:
            by_word.setdefault(fw.word, []).append(fw)
        # All spellings per word (batch mode hands out a distinct path per
        # re-submit) plus the single fewest-cell pick (instant mode clears it).
        self._candidate_word_options = by_word
        self._candidate_words = {}
        for word, options in by_word.items():
            self._candidate_words[word] = self._fewest_cell_word(options)

    def _fewest_cell_word(self, found_words):
        """Pick the FoundWord covering the fewest cells; break ties at random.
        Used when a typed word can be cleared several ways (common with wild
        vowels)."""
        fewest = min(len(fw.path) for fw in found_words)
        smallest = []
        for fw in found_words:
            if len(fw.path) == fewest:
                smallest.append(fw)
        return rand().choice(smallest)

    def _encode_variation(self, found):
        """Encode the gram grouping a cleared word was made of, for the player
        dictionary: each cell's contributed letters in order, joined by the
        active grid's separator (_gram_separator -- "|" square, "/" hex). A wild
        cell wraps the run it resolved to in "?...?"; a starting-obstacle cell
        wraps in "[ ]" and a starting-mission cell in "<>" (each outside the wild
        marker, e.g. "[?ea?]" / "<?ea?>"). A cell is at most one of obstacle /
        mission (distinct pieces never share a cell), so the wraps don't combine.
        Must run before _clear_paths prunes the tracking sets, so a just-cleared
        obstacle or mission still reads as one."""
        parts = []
        for (x, y), segment in zip(found.path, found.segments):
            gram = self._board.gram_at(x, y)
            text = segment.lower()
            if gram is not None and gram.is_wild:
                text = "?" + text + "?"
            if (x, y) in self._obstacle_cells:
                text = "[" + text + "]"
            elif (x, y) in self._mission_cells:
                text = "<" + text + ">"
            parts.append(text)
        return self._gram_separator.join(parts)

    def _sand_positions(self):
        """The board cells currently timed as sand cells (the
        rule_omniswap_timer_sand variant), or an empty set for every other
        mode/timer variant. Used to score sand-timer ("double points") cells."""
        sand = getattr(self._moving_mode, "_sand", None)
        if sand is None:
            return frozenset()
        return set(sand.active_positions())

    def _word_score_facts(self, fw):
        """The board-derived scoring facts for one cleared word: its cell/gram
        lengths and how many of its cells are obstacle / mission / sand-timer /
        already-fossilized. Captured BEFORE the clear-action mutates the cell-kind
        sets (see _clear_paths); combined with is_new and passed to the scorer.
        Returns a kwargs dict for Scorer.score_word_rule (minus is_new)."""
        path = fw.path
        sand = self._sand_positions()
        return {
            "word_length": len(fw.word),
            "gram_lengths": [len(seg) for seg in fw.segments],
            "obstacle_cells": sum(1 for c in path if c in self._obstacle_cells),
            "mission_cells": sum(1 for c in path if c in self._mission_cells),
            "sand_cells": sum(1 for c in path if c in sand),
            # Reusing an ALREADY-fossilized cell in a new word (fossil_word_use
            # allow); the word's own cells fossilize only after this is captured.
            "fossil_reuse_cells": sum(1 for c in path if c in self._fossilized_cells),
        }

    def _refresh_score(self):
        """Push the running point total to the score readout in whichever play
        panes exist (the moving pane always; the selecting pane once created)."""
        total = self._scorer.total
        self._moving_side_pane.set_score_label(total)
        if self._selecting_side_pane is not None:
            self._selecting_side_pane.set_score_label(total)

    def _clear_paths(self, found_words):
        """Stage 4: apply the chosen FoundWords to the board. Gates each word
        through the repeat rule, captures its gram grouping (before any cell
        changes), then hands the accepted words to the active clear-action rule
        (game_screen.clear_action) -- which removes or fossilizes their cells and
        reports which (if any) fully left the board. Records history + the player
        dictionary and lists the words; returns the words actually applied."""
        accepted = [fw for fw in found_words if self._repeat_rule(fw.word)]
        cleared_words = [fw.word for fw in accepted]
        # Leave a path trail per accepted word (gated by game_screen.word_trail).
        # Captured here, before any cell change, so the centers are still valid
        # even when the clear-action removes the cells.
        self._word_trail_rule(accepted)
        # The gram grouping each word was made of, captured BEFORE any cell change
        # so an obstacle / mission / partial gram still reads true.
        cleared_variations = [self._encode_variation(fw) for fw in accepted]
        # Board-derived scoring facts, captured BEFORE the clear-action mutates the
        # cell-kind sets -- same reason as cleared_variations (a fossilize action
        # would otherwise fossilize a word's own cells and read them as reuse, and
        # a remove action would drop cleared obstacle/mission cells from the sets).
        score_facts = [self._word_score_facts(fw) for fw in accepted]
        fully_cleared = self._clear_action_rule(accepted)
        # A starting obstacle or mission cell counts as gone only once FULLY
        # cleared; a partially-used (or fossilized) one stays tracked.
        self._obstacle_cells.difference_update(fully_cleared)
        self._mission_cells.difference_update(fully_cleared)
        for word in cleared_words:
            self._cleared_word_history.add(word)
        # Count every cleared word (repeats included) so the fossil requirement's
        # first-word skip knows the opening word has landed (see
        # _rule_fossil_skip_first_word).
        self._words_cleared_this_game += len(cleared_words)
        if cleared_words:
            # Record each word + its gram grouping in the player's lifetime
            # dictionary (instant autosave). add() returns True only for words
            # never collected before, so they list green; a word re-collected
            # with a new grouping saves the grouping but stays black (the count
            # didn't grow).
            new_flags = []
            obscure_flags = []
            word_scores = []
            for fw, variation, facts in zip(accepted, cleared_variations, score_facts):
                is_new = self._player_dict.add(fw.word, variation)
                word_obscure = is_obscure(fw.word)
                new_flags.append(is_new)
                obscure_flags.append(word_obscure)
                # Score the word into the running total (facts were captured above,
                # pre-clear); its points also list beside the word.
                points = self._scorer.score_word_rule(is_new=is_new, **facts)
                word_scores.append(points)
                # Single sink for every clear (interactive / batch / auto).
                L.log_30002(fw.word, fw.path, variation, is_new, word_obscure, points)
            self._moving_side_pane.add_cleared_words(
                cleared_words, new_flags, obscure_flags, word_scores)
            self._dictionary_count_rule(self._moving_side_pane, len(self._player_dict))
            self._refresh_score()
        # This clear may have filled the board (the last cell fossilized, or --
        # under remove -- an overlap-placement completed it); award the fill bonus.
        self._check_board_fill()
        return cleared_words

    # --- clear-action rules (game_screen.clear_action) ---------------------
    # Stage 4's cell fate for the accepted words. Both record the words the same
    # way (see _clear_paths); they differ only in what becomes of the cells. Each
    # returns the cells that FULLY left the board (for obstacle/mission tracking).
    def _rule_clear_remove(self, accepted):
        """Original: the consumed cells leave the board, partial-gram aware. Per
        cell, count letters eaten from the head (largest prefix any word took) and
        tail (largest suffix): a word's first cell gives up a suffix, its last a
        prefix, every middle cell the whole gram; wild / single-cell paths go
        whole. The leftover is the contiguous middle gram[head : n - tail] -- empty
        when the runs meet, so the cell clears. Batches naturally: WIN + GO over
        W ING O clears ING, while HI + GO leaves its middle N (see
        _apply_partial_clears)."""
        force_clear = set()           # cells consumed whole (middle / wild / 1-cell)
        eaten = {}                    # endpoint cell -> [head_eaten, tail_eaten]

        def eat_head(cell, j):
            slot = eaten.setdefault(cell, [0, 0])
            slot[0] = max(slot[0], j)

        def eat_tail(cell, k):
            slot = eaten.setdefault(cell, [0, 0])
            slot[1] = max(slot[1], k)

        for fw in accepted:
            last = len(fw.path) - 1
            for idx, (cell, seg) in enumerate(zip(fw.path, fw.segments)):
                gram = self._board.gram_at(*cell)
                if gram is None:
                    continue
                if gram.is_wild or last == 0 or (idx != 0 and idx != last):
                    force_clear.add(cell)        # whole gram consumed
                elif idx == 0:
                    eat_tail(cell, len(seg))     # word starts here: a suffix goes
                else:                            # idx == last
                    eat_head(cell, len(seg))     # word ends here: a prefix goes
        return self._apply_partial_clears(force_clear, eaten)

    def _rule_clear_fossilize(self, accepted):
        """Typewriter: every cell on each accepted word's path FOSSILIZES -- it
        stays on the board with its whole gram intact (no partial split, even
        under rule_gram_use_partial) but goes permanently dead: tracked in
        _fossilized_cells, tinted the fossil color, un-swappable, and skipped by
        the pathfinder (_collect_words) and the cursor. Nothing leaves the board,
        so no cell is reported cleared (obstacle/mission tracking is untouched)."""
        for fw in accepted:
            for cell in fw.path:
                if self._board.gram_at(*cell) is not None:
                    self._fossilize_cell(cell)
        return set()

    def _fossilize_cell(self, cell):
        """Freeze one cell: record it dead and tint it the fossil color in place."""
        self._fossilized_cells.add(cell)
        c = self._board.get_cell(*cell)
        if c is not None and c.square is not None:
            c.square.color = self.FOSSILIZED_CELL_COLOR

    def _apply_partial_clears(self, force_clear, eaten):
        """Clear the whole-gram cells outright, then resolve each partially-eaten
        endpoint cell: clear it if head + tail eat the whole gram, else re-letter
        it to the leftover middle run. Returns the set of cells fully cleared."""
        fully_cleared = set()
        for cell in force_clear:
            self._board.clear_cell(*cell)
            fully_cleared.add(cell)
        for cell, (head, tail) in eaten.items():
            if cell in force_clear:
                continue
            gram = self._board.gram_at(*cell)
            if gram is None:
                continue
            n = len(gram.text)
            if head + tail >= n:
                self._board.clear_cell(*cell)
                fully_cleared.add(cell)
            else:
                self._reletter_cell(*cell, gram.text[head:n - tail])
        return fully_cleared

    def _reletter_cell(self, x, y, text):
        """Re-render an occupied cell to its leftover letters after a partial-gram
        clear, then restore its resting color (it may have been tinted blue while
        placed or green while pending)."""
        self._board.relabel_cell(x, y, text)
        cell = self._board.get_cell(x, y)
        if cell is not None and cell.square is not None:
            cell.square.color = self._cell_resting_color((x, y))

    def _cell_resting_color(self, cell):
        """The fill a cell shows when no piece tint applies: its fossilized tint
        if it is dead, else its obstacle / mission tint if it is still one, else
        the plain settled color. Fossilized wins -- a fossilized cell is its
        permanent end state regardless of what it started as."""
        if cell in self._fossilized_cells:
            return self.FOSSILIZED_CELL_COLOR
        if cell in self._obstacle_cells:
            return self.OBSTACLE_CELL_COLOR
        if cell in self._mission_cells:
            return self.MISSION_CELL_COLOR
        return self.SETTLED_CELL_COLOR

    def _on_submit_word(self, typed):
        """Interactive submit (Enter or the Submit control). Dispatches to the
        active clear-timing rule, which either clears the word now or holds it for
        the phase-end batch; both show the most specific error on rejection."""
        word = typed.strip().upper()
        if not word:
            return
        L.log_30001(word)
        self._submit_clear_rule(word)

    def _reject_submission(self, word, messages):
        """Show why a submitted word was rejected. Under game_screen.reject_ghost
        = rule_reject_ghost_on, echo the word as a dim ghost above a CLEARED field
        (so corrective typing starts fresh, not appended to the failed attempt);
        under _off, leave the failed word in the field and just show the reason
        (original behavior)."""
        if self._reject_ghost:
            self._selecting_side_pane.reject(word, messages)
        else:
            self._selecting_side_pane.show_errors(messages)

    # --- clear-timing rules (game_screen.clear_timing) ---------------------
    # Paired per timing: a submit rule (what one submit does) and a phase-end
    # rule (what ending the phase does). See the registries in __init__.
    def _options_for(self, word):
        """The clearable FoundWord spellings of a submitted `word` (or None). The
        pipeline seam between word-finding strategies: adjacency modes read the
        pre-enumerated candidate map; constellation matches on demand against the
        whole board. Every submit path goes through here so both strategies share
        the disambiguation / clear / scoring machinery below."""
        if self._constellation:
            return self._constellation_options(word)
        return self._candidate_word_options.get(word)

    def _rule_submit_clears_now(self, word):
        """Clear-on-submit: if the word is a clearable candidate, resolve WHICH
        spelling (disambiguation rule) then clear it from the board and recompute
        against the smaller board; else show why not. (Original interactive
        behavior, now with the chooser seam.)"""
        options = self._options_for(word)
        if not options or not self._repeat_rule(word):
            self._reject_submission(word, self._submission_messages(word))
            return
        # Auto-pick returns the FoundWord to clear now; cycle opens the board
        # chooser and returns None, committing later via _commit_clear_now.
        chosen = self._disambiguation_rule(word, options, self._commit_clear_now)
        if chosen is not None:
            self._commit_clear_now(word, chosen)

    def _commit_clear_now(self, word, found):
        """Apply one resolved spelling in clear-on-submit mode: clear it, list it,
        recompute, and run the phase-end checks. Shared by the instant path (auto-
        pick / single spelling) and the chooser's confirm."""
        # Capture newness before _clear_paths adds the word to the player's
        # dictionary, so the entry pane can list it green.
        is_new = not self._player_dict.contains(word)
        # Preview the word's points for the entry list BEFORE _clear_paths runs
        # (which is where they're really scored into the total) -- the facts must
        # be read pre-clear, and the same pure rule guarantees the same number.
        points = self._scorer.word_points_rule(is_new=is_new, **self._word_score_facts(found))
        self._clear_paths([found])
        # Constellation turnover: refill or leave empty the cells this word vacated
        # (game_screen.constellation_turnover). Runs before the recompute/victory
        # checks below so a replenished board isn't read as empty.
        if self._constellation:
            self._constellation_turnover_rule(found.path)
        self._words_submitted_this_select += 1
        self._selecting_side_pane.accept_word(word, is_new, is_obscure(word), points)
        self._dictionary_count_rule(self._selecting_side_pane, len(self._player_dict))
        self._recompute_candidates()
        # This clear may have won the game immediately (e.g. it removed the last
        # obstacle/mission cell); if so, stop here rather than ending selection.
        if self._check_victory():
            return
        # One-word-per-select ends the phase right after this first clear,
        # regardless of adjacency (game_screen.select_word_limit).
        if self._select_word_limit_rule():
            self._end_selection()
            return
        # Leave SELECT once the placed piece is no longer adjacent to the board --
        # its remaining cells were consumed or stranded -- mirroring the adjacency
        # gate in _begin_selection. Keyed on adjacency, not the candidate count,
        # so the transition never reveals whether a word is still formable.
        # Constellation has no placed piece and the board never shrinks under the
        # typist, so this end-check would fire after every word; there the player
        # stays in SELECT (typing word after word) until they press Next.
        if not self._constellation and not self._piece_touches_existing(self._move_placed):
            self._end_selection()

    def _rule_submit_defers(self, word):
        """Clear-at-phase-end: hold the word for the phase-end batch instead of
        clearing now, tinting its cells green. The board never shrinks mid-phase,
        so cells reuse across words (overlaps); a word can be held several times
        as long as each takes a distinct path (repeats). Nothing clears until the
        phase ends (see _rule_endphase_clear_pending)."""
        options = self._options_for(word)
        if not options or not self._repeat_rule(word):
            self._reject_submission(word, self._submission_messages(word))
            return
        # Only spellings not already held this phase are offerable -- the chooser
        # (and auto-pick) resolve among these, so a re-submit takes a fresh path.
        fresh = self._unused_pending_paths(word, options)
        if not fresh:
            # A candidate, but every distinct way to spell it here is already
            # held -- a batch-mode-specific rejection.
            self._reject_submission(word, [self._no_more_paths_error(word)])
            return
        chosen = self._disambiguation_rule(word, fresh, self._commit_defer)
        if chosen is not None:
            self._commit_defer(word, chosen)

    def _commit_defer(self, word, found):
        """Hold one resolved spelling for the phase-end batch: append it, tint its
        cells, list it. Shared by the instant path and the chooser's confirm."""
        is_new = not self._player_dict.contains(word)
        # Preview the word's points for the entry list. Deferred words score in
        # the phase-end batch (_clear_paths); the board is unchanged until then,
        # so these facts and the same pure rule yield the batch's number.
        points = self._scorer.word_points_rule(is_new=is_new, **self._word_score_facts(found))
        self._pending.append(found)
        self._words_submitted_this_select += 1
        self._highlight_pending_cells(found.path)
        self._selecting_side_pane.accept_word(word, is_new, is_obscure(word), points)
        # One-word-per-select ends the phase now; _end_selection clears the single
        # held word on the way out (game_screen.select_word_limit).
        if self._select_word_limit_rule():
            self._end_selection()

    # --- disambiguation rules (game_screen.clear_disambiguation) -----------
    # Resolve WHICH spelling a submitted word clears when several paths exist.
    # Signature (word, options, on_confirm) -> FoundWord | None: return a chosen
    # FoundWord to commit now, or None having deferred to the chooser, which will
    # call on_confirm(word, found) once the player confirms.
    def _rule_disambig_auto_pick(self, word, options, on_confirm):
        """Original: silently keep the fewest-cell spelling (ties at random), no
        player choice. on_confirm is unused -- the pick commits immediately."""
        return self._fewest_cell_word(options)

    def _rule_disambig_cycle_two_or_more_choices(self, word, options, on_confirm):
        """Open the board chooser only when 2+ spellings exist; a lone spelling
        clears instantly (no needless prompt) -- the original ambiguity chooser.
        Returns None when the chooser opens (commit later via on_confirm), else
        the FoundWord to clear now."""
        return self._open_cycle_chooser(word, options, on_confirm, min_choices=2)

    def _rule_disambig_cycle_one_or_more_choices(self, word, options, on_confirm):
        """Open the board chooser for EVERY clearable word, a lone spelling
        included -- so every valid submit gets the blue-path preview + an explicit
        confirm (a second word_submit). Returns None (the choice commits later via
        on_confirm)."""
        return self._open_cycle_chooser(word, options, on_confirm, min_choices=1)

    def _open_cycle_chooser(self, word, options, on_confirm, min_choices):
        """Shared entry for the rule_disambig_cycle_* rules: open the board
        chooser once the candidate count reaches min_choices, else clear the lone
        spelling instantly. min_choices=1 always opens (options is never empty
        here); min_choices=2 opens only for genuine ambiguity."""
        if len(options) < min_choices:
            return options[0]
        self._begin_disambiguation(word, options, on_confirm)
        return None

    # --- disambiguation-cancel rules (game_screen.disambig_cancel) ---------
    def _rule_disambig_cancel_on(self):
        """word_clear backs out of the chooser, restoring the typed word."""
        self._cancel_disambiguation()

    def _rule_disambig_cancel_off(self):
        """word_clear is inert while the chooser is open -- the player must commit
        to one candidate once a valid word is submitted."""
        pass

    # --- disambiguation chooser (the cycle rules) --------------------------
    def _disambiguating(self):
        """Whether the 'select which one' chooser is currently open."""
        return bool(self._disambig_options)

    def _begin_disambiguation(self, word, options, on_confirm):
        """Open the chooser: order the candidates deterministically (fewest-cell
        first, then by path -- never shuffle, so the same cycle keys re-select the
        same path on replay), draw them, and show the prompt. The typed word is
        left in the field so a cancel returns to it."""
        ordered = sorted(options, key=lambda fw: (len(fw.path), fw.path))
        self._disambig_word = word
        self._disambig_options = ordered
        self._disambig_index = 0
        self._disambig_commit = on_confirm
        self._selecting_side_pane.clear_errors()
        # The submit was valid, so any prior rejection ghost has served its
        # purpose -- drop it before the chooser prompt takes the slot.
        self._selecting_side_pane.clear_ghost()
        # A lone path is a confirm, not a choice -- word it accordingly.
        prompt = (
            "disambig_confirm_prompt" if len(ordered) == 1 else "disambig_prompt"
        )
        self._selecting_side_pane.show_prompt(get_string(prompt))
        self._render_disambiguation()

    def _render_disambiguation(self):
        """Redraw the candidate polylines with the current highlight."""
        paths = [
            [self._board.cell_center(x, y) for (x, y) in fw.path]
            for fw in self._disambig_options
        ]
        self._disambig_lines.show(paths, self._disambig_index)

    def _cycle_disambiguation(self, delta):
        """Move the highlight to the next/previous candidate, wrapping around."""
        n = len(self._disambig_options)
        self._disambig_index = (self._disambig_index + delta) % n
        self._render_disambiguation()

    def _confirm_disambiguation(self):
        """Commit the highlighted candidate: log the choice, close the chooser,
        then run the timing-specific commit (clear-now or defer)."""
        word = self._disambig_word
        found = self._disambig_options[self._disambig_index]
        index, total = self._disambig_index, len(self._disambig_options)
        commit = self._disambig_commit
        L.log_30004(word, found.path, index, total)
        self._end_disambiguation()
        commit(word, found)

    def _cancel_disambiguation(self):
        """Back out without clearing: close the chooser, leaving the typed word in
        place for a re-submit or edit."""
        self._end_disambiguation()

    def _backout_disambiguation(self):
        """A typing / edit / Escape gesture while the chooser is open backs out of
        it, per game_screen.disambig_cancel. Returns True if the chooser actually
        closed (cancel enabled), so the caller may then let that same gesture edit
        the field (a letter appends, Backspace deletes) -- the player flows
        straight from 'confirm this word?' into hunting a different one."""
        if not self._disambig_cancel_enabled:
            return False
        self._cancel_disambiguation()
        return True

    def _end_disambiguation(self):
        """Tear down chooser state and its overlay + prompt."""
        self._disambig_options = []
        self._disambig_index = 0
        self._disambig_word = None
        self._disambig_commit = None
        self._disambig_lines.clear()
        self._selecting_side_pane.hide_prompt()

    def _rule_endphase_clear_none(self):
        """Clear-on-submit: phase end clears nothing extra (each word already
        cleared as it was submitted)."""
        pass

    def _rule_endphase_clear_pending(self):
        """Clear-at-phase-end: clear the whole held batch together when the phase
        ends. Overlapping cells (shared across held words) clear once; each held
        word still records its own gram grouping (see _encode_variation)."""
        if self._pending:
            self._clear_paths(self._pending)
        self._pending = []

    # --- select word-limit rules (game_screen.select_word_limit) -----------
    # Consulted after each accepted word in the interactive SELECT phase: return
    # True to end the phase now (back to MOVING), False to stay open for more.
    def _rule_unlimited_words(self):
        """Stay in SELECT after an accepted word; the phase ends only on Next
        piece or (clear-on-submit) when the placed piece is stranded. Original."""
        return False

    def _rule_one_word_per_select(self):
        """End the SELECT phase as soon as one word is accepted."""
        return True

    def _unused_pending_paths(self, word, options):
        """Every clearable FoundWord for `word` NOT already held this phase.
        Spellings are distinguished by path AND segments, so two different partial
        bites of the same cells (e.g. the same word taking a different prefix /
        suffix) each count as their own selection. The disambiguation rule then
        picks among these (auto-pick keeps the fewest-cell one; cycle offers them
        all)."""
        def key(fw):
            return (tuple(fw.path), tuple(fw.segments))
        used = {key(fw) for fw in self._pending if fw.word == word}
        return [fw for fw in options if key(fw) not in used]

    def _unused_pending_path(self, word, options):
        """The single fewest-cell spelling of `word` not already held, or None
        when every distinct spelling is taken. Retained for callers that want the
        old auto-pick directly; the submit path now goes through
        _unused_pending_paths + the disambiguation rule."""
        fresh = self._unused_pending_paths(word, options)
        if not fresh:
            return None
        return self._fewest_cell_word(fresh)

    def _no_more_paths_error(self, word):
        """The batch-mode rejection when a word is on the board but every way to
        spell it here is already held: distinct wording by how many ways exist."""
        total = len(self._options_for(word) or [])
        reason = "already_selected_one_way" if total <= 1 else "every_way_selected"
        L.log_30003(word, reason)
        return get_string(f"err_{reason}")

    def _highlight_pending_cells(self, path):
        """Tint a held word's cells light green so the player sees what the
        phase-end batch will clear. All cells go green -- including starting
        obstacle / mission cells on the path -- since the batch clears them too."""
        for (x, y) in path:
            cell = self._board.get_cell(x, y)
            if cell is not None and cell.square is not None:
                cell.square.color = self.PENDING_WORD_CELL_COLOR

    def _submission_error(self, word):
        """The single most specific reason `word` can't be cleared right now,
        walking the pipeline from the typed word inward: a non-word, a word not
        on the board at all, a board word too short to clear, a board word that
        doesn't touch the placed piece, one that touches no fossilized cell (when
        the fossil requirement is on), or one already cleared this game. Logs the
        stable reason key, then returns the localized message string."""
        if self._constellation:
            return self._constellation_submission_error(word)
        if not is_word(word):
            reason = "not_in_dictionary"
        elif word not in self._board_words_any:
            reason = "not_on_board"
        elif word not in self._length_ok_words:
            reason = "too_short"
        elif word not in self._candidate_words:
            # A word that clears every stage-2 filter but the fossil requirement
            # gets its own reason; anything else here failed placement/nucleation.
            reason = "not_fossil" if word in self._pre_fossil_words else "not_involved"
        else:
            reason = "already_cleared"
        L.log_30003(word, reason)
        return get_string(f"err_{reason}")

    def _submission_messages(self, word):
        """The error line for a rejected `word`, plus -- only when it's simply not
        a dictionary word -- a 'did you mean?' line of close spellings underneath.
        Shown together in the selecting pane's multiline error area."""
        messages = [self._submission_error(word)]
        if not is_word(word):
            suggestions = self._spell_suggest_rule(word)
            if suggestions:
                joined = ", ".join(suggestions)
                messages.append(get_string("did_you_mean", words=joined))
        return messages

    # --- Player word-piece rules (game_screen.player_word_piece) -----------
    # Clicking a cleared word in the right pane (MOVING) swaps the live piece for
    # a single-cell unimo whose one gram is that whole word, a normal player
    # piece in every other respect (overlap rules, placement, word formation).
    # The displaced pool piece is set aside, not consumed, and returns as the
    # next piece once the word-piece is placed (see _advance_piece). Only one
    # swap per piece: a word-piece can't be re-swapped until it's placed and a
    # fresh pool piece appears.

    def _rule_player_word_piece_enabled(self, x, y):
        """Feature on: try to swap the live piece for the clicked word. Returns
        True if a swap happened so the click is consumed."""
        return self._swap_to_word_piece(x, y)

    def _rule_player_word_piece_disabled(self, x, y):
        """Feature off: right-pane clicks do nothing during MOVING."""
        return False

    def _swap_to_word_piece(self, x, y):
        """Replace the live pool piece with a single-cell word-piece for the word
        clicked in the right pane. No-op (returns False) unless a normal pool
        piece is live, unplaced, and the click landed on a non-blank word row."""
        # Already holding a word-piece (override set) -> one swap per piece only.
        if self._override_piece is not None:
            return False
        pool_piece = self._piece_pool.current_piece()
        if pool_piece.placed:
            return False
        word = self._moving_side_pane.word_at(x, y)
        if not word:
            return False
        # Set the pool piece aside: clear the cells it hover-hides and hide it.
        # It stays at its pool index, so _advance_piece restores it next.
        self._clear_hover_visibility()
        pool_piece.set_visible(False)
        # Build the word-piece: the active grid's unimo, its single gram forced to
        # the clicked word. Same cell size / batch / tint as a normal pool piece.
        # dedup_grams=False: a player-chosen word bypasses the no-duplicate-multigram
        # rule (it's a deliberate fixed word, never re-rolled).
        word_piece = self._piece_class(
            self._unimo_type, self._cell_size, self._piece_batch, visible=False,
            gram_pick_rule=lambda count: [Gram(word)],
            cell_color=self.ACTIVE_PIECE_CELL_COLOR,
            dedup_grams=False,
        )
        self._override_piece = word_piece
        self._spawn_piece(word_piece)
        word_piece.set_visible(True)
        self._update_hover_visibility()
        return True

    def _advance_piece(self):
        """Spawn the next piece and resume play (or do nothing if the pool is
        exhausted). Checks victory first, so a win is caught before the next
        piece spawns (rule_victory_grid_empty's 'before spawning' point)."""
        if self._check_victory():
            return
        # A just-placed word-piece restores the pool piece set aside for it,
        # rather than consuming the next pooled piece (the swap left the pool
        # index untouched, so current_piece() is still that set-aside piece).
        if self._override_piece is not None:
            self._override_piece = None
            piece = self._piece_pool.current_piece()
            self._spawn_piece(piece)
            piece.set_visible(True)
            self._update_hover_visibility()
            return
        next_piece = self._piece_pool.advance()
        if next_piece:
            self._spawn_piece(next_piece)
            next_piece.set_visible(True)
            self._update_hover_visibility()

    def _end_selection(self):
        """Leave the SELECTING phase (the Next piece control, or once the piece
        is no longer adjacent to the board) and spawn the next piece. First runs
        the phase-end clear rule -- in batch mode this clears the whole held
        selection together (it may win the game, caught by _advance_piece) -- then
        settles the placed piece's remaining cells from light blue back to the
        board color."""
        self._endphase_clear_rule()
        self._settle_placed_cells()
        self._set_phase(Phase.MOVING)
        self._moving_mode.advance()
