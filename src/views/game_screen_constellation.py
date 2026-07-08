"""Constellation mode's word matcher, extracted from GameScreen as a mixin.

Constellation mode drops the adjacency pathfinder: a typed word is accepted if
its letters can be assembled from grams sitting ANYWHERE on the board, each cell
used at most once. This mixin owns that on-submit matcher; every method runs with
GameScreen's `self`, so it reaches the board and the shared fossil rules. The
matcher's output is a list of FoundWord (the same shape the pathfinder produces),
so the rest of the SELECT pipeline -- disambiguation (fewest-cell auto vs the
blue-line chooser), clearing/fossilizing, the word-trail overlay, scoring --
is reused unchanged.

Whole-gram only (game_screen answer): a word is cut into whole board grams, never
a partial gram. Wild-vowel cells are skipped for now (the constellation fill
formations don't use wilds); revisit if a wild formation is ever paired with this
mode."""

from collections import Counter

from views.found_word import FoundWord
from models.word_dictionary import is_word, all_words
from starting_coverage import any_word_formable, sample_formable_words
import debug_panel
import log_codes as L
from config import get_string


class ConstellationMixin:
    # Default so the SELECT pipeline's `if self._constellation` branches resolve
    # to the pathfinder path unless __init__ turned constellation on (real games
    # set it from the mode; bare __new__ test instances inherit this False).
    _constellation = False

    # --- SELECT-pipeline seam (routed here when self._constellation is True) ---
    # The engine calls these instead of the pathfinder-based candidate map. They
    # never enumerate the board: options are matched on demand for the one word the
    # player typed (enumerating every formable word would be combinatorial and
    # would hint which words exist -- see the no-availability-hints rule).
    def _recompute_candidates_constellation(self):
        """Constellation's cheap stand-in for _recompute_candidates: there is no
        pre-enumerated candidate set (a word is matched on submit), so just clear
        the maps the shared pipeline expects to exist. The diagnostic word-sets the
        pathfinder builds are unused here -- _constellation_submission_error does
        its own on-demand diagnosis."""
        self._candidate_word_options = {}
        self._candidates = []
        self._candidate_words = {}

    def _constellation_options(self, word):
        """The clearable spellings of a submitted `word` in constellation mode: the
        matcher's cell-assemblies, kept only if `word` is a dictionary word and the
        assembly meets the length rule. None when nothing qualifies (so the submit
        path rejects and asks _constellation_submission_error why)."""
        if not is_word(word):
            return None
        matches = self._constellation_match(word, self._constellation_max_paths)
        ok = [fw for fw in matches if self._word_length_rule(fw.word, fw.path)]
        return ok or None

    def _constellation_submission_error(self, word):
        """The single most specific reason a constellation `word` can't clear,
        walking inward: not a dictionary word, not assemblable from the board at
        all, assemblable but too short, else already cleared this game. Reuses the
        same err_* strings/log as the pathfinder path (_submission_error)."""
        if not is_word(word):
            reason = "not_in_dictionary"
        elif not self._constellation_match(word, 1):
            reason = "not_on_board"
        elif not [fw for fw in self._constellation_match(word, self._constellation_max_paths)
                  if self._word_length_rule(fw.word, fw.path)]:
            reason = "too_short"
        else:
            reason = "already_cleared"
        L.log_30003(word, reason)
        return get_string(f"err_{reason}")

    # --- turnover rules (game_screen.constellation_turnover) -------------------
    # After a constellation word clears, what becomes of the cells it vacated.
    # Only fires in constellation mode (see _commit_clear_now); with a fossilize
    # clear-action the cells aren't empty, so replenish naturally skips them.
    def _rule_constellation_no_replenish(self, cleared_cells):
        """Vacated cells stay empty -- the board shrinks toward the whole-board-
        cleared endgame (pair with rule_clear_remove + rule_victory_grid_empty)."""
        pass

    def _rule_constellation_replenish(self, cleared_cells):
        """Refill each now-empty vacated cell with a fresh gram from the configured
        player picker, so the board never empties (an endless constellation). A
        cell still occupied -- e.g. fossilized by the clear-action -- is left
        untouched; the new gram gets the picker's score-gradient glyph color for
        free (built through _fill_one_player_cell's piece). A replenished cell
        under an active hunt re-lights via the caller's recompute."""
        for (x, y) in cleared_cells:
            if self._board.is_valid(x, y) and self._board.gram_at(x, y) is None:
                self._fill_one_player_cell(x, y)

    # --- auto-end rules (game_screen.constellation_auto_end) -------------------
    # After a constellation word clears, decide whether the game should finish on
    # its own because the remaining grams can no longer spell ANY word. Consulted
    # only in constellation mode (see _commit_clear_now); the off rule is the
    # default so nothing new is revealed unless the option is turned on. Note this
    # trades against the no-availability-hints rule: an auto-finish tells the
    # player the board is exhausted, so it is opt-in.
    def _rule_constellation_auto_end_off(self, *_):
        """Never auto-end: the player finishes by hand (the End game button, or a
        configured victory rule). The default."""
        return False

    def _rule_constellation_auto_end_on(self, *_):
        """End the game the moment no dictionary word can still be assembled from
        the board's remaining usable grams: finish (FINISHED) and return True so
        the caller stops. Meaningful only with a shrinking board -- under
        rule_constellation_replenish fresh grams keep arriving, so this rarely (if
        ever) fires."""
        if self._constellation_any_word_formable():
            return False
        self._enter_endgame()
        return True

    def _constellation_usable_grams(self):
        """The multiset {gram text -> cell count} of the board's currently usable
        grams: occupied, non-wild, non-fossil-wall cells, pooled by text. The raw
        material for both end-detection and the debug sample -- the same cells
        _constellation_match can draw on. Fossil handling matches the block case
        exactly (walled cells excluded); an allow-fossil formation isn't the
        constellation preset, so a word spellable only from fossil cells isn't
        special-cased here."""
        grams = Counter()
        for cell in self._board.occupied_cells():
            if self._fossil_is_wall_rule(cell):
                continue
            gram = self._board.gram_at(*cell)
            if gram is None or gram.is_wild or not gram.text:
                continue
            grams[gram.text] += 1
        return grams

    def _constellation_accept(self):
        """The word-length rule as an (word, n_cells) predicate for the coverage
        helpers. The rule reads only len(text) and len(path), so a placeholder path
        of the grouping's cell count suffices -- the same shim the starting-coverage
        pass uses."""
        return lambda word, n_cells: self._word_length_rule(word, [None] * n_cells)

    def _constellation_any_word_formable(self):
        """Whether ANY dictionary word can still be assembled from the board's
        remaining usable grams under the active word-length rule -- the
        end-detection twin of _constellation_match. Existence-only over the whole
        dictionary with an early exit on the first formable word, so a board that
        can still spell something is cheap."""
        grams = self._constellation_usable_grams()
        if not grams:
            return False
        return any_word_formable(all_words(), grams, self._constellation_accept())

    # --- debug-panel word samples (F3) -----------------------------------------
    def _update_debug_word_samples(self):
        """Keep the debug panel's example-word list current, doing dictionary work
        ONLY while the panel is visible and something changed. Called every tick
        from GameScreen.update. A rising edge of visibility re-dirties, so the
        samples appear the instant the panel opens; otherwise a hidden panel (normal
        play) costs nothing. Non-constellation modes clear the section."""
        visible = debug_panel.visible
        if visible and not self._dbg_panel_was_visible:
            self._dbg_words_dirty = True     # opening the panel is a change
        self._dbg_panel_was_visible = visible
        if not visible or not self._dbg_words_dirty:
            return
        self._dbg_words_dirty = False
        if self._constellation:
            debug_panel.set_word_samples(
                self._constellation_word_samples(self._dbg_word_sample_count))
        else:
            debug_panel.set_word_samples(None)   # section hidden outside constellation

    def _constellation_word_samples(self, limit):
        """Up to `limit` example words the board can currently spell (the F3 debug
        sample). Reuses the usable-gram gathering and feeds sample_formable_words,
        which early-exits at `limit` -- so this is cheap unless the board is nearly
        unspellable. A short SAMPLE, never a count (a count is a stronger hint --
        see the no-word-availability-hints rule)."""
        grams = self._constellation_usable_grams()
        if not grams:
            return []
        return sample_formable_words(all_words(), grams, self._constellation_accept(), limit)

    def _constellation_match(self, word, limit):
        """Every way to assemble `word` from distinct board cells' whole grams,
        as FoundWord(path, segments, word) -- capped at `limit` assemblies.

        A segmentation cuts `word` into a sequence of gram-texts that each exist
        on the board; an assembly then binds each segment to a specific cell
        carrying that gram, with no cell reused. Different cell bindings are
        different constellations (different star patterns the chooser can cycle),
        so they're distinct results. Longer grams are tried first, so assemblies
        with FEWER cells surface first -- the capped list still contains the
        fewest-cell pick the auto-disambiguation rule wants.

        Fossil handling matches the rest of word-finding: a fossilized cell is
        excluded when the fossil-use rule walls it off (block), and an assembly
        must still satisfy _fossil_word_ok_rule (allow demands one fresh cell).
        Returns [] when `word` cannot be spelled from the board."""
        avail = {}                      # gram text -> [cells carrying it]
        for cell in self._board.occupied_cells():
            if self._fossil_is_wall_rule(cell):
                continue                # fossil-block: a frozen cell is unusable
            gram = self._board.gram_at(*cell)
            if gram is None or gram.is_wild:
                continue                # empty / wild (wilds unsupported here yet)
            avail.setdefault(gram.text, []).append(cell)
        # Longest grams first => fewest-cell assemblies are found early, so the
        # cap never drops the compact pick the auto rule selects.
        texts = sorted(avail, key=len, reverse=True)

        results = []
        used = set()
        path = []
        segs = []

        def rec(pos):
            if len(results) >= limit:
                return
            if pos == len(word):
                # A complete assembly: accept it if the fossil-word rule is happy
                # (block always is; allow needs at least one non-fossil cell).
                if self._fossil_word_ok_rule(path):
                    results.append(FoundWord(list(path), list(segs), word))
                return
            for text in texts:
                if len(results) >= limit:
                    return
                if not word.startswith(text, pos):
                    continue
                for cell in avail[text]:
                    if cell in used:
                        continue
                    used.add(cell)
                    path.append(cell)
                    segs.append(text)
                    rec(pos + len(text))
                    used.discard(cell)
                    path.pop()
                    segs.pop()

        rec(0)
        return results
