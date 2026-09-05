"""The endgame TYPING BONUS: after play ends, the player types out the words they
cleared, earning points for each one they spell correctly.

Why it exists: a player can clear words in this game without ever spelling them
(clicking cells, shooting grams, picking a picture off the idea belt). The typing
bonus makes them type each cleared word once, for typing muscle memory rather than
for recall -- the words are all shown, so this is copying, not remembering. There
is NO timer: the player has as long as they need, and the phase ends only when
every word has been typed (the incentive to work through all of them).

Scoring is the DICTIONARY-SCREEN formula (Scorer.composition_points_rule): the
word's cell/gram composition only, since the board context is gone by now. That is
independent of scoring.during_game, so a mode can score during play, at the end, or
both (see CONFIG_REFERENCE scoring.during_game).

This view owns the whole endgame UI: the target words over the board region (left)
and the typed field + banked-word list + running bonus total in the right pane.
The board-region display is deliberately a swappable rule (endgame.display); this
chunk ships the plain page, with the scrolling and conveyor variants to follow.
"""
import math
import pyglet

from config import CONFIG, get_color, get_string, select_rule
from models.scoring import Scorer
from models.spelling_suggester import nearest_word
from views.gram_preview import parse_variation
from views.endgame_displays import (build_page_display, build_scroll_display,
                                    build_belt_display)
import log_codes as L


# --- target-order rules (endgame.order) --------------------------------------
# What order the words to type are presented in. Each takes the targets in CLEAR
# order (the order the records arrived in) and returns them reordered; the display
# and the pane list both follow whatever comes back. Selected per run in start(),
# so a mode switch is picked up without rebuilding the view.
def rule_endgame_order_cleared(targets):
    """The order the player cleared them in, oldest first -- a replay of the game
    they just played. The original behavior."""
    return list(targets)


def rule_endgame_order_alphabetical(targets):
    """A-Z, like a page of the dictionary. Easiest to scan for the word you are
    part-way through typing, and the natural pairing with the page display."""
    return sorted(targets, key=lambda t: t["word"])


def rule_endgame_order_score(targets):
    """Highest-scoring first, so the biggest prizes are the ones on offer at the
    top of the list. Ties keep clear order (sorted is stable)."""
    return sorted(targets, key=lambda t: -t["points"])


# --- display rules (endgame.display) -----------------------------------------
# How the words to type are shown over the board region play has finished with.
# Each builds one of the interchangeable displays in views/endgame_displays.py,
# sized to that region. Selected per run in start(), like the order rules.
def rule_endgame_display_page(region_size, window_height):
    """One printed page: every word visible at once in columns, nothing moving.
    The gentlest display, and the one to keep for young players."""
    return build_page_display(region_size, window_height)


def rule_endgame_display_scroll(region_size, window_height):
    """A single slow column of LARGE words, looping forever -- fewer words on screen
    at a time, read from much bigger text."""
    return build_scroll_display(region_size, window_height)


def rule_endgame_display_belt(region_size, window_height):
    """The two-column conveyor (left column up, right column down), one looping ring
    seen through both windows -- the idea belt's motion applied to the words."""
    return build_belt_display(region_size, window_height)


# --- spelling-suggestion rules (endgame.spell_suggest) -----------------------
# The "did you mean?" offered after a MISSPELLED submission. This is deliberately
# NOT the in-play engine (game_screen.spell_suggest, which scans the whole
# dictionary): here the only words worth anything are the ones on screen, so a
# suggestion from outside that list would point the player at a word they cannot
# type for score. Each rule takes the typed text and the words still to be typed
# and returns ONE word (or "" for no suggestion). Selected per run in start().
def rule_endgame_suggest_off(typed, words, max_distance):
    """No "did you mean?" in the bonus -- the player finds the spelling on the
    board themselves. The original behavior (the miss is only echoed back)."""
    return ""


def rule_endgame_suggest_nearest_target(typed, words, max_distance):
    """The closest word still to be typed, by plain Levenshtein distance, with
    ties broken alphabetically -- see spelling_suggester.nearest_word. Never
    names a word already typed (it is worth nothing now) or one outside the
    target list."""
    return nearest_word(typed, words, max_distance)


class EndgameTyping:
    """One run of the typing bonus. Built per game screen and (re)started with
    start(records) at the end transition; inert (draws nothing, eats no input)
    until then. `on_finish` fires once, when the last target word is typed."""

    # How long the hit / miss flash under the typed field lingers, in seconds.
    FLASH_SECONDS = 1.6

    def __init__(self, grid_area_size, pane_x, pane_width, window_height, on_finish):
        self._grid_area_size = grid_area_size
        self._pane_x = pane_x
        self._pane_width = pane_width
        self._window_height = window_height
        self._on_finish = on_finish
        self._active = False
        # Per-word state: each target is {word, variation, points, done}. Built in
        # start() from the game's cleared-word records.
        self._targets = []
        self._typed = ""
        self._bonus_total = 0
        # Suggestion engine + distance ceiling, chosen per run in start().
        self._suggest_rule = rule_endgame_suggest_off
        self._suggest_max_distance = 0
        # Seconds left on the hit / miss flash under the typed field (0 = hidden).
        self._flash_remaining = 0.0
        # Composition scorer -- the same rule the My Dictionary screen scores a
        # collected word with. Built here (not shared with the game's Scorer) so the
        # bonus total is its own tally and never disturbs the in-play total.
        self._scorer = Scorer()

        self._batch = pyglet.graphics.Batch()
        # The board-region display of the words to type (endgame.display), chosen
        # per run in start() -- see the display rules above.
        self._display = None
        self._build_pane_labels()

    # --- lifecycle ---------------------------------------------------------
    def start(self, records):
        """Begin the bonus over `records` -- this game's ordered, de-duplicated
        cleared-word records (GameScreen._cleared_word_records). Each becomes a
        target scored from the gram grouping it was cleared with THIS game. An
        empty record list finishes immediately (nothing to type)."""
        self._targets = []
        for record in records:
            word = record["word"].upper()
            variation = record.get("variation") or _letter_variation(word)
            self._targets.append({
                "word": word,
                "variation": variation,
                "points": self._word_points(variation),
                "done": False,
            })
        # Presentation order (endgame.order). Read per run, not at import, so the
        # active game mode's override is the one that applies.
        order_rules = {
            "rule_endgame_order_cleared": rule_endgame_order_cleared,
            "rule_endgame_order_alphabetical": rule_endgame_order_alphabetical,
            "rule_endgame_order_score": rule_endgame_order_score,
        }
        self._targets = select_rule("endgame.order", order_rules)(self._targets)
        # Board-region display (endgame.display), also read per run so a mode swap
        # takes effect. It owns the whole left region; this view keeps the pane.
        display_rules = {
            "rule_endgame_display_page": rule_endgame_display_page,
            "rule_endgame_display_scroll": rule_endgame_display_scroll,
            "rule_endgame_display_belt": rule_endgame_display_belt,
        }
        self._display = select_rule("endgame.display", display_rules)(
            self._grid_area_size, self._window_height)
        self._display.show(self._targets)
        # "Did you mean?" engine (endgame.spell_suggest) and how far off a typed
        # word may be and still get one. Both read per run, like the rules above,
        # so a mode override applies (a class-body read would freeze the base).
        suggest_rules = {
            "rule_endgame_suggest_off": rule_endgame_suggest_off,
            "rule_endgame_suggest_nearest_target": rule_endgame_suggest_nearest_target,
        }
        self._suggest_rule = select_rule("endgame.spell_suggest", suggest_rules)
        self._suggest_max_distance = CONFIG["rules"]["endgame.suggest_max_distance"]
        self._typed = ""
        self._bonus_total = 0
        self._flash_remaining = 0.0
        self._flash_label.text = ""
        self._suggest_label.text = ""
        self._active = True
        self._refresh_pane()
        L.log_50004(len(self._targets))
        if not self._targets:
            self._finish()

    def stop(self):
        """Leave the bonus (a new game, or the player quitting to the menu)."""
        self._active = False

    @property
    def active(self):
        return self._active

    @property
    def bonus_total(self):
        """Points earned in the bonus so far -- what a caller banks at the end."""
        return self._bonus_total

    def _finish(self):
        self._active = False
        L.log_50006(self._bonus_total)
        if self._on_finish is not None:
            self._on_finish(self._bonus_total)

    def _word_points(self, variation):
        """One target's value: the composition score of the grouping it was cleared
        with (the dictionary-screen formula). Callers pass a stand-in grouping for a
        word recorded without one (see _letter_variation), so a target is never worth
        nothing for want of a record."""
        grams = _variation_grams(variation)
        if not grams:
            return 0
        letters = 0
        for gram in grams:
            letters += len(gram)
        return self._scorer.composition_points_rule(
            word_length=letters, gram_lengths=[len(g) for g in grams])

    # --- input -------------------------------------------------------------
    def on_text(self, text):
        """Append a typed letter. Non-letters (and anything typed once the bonus is
        over) are ignored; the field is uppercase to match the display."""
        if self._active and text.isalpha():
            self._typed += text.upper()
            self._refresh_pane()

    def on_key_press(self, symbol, modifiers, keys):
        """Backspace edits, ENTER submits. `keys` is GameScreen's control map, so
        the bindings stay in controls.yaml. Returns True when the key was used."""
        used = False
        if self._active:
            if symbol in keys["word_backspace"]:
                self._typed = self._typed[:-1]
                self._refresh_pane()
                used = True
            elif symbol in keys["word_submit"]:
                self._submit()
                used = True
            elif symbol in keys["word_clear"]:
                self._typed = ""
                self._refresh_pane()
                used = True
        return used

    def _submit(self):
        """Score the typed word if it matches an un-typed target, then clear the
        field either way. A misspelling simply scores nothing -- the player retypes
        it (mistakes are part of the exercise, so there is no penalty). Submitting
        is explicit (ENTER) rather than on-match, because one target word can be a
        prefix of another (CAT / CATCH)."""
        typed = self._typed
        self._typed = ""
        matched = ""
        points = 0
        for target in self._targets:
            if not target["done"] and target["word"] == typed:
                target["done"] = True
                matched = target["word"]
                points = target["points"]
                self._bonus_total += points
                self._banked_word(target)
        suggestion = ""
        if not matched and typed:
            suggestion = self._suggest_rule(
                typed, self._remaining_words(), self._suggest_max_distance)
        L.log_50005(typed, matched, points, self._bonus_total, suggestion)
        self._flash(typed, matched, points, suggestion)
        self._refresh_pane()
        self._display.refresh(self._targets)
        done = True
        for target in self._targets:
            if not target["done"]:
                done = False
        if done and self._active:
            self._finish()

    def _remaining_words(self):
        """The target words still to be typed -- the only candidates a suggestion
        may name, since a word already banked is worth nothing now."""
        words = []
        for target in self._targets:
            if not target["done"]:
                words.append(target["word"])
        return words

    def _flash(self, typed, matched, points, suggestion=""):
        """Show the verdict on a MISS under the field: the typed text echoed back, so
        the player sees the spelling they actually entered. A HIT says nothing here --
        it already lands in the banked-word list (with its points) right below, and
        flashing it as well just said the same thing twice. An empty submit (bare
        ENTER) says nothing either."""
        if matched:
            # ORIGINAL behavior (flashed the hit here too), kept for reference:
            #   self._flash_label.text = get_string(
            #       "endgame_hit", word=matched, count=points)
            #   self._flash_label.color = get_color("endgame.hit_text")
            #   self._flash_remaining = self.FLASH_SECONDS
            self._flash_label.text = ""
            self._flash_remaining = 0.0
        elif typed:
            self._flash_label.text = get_string("endgame_miss", word=typed)
            self._flash_label.color = get_color("endgame.miss_text")
            self._flash_remaining = self.FLASH_SECONDS
        else:
            self._flash_label.text = ""
            self._flash_remaining = 0.0
        # The "did you mean?" line rides under the miss and fades with it (a hit
        # and a bare ENTER both pass "" and so clear it).
        if suggestion:
            self._suggest_label.text = get_string("endgame_suggest", word=suggestion)
        else:
            self._suggest_label.text = ""

    def update(self, dt):
        """Age out the hit / miss flash, and drive the board-region display (a moving
        one scrolls here; the page ignores it). There is deliberately no clock on the
        player -- nothing here ends the bonus."""
        if self._flash_remaining > 0:
            self._flash_remaining -= dt
            if self._flash_remaining <= 0:
                self._flash_remaining = 0.0
                self._flash_label.text = ""
                self._suggest_label.text = ""
        if self._display is not None:
            self._display.update(dt)

    # --- right pane --------------------------------------------------------
    def _build_pane_labels(self):
        """The right-pane furniture: the prompt, the typed field, the running bonus
        total, and the list of words banked so far (newest at the top, each with the
        points it earned -- the same "word +NN" shape the in-play word list uses)."""
        margin = math.floor(self._pane_width / 16)
        x = self._pane_x + margin
        top = self._window_height - margin
        title_size = math.floor(self._window_height / 26)
        self._prompt_label = pyglet.text.Label(
            get_string("endgame_prompt"), font_size=math.floor(title_size * 0.8),
            x=x, y=top, anchor_x="left", anchor_y="top",
            color=get_color("endgame.prompt_text"), batch=self._batch,
        )
        self._input_label = pyglet.text.Label(
            "_", font_size=title_size,
            x=x, y=top - math.floor(title_size * 1.4), anchor_x="left", anchor_y="top",
            color=get_color("endgame.input_text"), batch=self._batch,
        )
        # Immediate verdict on the last submission, right under the field: the word
        # and what it just earned on a hit, or the miss echoed back so the player
        # sees what they actually typed. Fades out after FLASH_SECONDS.
        self._flash_label = pyglet.text.Label(
            "", font_size=math.floor(title_size * 0.8),
            x=x, y=top - math.floor(title_size * 2.7), anchor_x="left", anchor_y="top",
            color=get_color("endgame.hit_text"), batch=self._batch,
        )
        # "Did you mean X?" under the miss (endgame.spell_suggest), naming a word
        # still on the board -- so the player can go and read its spelling. This is
        # the one pane line that is a SENTENCE plus a word rather than a word, so it
        # is the smallest text here and the only one given a wrap width: without one
        # a long suggestion (NODE, ABSOLUTION) ran off the right edge of the pane and
        # was simply cut in half ("Did you mean NO").
        self._suggest_label = pyglet.text.Label(
            "", font_size=math.floor(title_size * 0.6),
            x=x, y=top - math.floor(title_size * 3.5), anchor_x="left", anchor_y="top",
            width=self._pane_width - 2 * margin, multiline=True,
            color=get_color("endgame.suggest_text"), batch=self._batch,
        )
        self._total_label = pyglet.text.Label(
            "", font_size=math.floor(title_size * 0.9),
            x=x, y=top - math.floor(title_size * 5.1), anchor_x="left", anchor_y="top",
            color=get_color("endgame.total_text"), batch=self._batch,
        )
        # Banked-word rows, pre-spawned blank and filled newest-first.
        self._row_size = math.floor(title_size * 0.75)
        self._row_height = math.floor(self._row_size * 1.35)
        rows_top = top - math.floor(title_size * 6.5)
        self._banked_rows = []
        row_count = max(1, math.floor((rows_top - margin) / self._row_height))
        for r in range(row_count):
            self._banked_rows.append(pyglet.text.Label(
                "", font_size=self._row_size,
                x=x, y=rows_top - r * self._row_height,
                anchor_x="left", anchor_y="top",
                color=get_color("endgame.banked_text"), batch=self._batch,
            ))
        # The banked words in newest-first order (text only; rows re-render from it).
        self._banked = []

    def _banked_word(self, target):
        """Record a just-typed word for the pane list (newest first)."""
        self._banked.insert(0, target["word"] + "  +" + str(target["points"]))

    def _refresh_pane(self):
        self._input_label.text = self._typed + "_"
        self._total_label.text = get_string("endgame_total", count=self._bonus_total)
        for r, row in enumerate(self._banked_rows):
            if r < len(self._banked):
                row.text = self._banked[r]
            else:
                row.text = ""

    def draw(self):
        """The right-pane typing UI, then the board-region display of the words
        (which owns its own batch, so a display can layer shapes however it likes)."""
        if self._active:
            self._batch.draw()
            if self._display is not None:
                self._display.draw()


def _letter_variation(word):
    """A stand-in grouping for a word recorded WITHOUT one: one cell per letter, in
    the square encoding ("legacy" -> "l|e|g|a|c|y"). Legacy / defensive only -- every
    clear route records the real grouping -- but it keeps such a word both scorable
    (it would otherwise be worth nothing) and drawable in cell mode (it would
    otherwise render as an empty space the player cannot read)."""
    return "|".join(word.lower())


def _variation_grams(variation):
    """The per-cell gram letters of an encoded player-dictionary variation, e.g.
    "ge|[ar]" -> ["GE", "AR"] -- the cell count and letters-per-cell the composition
    score is computed from.

    Defers to gram_preview.parse_variation, the one parser for this encoding (it also
    reports the grid shape and each gram's obstacle / mission / wild flags, which the
    cell RENDERING needs -- endgame.render). Scoring wants only the letters, so the
    flags are dropped here; both readings come from the same parse, so a change to the
    encoding can't make the score and the picture disagree."""
    grams = []
    if variation:
        _shape, parsed = parse_variation(variation)
        for text, _obstacle, _mission, _wild in parsed:
            grams.append(text)
    return grams
