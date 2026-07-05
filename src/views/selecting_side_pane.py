import pyglet
from views.shaders import get_shape_shader
from views.scrolling_word_list import ScrollingWordList
from config import get_color, get_string
from controls import control_keys


class SelectingSidePane:
    """Right pane shown during the SELECTING phase: the player types a word and
    submits it to clear it from the board. Reuses ScrollingWordList as a
    sub-component for the this-phase accepted-word list, so it stays separate
    from the moving side pane's game-long cleared-word ring buffer.

    Manual throughout, matching the in-game menu idiom: the text field is a
    Label showing the typed word with a faux caret, and Clear/Submit/Next are
    plain clickable Labels (bounds-checked in on_mouse_press) -- no hover/click
    styling. Validation lives in GameScreen; this pane only captures input and
    shows results via the on_submit / on_next callbacks plus accept_word /
    reject / show_errors. On a rejected submit, reject() echoes the typed word
    as a dim "You typed: ..." ghost in the prompt slot above a cleared field, so
    the player compares it to the spelling suggestion and retypes fresh. Board
    clicks during SELECTING move pieces rather than fill the field (GameScreen's
    select-click rule); Clear word empties it.

    Layout, top to bottom: header, prompt + typed-word field, error messages,
    the Clear word / Submit word / Next piece controls, then the accepted-word
    list filling the remaining space.
    """

    DIVIDER_COLOR = get_color("selecting_side_pane.divider")
    PROMPT_COLOR = get_color("selecting_side_pane.prompt")
    INPUT_COLOR = get_color("selecting_side_pane.input_text")
    PLACEHOLDER_COLOR = get_color("selecting_side_pane.placeholder")
    BUTTON_COLOR = get_color("selecting_side_pane.button_text")
    ERROR_COLOR = get_color("selecting_side_pane.error_text")
    COUNT_COLOR = get_color("selecting_side_pane.word_count")
    PHASE_LABEL_COLOR = get_color("selecting_side_pane.phase_label")
    SCORE_LABEL_COLOR = get_color("selecting_side_pane.score_label")
    # Vertical lines reserved between the error area and the controls below it.
    # The error label can now stack two messages -- the rejection reason plus a
    # "Did you mean: ...?" spelling-suggestion line -- and each can wrap to two
    # lines in this narrow pane, so reserve enough that the blue controls never
    # ride up under the suggestions.
    MAX_ERRORS = 5
    # Prompt + top-edge header text come from the active language (see
    # config.get_string); the header is the SELECTING twin of the moving pane's
    # "Pieces: N" countdown label (both pinned to the very top of the right pane).

    def __init__(self, x, y, width, height, on_submit, on_next):
        # on_submit(word): Enter or the Submit label. on_next(): the Next label.
        self._on_submit = on_submit
        self._on_next = on_next
        self._typed = ""
        # Echo of the last rejected word, shown dim in the prompt slot until the
        # player accepts a word or clears the field (see reject / clear_ghost).
        self._ghost = ""
        self._batch = pyglet.graphics.Batch()

        # Sizes derived from the pane width, not fixed pixels, so they scale on
        # retina displays (where the window is sized in physical pixels).
        margin = max(6, width // 12)
        base = max(12, int(width * 0.09))
        line_h = base * 1.6
        left = x + margin
        top = y + height - margin

        self._divider = pyglet.shapes.Line(
            x, y, x, y + height, thickness=1,
            color=self.DIVIDER_COLOR, batch=self._batch,
            program=get_shape_shader(),
        )

        # Top-edge header, the SELECTING twin of the moving pane's countdown.
        # Everything below is pushed down one line from this header.
        self._header = pyglet.text.Label(
            get_string("pick_words"), font_size=base * 0.7, x=left, y=top,
            anchor_x="left", anchor_y="top",
            color=self.PHASE_LABEL_COLOR, batch=self._batch,
        )
        top = top - line_h

        # Running point total, one line under the header so it reads beside the
        # race-clock timer that shares the header (see set_score_label).
        self._score = pyglet.text.Label(
            "", font_size=base * 0.7, x=left, y=top,
            anchor_x="left", anchor_y="top",
            color=self.SCORE_LABEL_COLOR, batch=self._batch,
        )
        top = top - line_h

        # Prompt + typed-word field.
        self._prompt = pyglet.text.Label(
            get_string("type_a_word"), font_size=base * 0.7, x=left, y=top,
            anchor_x="left", anchor_y="top",
            color=self.PROMPT_COLOR, batch=self._batch,
        )
        input_y = top - line_h
        self._input = pyglet.text.Label(
            "", font_size=base, x=left, y=input_y,
            anchor_x="left", anchor_y="top",
            color=self.INPUT_COLOR, batch=self._batch,
        )

        # Error area, directly under the input so a message reads against the
        # word just typed. A single multiline Label wrapped to the pane width:
        # one reason shows at a time, but it can be a full sentence that wraps in
        # the narrow pane. MAX_ERRORS reserves the vertical space below it.
        error_top = input_y - line_h * 1.2
        error_step = base * 0.95
        self._error = pyglet.text.Label(
            "", font_size=base * 0.7, x=left, y=error_top,
            width=width - 2 * margin, multiline=True,
            anchor_x="left", anchor_y="top",
            color=self.ERROR_COLOR, batch=self._batch,
        )

        # Controls (clickable labels). Clear word empties the field; it is always
        # shown, independent of the board click-to-type rule.
        controls_top = error_top - self.MAX_ERRORS * error_step - line_h * 0.3
        self._clear_btn = pyglet.text.Label(
            get_string("clear_word"), font_size=base, x=left, y=controls_top,
            anchor_x="left", anchor_y="top",
            color=self.BUTTON_COLOR, batch=self._batch,
        )
        submit_y = controls_top - line_h
        self._submit_btn = pyglet.text.Label(
            get_string("submit_word"), font_size=base, x=left, y=submit_y,
            anchor_x="left", anchor_y="top",
            color=self.BUTTON_COLOR, batch=self._batch,
        )
        next_y = submit_y - line_h
        self._next_btn = pyglet.text.Label(
            get_string("next_piece"), font_size=base, x=left, y=next_y,
            anchor_x="left", anchor_y="top",
            color=self.BUTTON_COLOR, batch=self._batch,
        )

        # Player's lifetime dictionary size, pinned to the very bottom edge.
        count_y = y + margin
        self._count = pyglet.text.Label(
            "", font_size=base * 0.7, x=left, y=count_y,
            anchor_x="left", anchor_y="bottom",
            color=self.COUNT_COLOR, batch=self._batch,
        )

        # This-phase accepted-word list fills the space between the controls and
        # the count label, reserving one line for the latter at the bottom.
        list_top = next_y - line_h
        list_bottom = count_y + line_h
        list_height = max(line_h, list_top - list_bottom)
        self._word_list = ScrollingWordList(x, list_bottom, width, list_height)

        self._render_input()

    # --- lifecycle ---------------------------------------------------------
    def begin(self):
        """Reset for a fresh selecting phase: empty input, no errors, no ghost,
        empty this-phase word list."""
        self._typed = ""
        self._ghost = ""
        self.clear_errors()
        self._word_list.reset()
        self._render_prompt()
        self._render_input()

    def prefill(self, word):
        """Pre-load the typed-word field with `word` (upper-cased) instead of
        starting empty. Used to carry the MOVING word-hunt entry into SELECT so
        the player can confirm it with a second ENTER, or edit it first -- it does
        NOT submit. Identical to having typed the word by hand; call after begin().
        An empty/blank `word` leaves the field empty."""
        self._typed = word.upper()
        self._ghost = ""
        self.clear_errors()
        self._render_prompt()
        self._render_input()

    # --- input -------------------------------------------------------------
    def on_text(self, text):
        # Words are letters only; ignore digits/space/punctuation. Any edit
        # clears stale errors ("cleared when the user starts re-typing").
        if text.isalpha():
            self._typed += text.upper()
            self.clear_errors()
            self._render_input()

    def on_key_press(self, symbol, modifiers):
        if symbol in control_keys("game.word_backspace"):
            self._typed = self._typed[:-1]
            self.clear_errors()
            self._render_input()
        elif symbol in control_keys("game.word_submit"):
            self._on_submit(self._typed)
        # Swallow every key while selecting (there is no active piece to drive).
        return True

    def reject(self, word, messages):
        """A submitted word was rejected (misspelled / not on the board): echo it
        as a dim "You typed: WORD" ghost in the prompt slot, CLEAR the input, and
        show the reason(s). The empty field means the player's corrective typing
        starts fresh instead of appending to the failed attempt, while the ghost
        stays up (through retyping) for a side-by-side compare with any spelling
        suggestion. Cleared on the next accept_word / clear_word / begin, or
        replaced by the next rejection."""
        self._ghost = word.upper()
        self._typed = ""
        self._render_prompt()
        self._render_input()
        self.show_errors(messages)

    def clear_ghost(self):
        """Drop the rejected-word echo and restore the plain prompt (e.g. once a
        valid word opens the chooser, or the field is cleared)."""
        if self._ghost:
            self._ghost = ""
            self._render_prompt()

    def clear_word(self):
        """Reset the typed-word field to empty, dropping any ghost echo (the Clear
        word control, and the SELECT-phase spacebar)."""
        self._typed = ""
        self._ghost = ""
        self.clear_errors()
        self._render_prompt()
        self._render_input()

    def is_empty(self):
        """Whether the typed-word field is empty (no lingering word attempt).
        Drives the ENTER-on-empty -> end-selection control in GameScreen."""
        return self._typed == ""

    def on_mouse_press(self, x, y, button, modifiers):
        if self._hit(self._clear_btn, x, y):
            self.clear_word()
        elif self._hit(self._submit_btn, x, y):
            self._on_submit(self._typed)
        elif self._hit(self._next_btn, x, y):
            self._on_next()

    # --- feedback from GameScreen -----------------------------------------
    def accept_word(self, word, is_new=False, is_obscure=False, points=None):
        """A submitted word was valid and cleared: list it and reset the field.
        `is_new` shows it green when the word is new to the player's dictionary;
        a new word that is `is_obscure` (obscure tier only) shows orange.
        `points`, if given, shows the word's score ("+NN") right of the word."""
        self._word_list.add_word(word, is_new, is_obscure, points)
        self._typed = ""
        self._ghost = ""
        self.clear_errors()
        self._render_prompt()
        self._render_input()

    def set_time_label(self, seconds):
        """Show the seconds left on the clock in the top-edge header, in place of
        the 'pick words' prompt -- the twin of the moving pane's countdown, used
        only by the omniswap race variant where one clock spans both phases."""
        self._header.text = get_string("time_count", count=seconds)

    def set_word_count(self, count):
        """Show the player's lifetime dictionary size along the bottom edge."""
        self._count.text = get_string("dictionary_count", count=count)

    def set_score_label(self, points):
        """Show the running point total, one line under the header/timer."""
        self._score.text = get_string("score_count", count=points)

    def show_errors(self, messages):
        # One message at a time today; join defensively if several are passed.
        self._error.color = self.ERROR_COLOR
        self._error.text = "\n".join(messages)

    def clear_errors(self):
        self._error.color = self.ERROR_COLOR
        self._error.text = ""

    def show_prompt(self, text):
        """Show a neutral prompt in the message slot (not an error): the
        "Select which one:" cue while the disambiguation chooser is open. Reuses
        the error Label's reserved space, tinted the prompt color so it doesn't
        read as a rejection."""
        self._error.color = self.PROMPT_COLOR
        self._error.text = text

    def hide_prompt(self):
        """Clear the chooser prompt and restore the slot to error styling."""
        self.clear_errors()

    def hit_submit(self, x, y):
        """Whether (x, y) is on the Submit label -- lets GameScreen route a
        Submit click to 'confirm the highlighted candidate' while the chooser is
        open, instead of re-submitting the typed word."""
        return self._hit(self._submit_btn, x, y)

    def hit_clear(self, x, y):
        """Whether (x, y) is on the Clear label (the chooser's back-out click)."""
        return self._hit(self._clear_btn, x, y)

    # --- internals ---------------------------------------------------------
    def _render_prompt(self):
        # The prompt slot doubles as the rejected-word echo: while a ghost is set
        # it reads "You typed: WORD" dim (placeholder color); otherwise the plain
        # "Type a word:" cue in the normal prompt color.
        if self._ghost:
            self._prompt.text = get_string("you_typed", word=self._ghost)
            self._prompt.color = self.PLACEHOLDER_COLOR
        else:
            self._prompt.text = get_string("type_a_word")
            self._prompt.color = self.PROMPT_COLOR

    def _render_input(self):
        # Faux caret: a trailing underscore. Faint when nothing's typed yet.
        if self._typed:
            self._input.text = self._typed + "_"
            self._input.color = self.INPUT_COLOR
        else:
            self._input.text = "_"
            self._input.color = self.PLACEHOLDER_COLOR

    def _hit(self, label, x, y):
        # Labels are anchored top-left, so the content box runs right/down from
        # (label.x, label.y).
        left = label.x
        right = label.x + label.content_width
        top = label.y
        bottom = label.y - label.content_height
        return left <= x <= right and bottom <= y <= top

    def draw(self):
        self._batch.draw()
        self._word_list.draw()
