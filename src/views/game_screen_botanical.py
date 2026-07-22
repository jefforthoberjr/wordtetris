"""Botanical mode's word matcher + leaf placement, extracted as a GameScreen mixin.

Botanical mode is a word-growing crossword. The board opens empty but for a
vertical STEM column of per-cell grams down the center. A typed word is accepted
if it CONTAINS the gram of some un-sprouted stem cell as a contiguous chunk; the
word is then laid horizontally through that stem cell (its gram forming the
crossing chunk) and the rest of the word grows out BOTH sides as new 'leaf' cells,
each a gram of up to three letters. Only the crossing chunk comes from the board --
the rest of the word is freely typed -- so, unlike every other mode, a word is only
PARTLY spelled from existing cells.

Rules: one leaf per stem cell (a sprouted stem cell is done), and any placement
whose leaf columns run off the board or overlap an existing cell is rejected. The
word must grow at least one leaf (a word that is exactly a stem gram is rejected).

Every method runs with GameScreen's self, so it reaches the board, the stem set,
the scorer and the shared clear/record sink. Kept out of game_screen.py to bound
that file's size (see AGENTS.md). Botanical PLACES cells on submit rather than
clearing them, so it bypasses the SELECT clear pipeline (hooked in _on_submit_word)
and records the grown word through _clear_paths under the no-op rule_clear_none."""

from models.gram import Gram
from models.word_dictionary import is_word, is_obscure
from views.found_word import FoundWord
from config import get_string
import log_codes as L

_LEAF_MAX = 3   # a leaf cell holds up to this many letters


class BotanicalMixin:
    # Default so the _on_submit_word hook resolves False on bare __new__ test
    # instances (real games set it from the mode). Only BotanicalMode flips it True.
    _botanical = False

    def _botanical_submit(self, word):
        """Handle one typed word in botanical mode (single-phase, clear-on-submit):
        grow it as a leaf off a stem cell, or show why it can't. Bypasses the whole
        SELECT clear pipeline -- botanical places cells rather than clearing them.
        The active game_screen.botanical_disambiguation rule then either grows a
        chosen placement now or opens the cycle chooser."""
        placements = self._botanical_placements(word) if is_word(word) else []
        if not placements:
            self._reject_submission(word, [self._botanical_submission_error(word)])
            return
        self._botanical_disambiguation_rule(word, placements)

    # --- botanical grow-site rules (game_screen.botanical_disambiguation) ----
    # WHERE a word grows when several stem crossings / leaf layouts are legal.
    # Signature (word, placements) -> None: grow a chosen placement now, or open the
    # SHARED cycle chooser (the same left/right + Enter UI the SELECT clear_
    # disambiguation rules drive), whose on_confirm grows the confirmed layout.
    def _rule_botanical_disambig_auto_pick(self, word, placements):
        """Original: silently grow the most-compact layout (_botanical_pick), no
        player choice."""
        self._botanical_place(word, self._botanical_pick(placements))

    def _rule_botanical_disambig_cycle_two_or_more_choices(self, word, placements):
        """Open the chooser only when 2+ layouts fit; a lone layout grows instantly
        (no needless prompt)."""
        self._botanical_open_chooser(word, placements, min_choices=2)

    def _rule_botanical_disambig_cycle_one_or_more_choices(self, word, placements):
        """Open the chooser for every accepted word, a lone layout included -- so
        every grow previews its span and takes an explicit confirm."""
        self._botanical_open_chooser(word, placements, min_choices=1)

    def _botanical_open_chooser(self, word, placements, min_choices):
        """Shared entry for the cycle rules: below min_choices layouts, grow the
        picked one now; else open the shared cycle chooser over the layouts (built as
        FoundWords), committing the confirmed one via _botanical_confirm_placement."""
        if len(placements) < min_choices:
            self._botanical_place(word, self._botanical_pick(placements))
            return
        options = [self._botanical_found_word(p) for p in placements]
        self._begin_disambiguation(word, options, self._botanical_confirm_placement)

    def _botanical_found_word(self, placement):
        """The FoundWord the chooser cycles for a placement: its full reading path +
        per-cell segments (see _botanical_layout). The chooser orders/draws by these
        alone, and _botanical_confirm_placement rebuilds the grow from them."""
        return FoundWord(list(placement["path"]), list(placement["segments"]),
                         placement["word"])

    def _botanical_confirm_placement(self, word, found):
        """Chooser on_confirm: grow the confirmed layout, rebuilt from its FoundWord.
        The one path cell that is a stem is the crossing; every other path cell is a
        new leaf holding its segment's gram."""
        stem = next(cell for cell in found.path if cell in self._stem_cells)
        cells = [(x, y, seg) for (x, y), seg in zip(found.path, found.segments)
                 if (x, y) != stem]
        self._botanical_place(word, {"stem": stem, "cells": cells,
                                     "segments": list(found.segments),
                                     "path": list(found.path), "word": word})

    def _botanical_placements(self, word):
        """Every legal way to grow `word` off the stem: for each un-sprouted stem
        cell whose gram occurs in `word`, at each occurrence, the horizontal leaf
        layout -- kept only when every leaf column is on the board and empty. Each
        entry is a dict {stem, cells, segments, path, word}."""
        out = []
        for stem in sorted(self._stem_cells):
            if stem in self._sprouted_stem_cells:
                continue
            gram = self._board.gram_at(*stem)
            if gram is None:
                continue
            gt = gram.text
            start = word.find(gt)
            while start != -1:
                layout = self._botanical_layout(word, start, gt, stem)
                if layout is not None:
                    out.append(layout)
                start = word.find(gt, start + 1)
        return out

    def _botanical_layout(self, word, k, gram_text, stem):
        """The leaf layout for placing `word` so its gram at index k..k+len sits on
        stem cell `stem`: chunk the letters left and right of the crossing into
        <= _LEAF_MAX-letter grams, step each out from the stem into its own column,
        and require every one on-board and empty. Returns the placement dict, or None
        if it grows no leaf or doesn't fit."""
        sx, sy = stem
        left_chunks = self._botanical_chunks(word[:k])
        right_chunks = self._botanical_chunks(word[k + len(gram_text):])
        if not left_chunks and not right_chunks:
            return None   # word is exactly the stem gram -- nothing grows
        # Left chunks fill columns sx-n .. sx-1 (reading L->R); right chunks sx+1 ..
        cells = [(sx - len(left_chunks) + i, sy, text) for i, text in enumerate(left_chunks)]
        cells += [(sx + 1 + i, sy, text) for i, text in enumerate(right_chunks)]
        for (x, y, _t) in cells:
            if not self._board.is_valid(x, y) or self._board.gram_at(x, y) is not None:
                return None
        # Full reading order (left leaves, stem, right leaves) for scoring + record.
        path = ([(x, y) for (x, y, _t) in cells[:len(left_chunks)]] + [stem]
                + [(x, y) for (x, y, _t) in cells[len(left_chunks):]])
        segments = left_chunks + [gram_text] + right_chunks
        return {"stem": stem, "cells": cells, "segments": segments,
                "path": path, "word": word, "k": k}

    def _botanical_chunks(self, letters):
        """Split `letters` into consecutive grams of up to _LEAF_MAX letters, greedy
        from the left (OVERLOADING's 'VERLOADING' -> VER, LOA, DIN, G). Empty in,
        empty out."""
        return [letters[i:i + _LEAF_MAX] for i in range(0, len(letters), _LEAF_MAX)]

    def _botanical_pick(self, placements):
        """Choose one placement when several are legal: the FEWEST new leaf cells
        (most compact), then the EARLIEST crossing position in the word (so a stem
        letter at the word's start grows rightward, matching the natural reading --
        OVERLOADING crosses its FIRST O into VER/LOA/DIN/G), then deterministically by
        stem cell and cells so a replay reproduces it."""
        return min(placements,
                   key=lambda p: (len(p["cells"]), p["k"], p["stem"], p["cells"]))

    def _botanical_place(self, word, placement):
        """Grow the chosen leaf: place each new leaf cell (a forced-gram unimo in the
        leaf color), mark the stem cell sprouted, then record + score the word through
        the shared sink (clear-action rule_clear_none leaves the cells in place)."""
        for (x, y, text) in placement["cells"]:
            self._place_leaf_cell(x, y, text)
        self._sprouted_stem_cells.add(placement["stem"])
        L.log_30008(word, placement["stem"], placement["path"])
        fw = FoundWord(list(placement["path"]), list(placement["segments"]), word)
        is_new = not self._player_dict.contains(word)
        display = self._scorer.word_score_display_rule(
            is_new=is_new, **self._word_score_facts(fw))
        self._clear_paths([fw])   # scores, adds to dict, lists (rule_clear_none: cells stay)
        self._selecting_side_pane.accept_word(word, is_new, is_obscure(word), display)
        self._dictionary_count_rule(self._selecting_side_pane, len(self._player_dict))

    def _place_leaf_cell(self, x, y, text):
        """Build + settle one leaf cell holding the forced gram `text` (1-3 letters)
        in the leaf color. dedup_grams=False: a leaf is a deliberate fixed gram, never
        re-rolled (mirrors the player word-piece)."""
        piece = self._piece_class(
            self._unimo_type, self._cell_size, self._piece_batch, visible=False,
            gram_pick_rule=lambda count: [Gram(text)],
            cell_color=self.LEAF_CELL_COLOR, dedup_grams=False)
        piece.set_position(x, y)
        piece.place()
        for gx, gy, cell, label, gram, overlay in piece.get_cell_data():
            self._board.place(gx, gy, cell, label, gram, overlay)
        piece.set_visible(True)

    def _botanical_submission_error(self, word):
        """The most specific reason a botanical `word` can't grow: not a dictionary
        word, else no un-sprouted stem gram occurs in it (no crossing), else a
        crossing exists but no layout fits on the board (blocked / off the edge)."""
        if not is_word(word):
            reason = "not_in_dictionary"
        elif not self._botanical_any_crossing(word):
            reason = "botanical_no_stem"
        else:
            reason = "botanical_no_room"
        self._last_reject_reason = reason
        L.log_30003(word, reason)
        return get_string(f"err_{reason}")

    def _botanical_any_crossing(self, word):
        """Whether any un-sprouted stem cell's gram occurs in `word` at all (ignoring
        whether the leaves fit) -- splits 'no stem letter' from 'no room'."""
        for stem in self._stem_cells:
            if stem in self._sprouted_stem_cells:
                continue
            gram = self._board.gram_at(*stem)
            if gram is not None and gram.text in word:
                return True
        return False
