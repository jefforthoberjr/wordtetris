"""Word-muncher mode's board effects, extracted from GameScreen as a mixin.

MOVING_MUNCHER (game_screen.mode: rule_mode_muncher) builds a word by EATING
cells: the character walks the board and bites the cell he stands on, and that
cell's whole gram leaves the board and appends to the word assembling in the right
pane. The character, his animation and the word buffer live in the MODE
(views/moving_mode.MuncherMovingMode); what a bite does to the BOARD lives here,
because it needs the engine's cell state, replenish machinery and logging.

Every method runs with GameScreen's `self`, so it reaches the board, the
fossilized-cell set, the replenish rules and the panes exactly as the rest of the
engine does.

REPLENISH IS RECYCLED, NOT REBUILT. An eaten cell goes through the same
turnover + delay + fade + length machinery constellation mode uses
(game_screen.constellation_turnover, replenish_delay_seconds,
replenish_fade_seconds, replenish_length) -- so a muncher mode file chooses
between a board that stays eaten (rule_constellation_no_replenish, the board
shrinks as he clears it) and one that grows back behind him
(rule_constellation_replenish, optionally with the escalating hydra lengths) by
flipping the knobs that already exist.

WORD RESOLUTION. Nothing here goes through the SELECT pipeline. The grams were
taken off the board as they were eaten, so a submitted word is validated as a
plain dictionary lookup over the buffer (plus the shared word-length and repeat
rules) -- exactly the shooting gallery's shape, which is why an ACCEPTED word is
banked by calling straight into ShootingMixin._shooting_submit rather than
copying its scoring/recording body. A REJECTED word costs a LIFE
(game_screen.muncher_lives); the last life ends the game into the endgame typing
bonus.
"""

from config import CONFIG, get_string
from models.word_dictionary import is_word
import log_codes as L


class MuncherMixin:
    # Default so the engine's `if self._muncher` branches resolve to "not muncher"
    # unless __init__ turned it on from the mode (real games set it from
    # MuncherMovingMode.is_muncher; bare __new__ test instances inherit False).
    _muncher = False

    def _muncher_eat(self, pos):
        """One bite at board cell `pos`. Returns the gram's letters when something
        was actually eaten, or "" when the bite hit nothing edible -- the mode
        appends the return value to its word buffer, so "" is simply a bite that
        adds no letters.

        Three cells yield nothing, all of them deliberately silent rather than an
        error (a wasted bite is the player's own business, and an error blip for
        chewing air would be noise):

          * an EMPTY cell -- one he already ate, or a hole the formation left;
          * a FOSSILIZED cell -- frozen by a mode's clear-action, and frozen means
            frozen for teeth too;
          * a WILD cell -- it carries no fixed letters to spell with, the same
            reason the shooting gallery treats a shot wild cell as a miss.

        An eaten gram is gone from the board the instant it is bitten. It is never
        restored: a rejected word does not spit its letters back, and by then the
        cell may already hold a replenished gram."""
        gram = self._board.gram_at(*pos)
        eaten = ""
        if gram is None:
            L.log_20010("bite_empty", pos)
        elif pos in self._fossilized_cells:
            L.log_20010("bite_fossil", pos, gram=gram.text)
        elif gram.is_wild or not gram.text:
            L.log_20010("bite_wild", pos, gram=gram.text)
        else:
            eaten = gram.text
            self._board.clear_cell(*pos)
            # Refill (or don't) exactly as a cleared constellation cell would --
            # see the module docstring. The length map feeds the escalating
            # replenish_length rules the eaten gram's own size, so a muncher mode
            # can run hydra-style growth off bites.
            self._constellation_turnover_rule([pos], {pos: min(len(eaten), 3)})
            # The board changed, so the F3 formable-word sample is stale.
            self._dbg_words_dirty = True
            L.log_20010("bite", pos, gram=eaten)
        return eaten

    # --- lives (game_screen.muncher_lives) ---------------------------------
    def _muncher_start_lives(self):
        """Set the life count for a new game and show it. Called from
        MuncherMovingMode.start(), so a restart always deals a fresh three."""
        self._muncher_lives = CONFIG["rules"]["game_screen.muncher_lives"]
        L.log_20011("start", self._muncher_lives, "")
        self._muncher_show_lives()

    def _muncher_show_lives(self):
        """Put the remaining lives where a timer would go -- the moving pane's
        status row -- as a row of little mouth-closed munchers (see
        views/muncher_lives.MuncherLivesRow).

        Falls back to a plain "Lives: N" text readout on a pane that has no icon
        row. Only the merged single-phase pane draws the icons, and the muncher
        preset uses that pane; the fallback keeps the count visible if the mode is
        ever run two-phase rather than silently losing it."""
        pane = self._moving_side_pane
        if hasattr(pane, "set_lives"):
            pane.set_lives(self._muncher_lives)
        elif hasattr(pane, "set_status_text"):
            pane.set_status_text(get_string("muncher_lives", count=self._muncher_lives))

    def _muncher_lose_life(self, reason):
        """Spend one life on a bad word. At zero the game ends outright (the
        endgame typing bonus then takes over, exactly as a run-out clock or a
        typewriter cursor running off the board does) -- there is no other end
        condition in this mode."""
        self._muncher_lives -= 1
        L.log_20011("lost", self._muncher_lives, reason)
        self._muncher_show_lives()
        if self._muncher_lives <= 0:
            L.log_20011("out", 0, reason)
            self._enter_endgame()
        else:
            # Let the character react (game_screen.muncher_life_loss: dissolve and
            # reform, in place or back at the spawn cell). Deliberately NOT on the
            # last life: _enter_endgame has just taken the screen away from the
            # board, so an animation there would play to nobody -- and the mode
            # freezes input for the length of a fade, which must never be the last
            # thing a finished game does.
            self._moving_mode.lose_life_effect()

    # --- submitting the eaten word -----------------------------------------
    def _muncher_submit(self, word, path, segments):
        """Resolve the word the player has eaten. Returns True when it was
        accepted (scored and recorded), False when it cost a life.

        The gates, in the order the player meets them -- a word that fails ANY of
        them costs a life, per the mode's design: there is no free retry, and no
        way to put letters back, so a careless bite is the risk the whole mode
        turns on.

          not_in_dictionary  the eaten letters do not spell a word
          too_short          shorter than game_screen.word_length allows
          already_cleared    cleared earlier this game (game_screen.word_repeat;
                             under rule_repeat_allow this gate is simply open)

        An empty submit is not a submission at all -- it is a fumbled key press
        with nothing eaten, so it is ignored rather than punished."""
        accepted = False
        if not word:
            L.log_20011("empty", self._muncher_lives, "")
        else:
            reason = ""
            if not is_word(word):
                reason = "not_in_dictionary"
            elif not self._word_length_rule(word, path):
                reason = "too_short"
            elif not self._repeat_rule(word):
                reason = "already_cleared"
            if reason:
                self._muncher_reject(word, reason)
            else:
                # The eaten cells are already off the board, so banking is the
                # shooting gallery's job exactly: score, record for the endgame
                # typing bonus, add to the player dictionary, list it, draw the
                # trail -- with no clear-action, because there is nothing left to
                # clear. See ShootingMixin._shooting_submit.
                self._shooting_submit(word, path, segments)
                accepted = True
        return accepted

    def _muncher_reject(self, word, reason):
        """Spit the word out: clear the readout, show the reason (as an icon under
        game_screen.error_display: rule_error_icon, as text otherwise -- the same
        error slot every other mode rejects into), and spend a life."""
        pane = self._moving_side_pane
        pane.clear_word()
        messages = [get_string(f"err_{reason}")]
        pane.show_errors(messages, reason)
        L.log_30003(word, reason)
        self._muncher_lose_life(reason)

    def _muncher_forced_clear(self, word, path, segments):
        """game_screen.muncher_dead_end: the eaten letters can no longer begin any
        word and the player has used up the grace grams, so the word is taken away
        from them -- same cost as submitting it would have been. Routed through the
        normal reject so the error slot, the log and the life all behave
        identically; the reason gets its own string because "you were never going
        to get there" is a different message from "that is not a word"."""
        L.log_20011("dead_end", self._muncher_lives, word)
        self._muncher_reject(word, "muncher_dead_end")
