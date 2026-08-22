"""Selection / word-clearing pipeline extracted from GameScreen: begin_selection, recompute_candidates, clear_paths and the clear-action / clear-timing / disambiguation-chooser / word-limit / player-word-piece rules, plus submission error wording, scoring glue and advance/end-selection. A mixin -- every method runs with GameScreen's self; the __init__ registries resolve these by name. Kept out of game_screen.py to bound its size (see AGENTS.md)."""

from collections import Counter

from views.game_phase import Phase
from models.gram import Gram
from models.word_dictionary import (
    is_word, is_prefix, is_obscure, select_maximal_paths, all_words)
from config import select_rule, get_color, get_string, CONFIG
import log_codes as L
from source import rand


class SelectionMixin:
    # Default so _word_score_facts' stem-cell count resolves to 0 on bare __new__
    # test instances (real games set the instance attribute in __init__ /
    # _start_new_game). Only MOVING_PLANT populates it. See _rule_formation_plant.
    _stem_cells = frozenset()

    # The belt widget, when game_screen.idea_belt is on (GameScreen caches the
    # pane's one). None here so the match rule below is safe on bare __new__ test
    # instances and in every belt-off game.
    _idea_belt = None

    # --- idea-belt match rules (idea_belt.match) ---------------------------
    # What a cleared word does to the right pane's picture conveyor. Called from
    # every clear sink (_clear_paths, _shooting_submit) with the words that just
    # cleared; returns the bonus points awarded, so a caller can tell whether the
    # score readout needs a refresh.
    def _rule_idea_match_ignore(self, words):
        """The belt is a pure prompt: a cleared word leaves every picture turning
        and pays nothing. The original behavior -- the board and the belt never
        knew about each other."""
        return 0

    def _rule_idea_match_clear_and_bonus(self, words):
        """A cleared word the belt was showing takes its picture off the conveyor
        and pays scoring.idea_belt_match_bonus.

        This is the belt's only feedback loop: the young player sees the picture
        they just spelled disappear, which turns the conveyor from a list of
        suggestions into a set of targets. Paid once per matching word (see
        Scorer.idea_belt_match_bonus_rule) and only on the FIRST clear of it --
        IdeaPool.clear_word reports nothing the second time, so a word cleared
        again pays nothing again."""
        points = 0
        if self._idea_belt is not None:
            for word in words:
                struck = self._idea_belt.clear_word(word)
                if struck:
                    award = self._scorer.idea_belt_match_bonus_rule()
                    points = points + award
                    L.log_30012(word, struck, award,
                                self._idea_belt.active_count())
        return points

    # Default so every clear path works on bare __new__ test instances, which never
    # run GameScreen.__init__'s select_rule wiring. The shipped rule, not the
    # ignore one -- with no belt built (_idea_belt None) it is a no-op anyway, and
    # a test that installs a belt then gets the real behavior.
    _idea_match_rule = _rule_idea_match_clear_and_bonus

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
            # MOVING_PLANT: cells of this word that are stem cells (>0 => a plant word
            # grown off the stem, scored x scoring.plant_word_multiplier). Always 0 in
            # other modes (_stem_cells is empty), so the multiplier stays inert there.
            "stem_cells": sum(1 for c in path if c in self._stem_cells),
        }

    def _record_cleared_word(self, word, variation, is_new, is_obscure, points):
        """Append one cleared word to this game's ordered record
        (_cleared_word_records), the list the endgame typing bonus replays. Each
        entry keeps the gram grouping the word was cleared with THIS game
        (`variation`), so the endgame re-renders the cells the player actually
        built -- not whatever other groupings the lifetime dictionary knows -- plus
        the in-play `points` it earned and its new / obscure flags for coloring.

        DE-DUPLICATED by word: a word cleared twice (or cleared again with a
        different grouping) is recorded once, the FIRST clear winning, so the
        endgame never asks the player to type the same word twice. Called from
        every clear sink (_clear_paths, _shooting_submit)."""
        # A real game builds the list per game (see GameScreen.reset); bare
        # __new__ test instances never run that, so start one on first use rather
        # than making callers wire it up.
        if getattr(self, "_cleared_word_records", None) is None:
            self._cleared_word_records = []
        already = False
        for record in self._cleared_word_records:
            if record["word"] == word:
                already = True
        if not already:
            self._cleared_word_records.append({
                "word": word,
                "variation": variation,
                "is_new": is_new,
                "is_obscure": is_obscure,
                "points": points,
            })

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
        # Cell-health seam (game_screen.cell_health), interposed BEFORE the clear-
        # action: it damages every health-carrying cell the accepted words ran
        # through, holds the words whose targets survived (their cells fossilize
        # as a attacker trail) and returns the rest for the normal clear-action,
        # plus the cells that left with a destroyed target. Under
        # rule_cell_health_off it hands `accepted` straight back and releases
        # nothing, so this is the original single line. See CellHealthMixin.
        clearable, released = self._cell_health_rule(accepted)
        fully_cleared = self._clear_action_rule(clearable) | released
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
                # pre-clear); its points also list beside the word. The total/log
                # use the int total; the pane gets the display value (a "+A +B +C"
                # breakdown or the same int, per scoring.word_score_display).
                points = self._scorer.score_word_rule(is_new=is_new, **facts)
                word_scores.append(self._scorer.word_score_display_rule(is_new=is_new, **facts))
                # Keep the word (with THIS game's grouping) for the endgame typing
                # bonus; a repeat word is ignored there.
                self._record_cleared_word(fw.word, variation, is_new, word_obscure, points)
                # Single sink for every clear (interactive / batch / auto).
                L.log_30002(fw.word, fw.path, variation, is_new, word_obscure, points)
            # Idea belt (idea_belt.match): any of these words the belt was
            # prompting with a picture comes off it now, paying the match bonus
            # into the same running total. Placed before the score refresh below
            # so the readout shows the bonus in the same frame as the words.
            self._idea_match_rule(cleared_words)
            self._moving_side_pane.add_cleared_words(
                cleared_words, new_flags, obscure_flags, word_scores)
            self._dictionary_count_rule(self._moving_side_pane, len(self._player_dict))
            self._refresh_score()
        # This clear may have filled the board (the last cell fossilized, or --
        # under remove -- an overlap-placement completed it); award the fill bonus.
        self._check_board_fill()
        # Any clear changes the board, so the debug panel's formable-word sample
        # ("Board words") is stale; recomputed lazily on the next update tick while
        # the panel is visible (see _update_debug_word_samples). Set here -- the
        # single sink for every clear path (auto-select, clear-on-submit, phase-end
        # batch) -- so no call site can forget it. Cheap: a hidden panel ignores it.
        self._dbg_words_dirty = True
        return cleared_words

    # --- clear-action rules (game_screen.clear_action) ---------------------
    # Stage 4's cell fate for the accepted words. Both record the words the same
    # way (see _clear_paths); they differ only in what becomes of the cells. Each
    # returns the cells that FULLY left the board (for obstacle/mission tracking).
    def _rule_remove_cells(self, accepted):
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

        held = set()                  # cells the attacker-hold rule kept on the board
        for fw in accepted:
            last = len(fw.path) - 1
            for idx, (cell, seg) in enumerate(zip(fw.path, fw.segments)):
                gram = self._board.gram_at(*cell)
                if gram is None:
                    continue
                # Cells already committed to a live obstacle / mission are skipped
                # under rule_attacker_cells_held: a later word that reuses an
                # attacker fossil but misses its target must not carry the attack
                # off the board with it. A no-op under the consumable rule (and
                # whenever cell health is off, since nothing is ever committed).
                if self._attacker_hold_rule(cell):
                    held.add(cell)
                    continue
                if gram.is_wild or last == 0 or (idx != 0 and idx != last):
                    force_clear.add(cell)        # whole gram consumed
                elif idx == 0:
                    eat_tail(cell, len(seg))     # word starts here: a suffix goes
                else:                            # idx == last
                    eat_head(cell, len(seg))     # word ends here: a prefix goes
        if held:
            L.log_30011(sorted(held))
        return self._apply_partial_clears(force_clear, eaten)

    def _rule_fossilize_cells(self, accepted):
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

    def _rule_clear_plant(self, accepted):
        """MOVING_PLANT: a cleared word's fate depends on whether it grew off the
        stem. A PLANT WORD -- its path touches a green stem cell (the root suffix) --
        becomes a permanent BRANCH: its fresh (non-stem) prefix cells FOSSILIZE green
        in place, the stem cells being fossil already. A word that touches NO stem
        cell is an ordinary REFRESH word (e.g. CAT): its cells are REMOVED and each
        schedules a faded-in fresh gram (the same replenish path constellation uses),
        so the player can fish the board for new letters toward more plant words.
        Returns the cells that fully left the board (the refresh cells) for
        obstacle/mission tracking; a branch fossilizes in place, clearing nothing."""
        fully_cleared = set()
        for fw in accepted:
            touches_stem = any(cell in self._stem_cells for cell in fw.path)
            if touches_stem:
                for cell in fw.path:
                    if cell not in self._stem_cells and self._board.gram_at(*cell) is not None:
                        self._fossilize_cell(cell)
                L.log_30007("branch", fw.word, fw.path)
            else:
                for cell in fw.path:
                    if self._board.gram_at(*cell) is not None:
                        self._board.clear_cell(*cell)
                        fully_cleared.add(cell)
                        self._schedule_replenish(cell[0], cell[1])
                L.log_30007("refresh", fw.word, fw.path)
        return fully_cleared

    def _rule_clear_none(self, accepted):
        """No-op clear-action: the accepted words' cells stay on the board untouched.
        Used by MOVING_BOTANICAL, which PLACES cells on submit and records/scores the
        grown word through _clear_paths without removing anything. Returns an empty
        fully-cleared set (nothing left the board)."""
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
        # Botanical (MOVING_BOTANICAL): a word grows off the stem as leaf cells rather
        # than clearing existing cells, so it takes its own placement path and never
        # touches the SELECT clear pipeline / candidate recompute below.
        if self._botanical:
            L.log_30001(word)
            self._botanical_submit(word)
            return
        # Single-phase (MOVING_AND_SELECTING): no _begin_selection ran to snapshot
        # the board's candidates, and the board may have changed via swaps since the
        # last submit, so recompute now at submit time. Constellation matches on
        # demand and takes the cheap clear-only branch, so this is near-free there.
        if self._single_phase:
            self._recompute_candidates()
        L.log_30001(word)
        self._submit_clear_rule(word)

    def _reject_submission(self, word, messages):
        """Show why a submitted word was rejected. Under game_screen.reject_ghost
        = rule_reject_ghost_on, echo the word as a dim ghost above a CLEARED field
        (so corrective typing starts fresh, not appended to the failed attempt);
        under _off, leave the failed word in the field and just show the reason
        (original behavior)."""
        # _last_reject_reason is the stable key the error functions just logged;
        # the pane uses it to pick an error icon under game_screen.error_display =
        # rule_error_icon (ignored under the text default).
        reason = self._last_reject_reason
        # For a missing-letter reject, which of the typed letters don't exist on the
        # board at all (reddened in the ghost). Only meaningful with the ghost, and
        # only for that sub-class -- a gram-mismatch reject has no absent letters.
        missing = (self._missing_letters(word)
                   if reason == "not_on_board_missing_letter" else None)
        if self._reject_ghost:
            self._selecting_side_pane.reject(word, messages, reason, missing)
        else:
            self._selecting_side_pane.show_errors(messages, reason)

    # --- not-on-board missing-letter hint (game_screen.missing_letter_highlight) -
    _VOWELS = set("AEIOU")

    def _board_letter_counts(self):
        """The multiset {letter -> how many exist} across ALL the board's occupied
        grams (a wild cell contributes one of every vowel). Supply-only: it counts
        letters, NOT gram boundaries or tiling. Superseded by the word-restricted
        _board_letter_counts_for_word for the shortage check (this over-counts a
        letter that lives only in grams that can't tile the word -- SPONSOR's 2nd O,
        carried by SHO / TION / OND, none of them a substring of SPONSOR); kept as
        the plain board-wide census in case a caller wants the unrestricted count."""
        counts = Counter()
        for cell in self._board.occupied_cells():
            gram = self._board.gram_at(*cell)
            if gram is None:
                continue
            if gram.is_wild:
                counts.update(self._VOWELS)      # a wild can be any one vowel
            else:
                counts.update(gram.text)
        return counts

    def _board_letter_counts_for_word(self, word):
        """Like _board_letter_counts, but restricted to grams that could actually sit
        inside `word` -- i.e. whose text is a substring of it (a wild counts toward any
        vowel that appears in the word). Any whole-gram tiling of the word partitions it
        into contiguous grams, each necessarily a substring of the word AND present on
        the board, so this restricted supply -- not the board-wide census -- is the true
        upper bound on how many of each letter a tiling can place. A letter locked solely
        inside non-substring grams (SPONSOR's 2nd O, alive only in SHO / TION / OND)
        contributes nothing here, exposing the shortage the board-wide count hides."""
        word = word.upper()
        word_vowels = self._VOWELS.intersection(word)
        counts = Counter()
        for cell in self._board.occupied_cells():
            gram = self._board.gram_at(*cell)
            if gram is None:
                continue
            if gram.is_wild:
                counts.update(word_vowels)       # a wild can be any vowel the word uses
            elif gram.text in word:              # only substring grams can tile into word
                counts.update(gram.text)
        return counts

    def _excess_letters(self, word, uncoverable=None):
        """One bool per letter of `word`: True where that OCCURRENCE outruns the board's
        PLACEABLE supply of that letter -- i.e. the word needs more of it than any tiling
        could ever lay down. The first N copies of a letter (N = placeable supply) read as
        present; every copy past N is flagged. Generalizes 'letter exists nowhere' (supply
        0 flags every copy) to 'not ENOUGH placeable copies' -- RUTHLESS's 2nd S when the
        board has one S, and SPONSOR's 2nd O when the only spare O's are trapped in grams
        (SHO / TION / OND) that can't tile into SPONSOR. Uses the word-restricted supply,
        not the board-wide census, so those trapped copies don't mask the shortage. Drives
        both the reason split and the ghost highlight, so they agree.

        `uncoverable` (the _uncoverable_flags of the same word) makes the scarce supply
        spend itself POSITION-AWARE: a position no gram can cover is already flagged by
        that signal, so it neither claims a copy of the letter nor gets an excess flag
        here. Without it the supply is handed out blindly left-to-right and the surplus
        lands on the LAST occurrence even when that one is the placeable one -- DIAGONAL
        on a board whose only A is inside NAL reddened the A of NAL (the gram the player
        was building around) instead of the unreachable A of "AGO". Pass None to get the
        original position-blind allocation."""
        avail = self._board_letter_counts_for_word(word)
        used = Counter()
        flags = []
        for i, ch in enumerate(word.upper()):
            if uncoverable is not None and uncoverable[i]:
                flags.append(False)   # already flagged; don't spend supply on a dead slot
                continue
            used[ch] += 1
            flags.append(used[ch] > avail[ch])
        return flags

    def _placeable_gram_texts(self):
        """The set of gram texts the board can lay down, plus a flag for whether any
        wild is present. Mirrors _board_letter_counts' supply view (all occupied
        cells; a wild stands in for any one vowel) but keeps whole-gram texts rather
        than loose letters, so _uncoverable_flags can ask WHERE a gram could sit."""
        texts = set()
        wild_vowels = False
        for cell in self._board.occupied_cells():
            gram = self._board.gram_at(*cell)
            if gram is None:
                continue
            if gram.is_wild:
                wild_vowels = True
            else:
                texts.add(gram.text)
        return texts, wild_vowels

    def _uncoverable_flags(self, word):
        """One bool per letter of `word`: True where NO placeable board gram can sit
        over that position, so the letter can't be tiled there no matter how the rest
        is arranged. A tighter form of _excess_letters: a letter absent from every
        gram (supply 0) is uncoverable everywhere, but so is a letter that lives ONLY
        inside grams that never appear in `word` -- TROGLODYTE's G, carried only by
        GE / GH when the word contains neither substring. A wild covers any single
        vowel position. Purely local (per-position), so a letter that IS coverable
        somewhere but still won't tile globally stays unflagged (that's gram-mismatch,
        not a missing letter)."""
        word = word.upper()
        texts, wild_vowels = self._placeable_gram_texts()
        covered = [False] * len(word)
        for gram in texts:
            start = word.find(gram)
            while start != -1:
                for k in range(start, start + len(gram)):
                    covered[k] = True
                start = word.find(gram, start + 1)
        return [not covered[i] and not (wild_vowels and ch in self._VOWELS)
                for i, ch in enumerate(word)]

    def _unavailable_letters(self, word):
        """Per-letter flags unioning the two provably-unspellable signals: over-demand
        (needs more copies of a letter than the board holds -- RUTHLESS's 2nd S) and
        uncoverable (no gram carrying the letter can sit at that position -- TROGLODYTE's
        G). Both are necessary conditions any real tiling must meet, so a flag is a hard
        'this letter can't go here', and a fully-tileable word flags nothing. Drives both
        the reason split and the ghost highlight, so the two always agree.

        Uncoverable is computed FIRST and fed to the over-demand pass, so the board's
        scarce copies of a letter are spent on the positions a gram can actually cover
        and the surplus flag lands on a position that was doomed anyway. This never
        changes whether ANY flag is set (an uncoverable position is itself a flag), so
        the reason split below is unaffected -- only WHICH letters redden."""
        uncoverable = self._uncoverable_flags(word)
        excess = self._excess_letters(word, uncoverable)
        return [e or u for e, u in zip(excess, uncoverable)]

    def _missing_letters(self, word):
        """The per-letter unavailable-letter flags for the ghost highlight, or None when
        the highlight rule is off (so the pane draws the ghost plain)."""
        if not self._missing_letter_highlight:
            return None
        return self._unavailable_letters(word)

    def _not_on_board_reason(self, word):
        """Split a not-on-board rejection into its three sub-classes, so each can get
        its own message / error icon:
          not_on_board_missing_letter -- some letter can't be placed: the board has
              too few copies of it, OR it exists only inside grams that don't fit the
              word (so it's effectively absent here). Provably unspellable, and the
              blocking letters get reddened in the ghost.
          not_on_board_needs_rearrange -- every letter's here AND the board's whole
              grams DO tile the word (an arrangement-independent assembly exists), but
              no physically-adjacent path spells it. The right pieces are on the board,
              just not next to each other -- moving them together would spell it. Only
              reachable in adjacency modes: the constellation path asks this only when
              no assembly exists, so there it always falls through to gram-mismatch.
          not_on_board_gram_mismatch  -- every letter can be placed somewhere, but the
              board's whole grams don't divide to spell it at all (right letters, wrong
              pieces) -- no rearrangement helps. (Whole-gram basis: a word spellable
              only via partial-gram eating still reads as gram-mismatch here.)
        Shares _unavailable_letters with the highlight, so those two always agree."""
        if any(self._unavailable_letters(word)):
            return "not_on_board_missing_letter"
        if self._constellation_match(word, 1):
            return "not_on_board_needs_rearrange"
        return "not_on_board_gram_mismatch"

    # --- clear-timing rules (game_screen.clear_timing) ---------------------
    # Paired per timing: a submit rule (what one submit does) and a phase-end
    # rule (what ending the phase does). See the registries in __init__.
    def _force_single_phase_clear_timing(self):
        """Single-phase (MOVING_AND_SELECTING) has no phase boundary, so the
        clear-at-phase-end batch would never flush: submitted words would tint
        green forever and never clear or list. Deferring only makes sense with a
        phase end, so single-phase always clears on submit regardless of the
        configured clear_timing -- a mode invariant, not a player-tunable knob.
        Applied over the resolved clear-timing rules in __init__; a no-op in
        two-phase, so the player's clear_timing choice stands there."""
        if self._single_phase:
            self._submit_clear_rule = self._rule_submit_clears_now
            self._endphase_clear_rule = self._rule_endphase_clear_none

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
        display = self._scorer.word_score_display_rule(is_new=is_new, **self._word_score_facts(found))
        self._clear_paths([found])
        # Constellation turnover: refill or leave empty the cells this word vacated
        # (game_screen.constellation_turnover). Runs before the recompute/victory
        # checks below so a replenished board isn't read as empty.
        if self._constellation:
            self._constellation_turnover_rule(found.path)
        self._words_submitted_this_select += 1
        self._selecting_side_pane.accept_word(word, is_new, is_obscure(word), display)
        self._dictionary_count_rule(self._selecting_side_pane, len(self._player_dict))
        self._recompute_candidates()
        # This clear may have won the game immediately (e.g. it removed the last
        # obstacle/mission cell); if so, stop here rather than ending selection.
        if self._check_victory():
            return
        # Constellation auto-end (game_screen.constellation_auto_end): if the board
        # can no longer spell any word, finish the game. After the victory check
        # (a win outranks a plain finish) and after the recompute/turnover above,
        # so it reads the settled board. Off by default and inert in every other
        # mode; the rule ends the game itself and returns True when it fires.
        if self._constellation and self._constellation_auto_end_rule():
            return
        # Omniswap auto-end (game_screen.omniswap_auto_end): mirror the constellation
        # check for the swappable-gram board -- if the remaining swappable grams can
        # no longer spell any submittable word, finish rather than let the player run
        # the clock down. Off by default and inert in every other mode.
        if self._omniswap and self._omniswap_auto_end_rule():
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
        display = self._scorer.word_score_display_rule(is_new=is_new, **self._word_score_facts(found))
        self._pending.append(found)
        self._words_submitted_this_select += 1
        self._highlight_pending_cells(found.path)
        self._selecting_side_pane.accept_word(word, is_new, is_obscure(word), display)
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
        """Redraw the open chooser with the current selection, via the active
        display rule (blue lines vs cell highlight -- game_screen.disambig_display).
        Called on open and on every cycle."""
        self._disambig_display_rule(self._disambig_options, self._disambig_index)

    # --- disambiguation display rules (game_screen.disambig_display) --------
    # HOW an open chooser is drawn, orthogonal to the clear_disambiguation cycle
    # rules that decide WHEN it opens. Each takes the ordered options + selected
    # index and renders; _end_disambiguation tears both views down regardless.
    def _rule_disambig_display_lines(self, options, selected):
        """Original: one blue polyline per candidate, the selected one dark on top
        (views.disambiguation_lines)."""
        paths = [
            [self._board.cell_center(x, y) for (x, y) in fw.path]
            for fw in options
        ]
        self._disambig_lines.show(paths, selected)

    def _rule_disambig_display_highlight(self, options, selected):
        """Alternate: light every candidate cell's text (hunt color) and tint the
        selected candidate's cells lime (views.disambiguation_highlight)."""
        self._disambig_highlight.show(options, selected, self._board)

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
        # Tear down whichever display was active; the inactive one no-ops.
        self._disambig_lines.clear()
        self._disambig_highlight.clear()
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
            # Union of the held words' cells, captured BEFORE _clear_paths removes
            # them, so constellation turnover can refill exactly what emptied. The
            # replenish rule only fills cells that actually went empty, so passing
            # overlapping / duplicate cells is safe.
            pending_cells = [cell for fw in self._pending for cell in fw.path]
            self._clear_paths(self._pending)
            # Constellation turnover: refill (or, under no-replenish, leave empty)
            # the vacated cells -- the batch-mode twin of the _commit_clear_now call,
            # so replenish works under rule_clear_at_phase_end too (the constellation
            # preset's timing). Inert in every other mode.
            if self._constellation:
                self._constellation_turnover_rule(pending_cells)
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
        self._last_reject_reason = reason
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
            reason = self._not_on_board_reason(word)
        elif word not in self._length_ok_words:
            reason = "too_short"
        elif word not in self._candidate_words:
            # A word that clears every stage-2 filter but the fossil requirement
            # gets its own reason; anything else here failed placement/nucleation.
            reason = "not_fossil" if word in self._pre_fossil_words else "not_involved"
        else:
            reason = "already_cleared"
        self._last_reject_reason = reason
        L.log_30003(word, reason)
        return get_string(f"err_{reason}")

    def _submission_messages(self, word):
        """The error line for a rejected `word`, plus -- only when it's simply not
        a dictionary word -- a 'did you mean?' line of close spellings underneath.
        Shown together in the selecting pane's multiline error area."""
        messages = [self._submission_error(word)]
        if not is_word(word):
            suggestions = self._spell_suggest_rule(word)
            # Whether the player will actually see the hint: text mode always shows
            # it; icon mode shows it only when error_icon_keeps_suggestion is on
            # (the not_in_dictionary reason always carries an icon). Logged for
            # debugging which hints reach the player -- see log_30005.
            shown = bool(suggestions) and (
                self._error_display == "text" or self._error_icon_keeps_suggestion)
            L.log_30005(word, suggestions, shown)
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
        # Single-phase never leaves MOVING: there is no selection phase to end.
        # It runs clear-on-submit (no held batch to flush) and has no placed piece
        # to settle, so every auto-end trigger (word limit, piece-adjacency) is a
        # no-op here.
        if self._single_phase:
            return
        self._endphase_clear_rule()
        self._settle_placed_cells()
        # Constellation auto-end (game_screen.constellation_auto_end): after the batch
        # clears + replenishes above, finish the game if the board can no longer spell
        # any word -- the batch-mode twin of the _commit_clear_now check, so auto-end
        # works under rule_clear_at_phase_end too. The rule ends the game itself and
        # returns True when it fires; stop here rather than returning to MOVING /
        # spawning the next piece. Off by default and inert in every other mode.
        if self._constellation and self._constellation_auto_end_rule():
            return
        # Omniswap auto-end (game_screen.omniswap_auto_end): the batch-mode twin of
        # the _commit_clear_now check, so auto-end works under rule_clear_at_phase_end
        # too. Stop here rather than returning to MOVING when it fires. Off by default
        # and inert in every other mode.
        if self._omniswap and self._omniswap_auto_end_rule():
            return
        self._set_phase(Phase.MOVING)
        self._moving_mode.advance()
