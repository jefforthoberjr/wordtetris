"""Shooting-gallery mode's word submit, extracted from GameScreen as a mixin.

MOVING_SHOOTING_GALLERY (game_screen.mode: rule_mode_shooting_gallery) builds a
word by SHOOTING cells, not typing: each shot appends the hit cell's whole gram to
a running buffer (ShootingGalleryMode._buffer). Detection is greedy -- the instant
the buffer spells a dictionary word the mode calls _shooting_submit here. Because
the word is validated as a plain dictionary lookup on the shot grams (never
assembled from the board), the normal SELECT pipeline -- which matches a typed word
against the board's cells and then clears them -- does not apply: the shot cells are
already fading away on their own. So this is a slimmed sibling of
SelectionMixin._clear_paths: it scores, records, lists, logs, and draws the shot
trail, but performs NO board clear-action (there is nothing left to clear).

Every method runs with GameScreen's `self`, reaching the shared scorer, player
dictionary, panes, and score/word-trail rules the rest of the engine already owns."""

from views.found_word import FoundWord
from models.word_dictionary import is_obscure
import log_codes as L


class ShootingMixin:
    # Default so the engine's `if self._shooting` branches resolve to "not shooting"
    # unless __init__ turned it on from the mode (real games set it from
    # ShootingGalleryMode.is_shooting; bare __new__ test instances inherit False).
    _shooting = False

    def _shooting_submit(self, word, path, segments):
        """Award and record one shot-spelled `word` (greedy detection already
        confirmed it is a dictionary word). `path` is the shot cells in spelled
        order, `segments` their gram letters. Mirrors the tail of _clear_paths --
        scoring, the player dictionary, the cleared-word list, the log, the score
        readout, and the word-trail 'constellation' through the shot cells -- but
        skips the board clear-action entirely: the shot cells are removed by the
        ShootingField's fast fade, not by a word submit."""
        fw = FoundWord(list(path), list(segments), word)
        is_new = not self._player_dict.contains(word)
        obscure = is_obscure(word)
        # The gram grouping recorded for the player dictionary -- the shot grams in
        # order, lowercased and joined by the grid separator. No obstacle / mission /
        # wild wrapping (rule_formation_empty seeds none of those here), so this is
        # the plain-cell case of _encode_variation without a board read.
        variation = self._gram_separator.join(seg.lower() for seg in segments)
        # Score facts read the cell-kind sets (all empty here) + the gram lengths, so
        # they hold even though the shot cells may already be gone from the board.
        facts = self._word_score_facts(fw)
        points = self._scorer.score_word_rule(is_new=is_new, **facts)
        display = self._scorer.word_score_display_rule(is_new=is_new, **facts)
        # Trail through the shot cells (gated by game_screen.word_trail): the centers
        # are board geometry, valid even after the cells cleared.
        self._word_trail_rule([fw])
        self._player_dict.add(word, variation)
        self._cleared_word_history.add(word)
        # Keep the word (with THIS game's grouping) for the endgame typing bonus,
        # the same as _clear_paths does for every other clear route.
        self._record_cleared_word(word, variation, is_new, obscure, points)
        self._words_cleared_this_game += 1
        L.log_30002(word, fw.path, variation, is_new, obscure, points)
        # List it (the game-long sink) and reset the buffer readout. add_cleared_words
        # lists; accept_word only clears the field (it does not re-list -- see the
        # merged pane), so the two together mirror _clear_paths' pane updates.
        pane = self._moving_side_pane
        pane.add_cleared_words([word], [is_new], [obscure], [display])
        pane.accept_word(word, is_new, obscure, display)
        self._dictionary_count_rule(pane, len(self._player_dict))
        self._refresh_score()
        # Any award changes the F3 formable-word sample basis; recompute lazily.
        self._dbg_words_dirty = True
