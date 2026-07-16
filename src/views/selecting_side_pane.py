import pyglet
from views.shaders import get_shape_shader
from views.scrolling_word_list import ScrollingWordList
from views.textures import error_icon_image
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
    styling. An optional End game control (show_end) sits below Next: a manual
    finish for modes with no natural close -- constellation, where a piece never
    shrinks the board and (in the endless preset) no victory rule fires, so the
    player would otherwise be stuck typing forever. Validation lives in GameScreen; this pane only captures input and
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
    MISSING_COLOR = get_color("selecting_side_pane.missing_letter")
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

    def __init__(self, x, y, width, height, on_submit, on_next,
                 on_end=None, show_end=False, show_clear=True,
                 show_submit=True, show_next=True, error_display="text"):
        # on_submit(word): Enter or the Submit label. on_next(): the Next label.
        # on_end(): the End game label, present only when show_end (constellation);
        # None everywhere else, so the button is neither built nor clickable.
        # show_clear / show_submit / show_next (game_screen.show_*_button): drop a
        # button's clickable label independently; a hidden button takes no vertical
        # slot and is skipped in on_mouse_press. The keyboard route stays live.
        self._on_submit = on_submit
        self._on_next = on_next
        self._on_end = on_end
        # "text" shows the rejection reason as words; "icon" shows a reason icon in
        # the same slot (game_screen.error_display). See show_errors / _set_error_icon.
        self._error_display = error_display
        # Live error-icon sprite (icon mode only), or None when the slot shows text.
        self._error_sprite = None
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

        # Prompt + typed-word field. The prompt is a FormattedDocument label (not a
        # plain Label) so the "You typed: WORD" ghost can redden individual missing
        # letters per _render_prompt; a plain Label paints one color for all text.
        self._prompt_font = base * 0.7
        self._ghost_missing = None
        self._prompt_doc = pyglet.text.document.FormattedDocument("")
        self._prompt = pyglet.text.DocumentLabel(
            document=self._prompt_doc, x=left, y=top,
            anchor_x="left", anchor_y="top", batch=self._batch,
        )
        self._render_prompt()
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
        # Center + max box of the error area, reused as the error-icon slot: fit an
        # icon inside the same space the text messages would occupy (icon mode).
        self._err_box_w = width - 2 * margin
        self._err_box_h = self.MAX_ERRORS * error_step
        self._err_box_cx = left + self._err_box_w / 2
        self._err_box_cy = error_top - self._err_box_h / 2

        # Controls (clickable labels), stacked top-to-bottom in the fixed order
        # Clear / Submit / Next / End. Each is built only when its show flag is set;
        # a hidden button takes no vertical slot (the stack closes up) and stays out
        # of on_mouse_press. controls_bottom tracks the last built button so the
        # word list starts one line under it -- if all are hidden it sits just below
        # the error area. See _add_button.
        controls_top = error_top - self.MAX_ERRORS * error_step - line_h * 0.3
        self._line_h = line_h
        self._base = base
        self._left = left
        self._btn_y = controls_top
        self._controls_bottom = controls_top
        self._clear_btn = self._add_button("clear_word") if show_clear else None
        self._submit_btn = self._add_button("submit_word") if show_submit else None
        self._next_btn = self._add_button("next_piece") if show_next else None
        self._end_btn = self._add_button("end_game") if show_end else None
        controls_bottom = self._controls_bottom

        # Player's lifetime dictionary size, pinned to the very bottom edge.
        count_y = y + margin
        self._count = pyglet.text.Label(
            "", font_size=base * 0.7, x=left, y=count_y,
            anchor_x="left", anchor_y="bottom",
            color=self.COUNT_COLOR, batch=self._batch,
        )

        # This-phase accepted-word list fills the space between the controls and
        # the count label, reserving one line for the latter at the bottom.
        list_top = controls_bottom - line_h
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

    def reject(self, word, messages, reason=None, missing=None):
        """A submitted word was rejected (misspelled / not on the board): echo it
        as a dim "You typed: WORD" ghost in the prompt slot, CLEAR the input, and
        show the reason(s). The empty field means the player's corrective typing
        starts fresh instead of appending to the failed attempt, while the ghost
        stays up (through retyping) for a side-by-side compare with any spelling
        suggestion. Cleared on the next accept_word / clear_word / begin, or
        replaced by the next rejection. `missing` (one bool per letter, or None)
        reddens the ghost letters that don't exist on the board."""
        self._ghost = word.upper()
        self._ghost_missing = missing
        self._typed = ""
        self._render_prompt()
        self._render_input()
        self.show_errors(messages, reason)

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
        if self._clear_btn is not None and self._hit(self._clear_btn, x, y):
            self.clear_word()
        elif self._submit_btn is not None and self._hit(self._submit_btn, x, y):
            self._on_submit(self._typed)
        elif self._next_btn is not None and self._hit(self._next_btn, x, y):
            self._on_next()
        elif self._end_btn is not None and self._hit(self._end_btn, x, y):
            self._on_end()

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

    def show_errors(self, messages, reason=None):
        # Icon mode: show the reason's icon in place of the text (and drop any
        # extra lines like the "did you mean?" suggestion). Reasons with no icon
        # fall through to the text message. One message at a time today; join
        # defensively if several are passed.
        if self._error_display == "icon" and self._set_error_icon(reason):
            self._error.text = ""
            return
        self._clear_error_icon()
        self._error.color = self.ERROR_COLOR
        self._error.text = "\n".join(messages)

    def clear_errors(self):
        self._clear_error_icon()
        self._error.color = self.ERROR_COLOR
        self._error.text = ""

    def _set_error_icon(self, reason):
        """Show the error icon for `reason`, scaled to fit the error slot. Returns
        False (and shows nothing) when the reason has no icon, so the caller falls
        back to text."""
        image = error_icon_image(reason, self._err_box_w)
        if image is None:
            return False
        self._clear_error_icon()
        sprite = pyglet.sprite.Sprite(image, batch=self._batch)
        sprite.scale = min(self._err_box_w / image.width,
                           self._err_box_h / image.height)
        sprite.x = self._err_box_cx
        sprite.y = self._err_box_cy
        self._error_sprite = sprite
        return True

    def _clear_error_icon(self):
        if self._error_sprite is not None:
            self._error_sprite.delete()
            self._error_sprite = None

    def show_prompt(self, text):
        """Show a neutral prompt in the message slot (not an error): the
        "Select which one:" cue while the disambiguation chooser is open. Reuses
        the error Label's reserved space, tinted the prompt color so it doesn't
        read as a rejection."""
        self._clear_error_icon()
        self._error.color = self.PROMPT_COLOR
        self._error.text = text

    def hide_prompt(self):
        """Clear the chooser prompt and restore the slot to error styling."""
        self.clear_errors()

    def hit_submit(self, x, y):
        """Whether (x, y) is on the Submit label -- lets GameScreen route a
        Submit click to 'confirm the highlighted candidate' while the chooser is
        open, instead of re-submitting the typed word. False when Submit is hidden."""
        return self._submit_btn is not None and self._hit(self._submit_btn, x, y)

    def hit_clear(self, x, y):
        """Whether (x, y) is on the Clear label (the chooser's back-out click).
        False when Clear is hidden."""
        return self._clear_btn is not None and self._hit(self._clear_btn, x, y)

    # --- internals ---------------------------------------------------------
    def _render_prompt(self):
        # The prompt slot doubles as the rejected-word echo: while a ghost is set
        # it reads "You typed: WORD" dim (placeholder color); otherwise the plain
        # "Type a word:" cue in the normal prompt color.
        if self._ghost:
            self._set_prompt(get_string("you_typed", word=self._ghost),
                             self.PLACEHOLDER_COLOR,
                             word=self._ghost, missing=self._ghost_missing)
        else:
            self._set_prompt(get_string("type_a_word"), self.PROMPT_COLOR)

    def _set_prompt(self, text, base_color, word=None, missing=None):
        # Paint the whole prompt in base_color, then (ghost only) redden the
        # letters flagged in `missing` -- located by finding `word` inside the
        # rendered "You typed: WORD" string, so a template change moves with it.
        self._prompt_doc.text = text
        self._prompt_doc.set_style(0, len(text), {
            "font_size": self._prompt_font,
            "color": base_color,
        })
        if word and missing:
            start = text.rfind(word)
            if start >= 0:
                for i, gone in enumerate(missing):
                    if gone:
                        self._prompt_doc.set_style(
                            start + i, start + i + 1, {"color": self.MISSING_COLOR})

    def _render_input(self):
        # Faux caret: a trailing underscore. Faint when nothing's typed yet.
        if self._typed:
            self._input.text = self._typed + "_"
            self._input.color = self.INPUT_COLOR
        else:
            self._input.text = "_"
            self._input.color = self.PLACEHOLDER_COLOR

    def _add_button(self, text_key):
        # Build one control label at the running stack cursor, advance the cursor
        # down one line, and record its line as the current controls_bottom. Only
        # called for buttons whose show flag is set, so hidden ones close the gap.
        btn = pyglet.text.Label(
            get_string(text_key), font_size=self._base, x=self._left, y=self._btn_y,
            anchor_x="left", anchor_y="top",
            color=self.BUTTON_COLOR, batch=self._batch,
        )
        self._controls_bottom = self._btn_y
        self._btn_y -= self._line_h
        return btn

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
