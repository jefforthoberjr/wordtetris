import pyglet
from views.shaders import get_shape_shader
from views.scrolling_word_list import ScrollingWordList
from config import get_color, get_string
from controls import control_keys


class MovingSelectingSidePane:
    """Right pane for the single-phase MOVING_AND_SELECTING model
    (game_screen.phase_model = rule_single_phase): the merged twin of the moving
    and selecting panes, for pre-filled-board modes where the game never leaves
    MOVING. One typed field does both jobs at once -- as the player types, every
    board gram involved lights up (the moving pane's live word-HUNT highlight,
    via on_change); pressing ENTER (or Submit) submits that same word to clear it
    (the selecting pane's submit). There is no "Select words" button (no phase to
    enter) and no "Next piece" button (no phase to leave); an optional End game
    control remains for endless modes (constellation).

    Implements the union of MovingSidePane's and SelectingSidePane's public
    surfaces so GameScreen can point BOTH self._moving_side_pane and
    self._selecting_side_pane at one instance and every existing call site works
    unchanged. The cleared-word list is the game-long one (there is no per-phase
    batch), fed by _clear_paths through add_cleared_words -- so accept_word here
    does NOT also list the word (that would double it), it only resets the field.

    Layout, top to bottom: status label (pieces/time), score, prompt + typed-word
    field, error messages, Clear word / Submit word / (End game), then the
    cleared-word list filling the rest, with the dictionary count pinned bottom.
    """

    DIVIDER_COLOR = get_color("selecting_side_pane.divider")
    PROMPT_COLOR = get_color("selecting_side_pane.prompt")
    INPUT_COLOR = get_color("selecting_side_pane.input_text")
    PLACEHOLDER_COLOR = get_color("selecting_side_pane.placeholder")
    BUTTON_COLOR = get_color("selecting_side_pane.button_text")
    ERROR_COLOR = get_color("selecting_side_pane.error_text")
    COUNT_COLOR = get_color("selecting_side_pane.word_count")
    STATUS_COLOR = get_color("moving_side_pane.phase_label")
    SCORE_COLOR = get_color("selecting_side_pane.score_label")
    # Mirrors SelectingSidePane: the error label can stack a rejection reason plus
    # a spelling suggestion, each wrapping in this narrow pane, so reserve room.
    MAX_ERRORS = 5

    def __init__(self, x, y, width, height, on_submit, on_change=None,
                 on_end=None, show_end=False):
        # on_submit(word): ENTER or the Submit control. on_change(text): the live
        # hunt-highlight callback, fired after every edit (None -> no highlight).
        # on_end(): the End game control, built only when show_end (constellation).
        self._on_submit = on_submit
        self._on_change = on_change
        self._on_end = on_end
        self._typed = ""
        # Echo of the last rejected word, shown dim in the prompt slot until the
        # player accepts a word or clears the field (see reject / clear_ghost).
        self._ghost = ""
        self._x = x
        self._y = y
        self._width = width
        self._height = height
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

        # Top-edge status label: the moving pane's "Pieces: N" / countdown twin.
        self._status = pyglet.text.Label(
            "", font_size=base * 0.7, x=left, y=top,
            anchor_x="left", anchor_y="top",
            color=self.STATUS_COLOR, batch=self._batch,
        )
        top = top - line_h

        # Running point total, one line under the status label.
        self._score = pyglet.text.Label(
            "", font_size=base * 0.7, x=left, y=top,
            anchor_x="left", anchor_y="top",
            color=self.SCORE_COLOR, batch=self._batch,
        )
        top = top - line_h

        # Prompt + typed-word field (doubles as the hunt field).
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

        # Error area, directly under the input so a message reads against the word
        # just typed. One multiline Label wrapped to the pane width.
        error_top = input_y - line_h * 1.2
        error_step = base * 0.95
        self._error = pyglet.text.Label(
            "", font_size=base * 0.7, x=left, y=error_top,
            width=width - 2 * margin, multiline=True,
            anchor_x="left", anchor_y="top",
            color=self.ERROR_COLOR, batch=self._batch,
        )

        # Controls: Clear word (always) then Submit word; no Next piece (no phase
        # to leave). Clickable labels, bounds-checked in on_mouse_press.
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

        # Optional End game control, one line under Submit -- built only when the
        # host mode asks for it (constellation, which never ends on its own).
        if show_end:
            end_y = submit_y - line_h
            self._end_btn = pyglet.text.Label(
                get_string("end_game"), font_size=base, x=left, y=end_y,
                anchor_x="left", anchor_y="top",
                color=self.BUTTON_COLOR, batch=self._batch,
            )
            controls_bottom = end_y
        else:
            self._end_btn = None
            controls_bottom = submit_y

        # Player's lifetime dictionary size, pinned to the very bottom edge.
        count_y = y + margin
        self._count = pyglet.text.Label(
            "", font_size=base * 0.7, x=left, y=count_y,
            anchor_x="left", anchor_y="bottom",
            color=self.COUNT_COLOR, batch=self._batch,
        )

        # The cleared-word list fills the space between the controls and the count
        # label. Game-long (there is no per-phase batch in single-phase).
        list_top = controls_bottom - line_h
        list_bottom = count_y + line_h
        list_height = max(line_h, list_top - list_bottom)
        self._word_list = ScrollingWordList(x, list_bottom, width, list_height)

        self._render_input()

    @property
    def x(self):
        return self._x

    @property
    def width(self):
        return self._width

    # --- lifecycle ---------------------------------------------------------
    def begin(self):
        """Fresh input: empty field, no errors, no ghost. Does NOT touch the
        cleared-word list (it is game-long here, unlike SelectingSidePane's
        per-phase list). Called once when single-phase play starts."""
        self._typed = ""
        self._ghost = ""
        self.clear_errors()
        self._render_prompt()
        self._render_input()

    def reset(self):
        """New game: clear the word list and empty the field/highlight."""
        self._word_list.reset()
        self.clear_word()

    def prefill(self, word):
        """Pre-load the field with `word` (upper-cased). Present for API parity
        with SelectingSidePane; unused by the single-phase flow (no ENTER carries
        a hunt word across a phase boundary here)."""
        self._typed = word.upper()
        self._ghost = ""
        self.clear_errors()
        self._render_prompt()
        self._render_input()
        self._notify()

    # --- input -------------------------------------------------------------
    def on_text(self, text):
        # Letters only; ignore digits/space/punctuation. Any edit clears stale
        # errors and re-fires the live hunt highlight.
        if text.isalpha():
            self._typed += text.upper()
            self.clear_errors()
            self._render_input()
            self._notify()

    def on_key_press(self, symbol, modifiers):
        """Backspace edits; word_submit (ENTER) submits the typed word; word_clear
        (spacebar) empties the field. Returns True when it consumes the key, so
        GameScreen knows not to pass it on to the moving mode (which is how the
        merged field keeps ENTER from re-triggering a mode's open-select route)."""
        if symbol in control_keys("game.word_backspace"):
            if self._typed:
                self._typed = self._typed[:-1]
                self.clear_errors()
                self._render_input()
                self._notify()
            return True
        if symbol in control_keys("game.word_submit"):
            self._on_submit(self._typed)
            return True
        if symbol in control_keys("game.word_clear"):
            self.clear_word()
            return True
        return False

    def on_mouse_press(self, x, y, button, modifiers):
        """Route a click on Clear / Submit / End. Returns True if a control was
        hit (so GameScreen consumes the click before the board / moving mode);
        board clicks fall through unconsumed."""
        if self._hit(self._clear_btn, x, y):
            self.clear_word()
            return True
        if self._hit(self._submit_btn, x, y):
            self._on_submit(self._typed)
            return True
        if self._end_btn is not None and self._hit(self._end_btn, x, y):
            self._on_end()
            return True
        return False

    # --- moving-side field API (hunt highlight) ---------------------------
    def hunt_text(self):
        """The word currently typed (the field doubles as the hunt field)."""
        return self._typed

    def clear_hunt(self):
        """Empty the field and drop its highlight. Same as clear_word; kept for
        the MovingSidePane name GameScreen calls on a phase change (a no-op path
        in single-phase, which never changes phase)."""
        self.clear_word()

    def clear_word(self):
        """Reset the typed field to empty, dropping any ghost echo and clearing
        the live highlight (Clear word control, and the word_clear key). Only
        re-fires the highlight callback when the field actually held text -- so an
        empty->empty clear (e.g. the clear_hunt on the opening phase change, before
        the board exists) never reaches into the board. Mirrors MovingSidePane."""
        had_text = bool(self._typed)
        self._typed = ""
        self._ghost = ""
        self.clear_errors()
        self._render_prompt()
        self._render_input()
        if had_text:
            self._notify()

    def is_empty(self):
        return self._typed == ""

    # --- feedback from GameScreen -----------------------------------------
    def accept_word(self, word, is_new=False, is_obscure=False, points=None):
        """A submitted word was valid and cleared: reset the field. It is NOT
        listed here -- _clear_paths already listed it through add_cleared_words
        (the game-long sink), and listing it again would double it."""
        self._typed = ""
        self._ghost = ""
        self.clear_errors()
        self._render_prompt()
        self._render_input()
        self._notify()

    def reject(self, word, messages):
        """A submitted word was rejected: echo it dim as "You typed: WORD" in the
        prompt slot, clear the field (corrective typing starts fresh), drop the
        highlight, and show the reason(s)."""
        self._ghost = word.upper()
        self._typed = ""
        self._render_prompt()
        self._render_input()
        self._notify()
        self.show_errors(messages)

    def clear_ghost(self):
        if self._ghost:
            self._ghost = ""
            self._render_prompt()

    def add_cleared_words(self, words, new_flags=None, obscure_flags=None, scores=None):
        """The game-long cleared-word list sink (_clear_paths), newest on top."""
        self._word_list.add_words(words, new_flags, obscure_flags, scores)

    def word_at(self, x, y):
        """The cleared word displayed at pixel (x, y), or None. Drives the
        player-word-piece feature (omniswap)."""
        if x < self._x or x > self._x + self._width:
            return None
        return self._word_list.word_at(x, y)

    def hit_select(self, x, y):
        """No Select button in single-phase; there is no phase to enter."""
        return False

    def hit_submit(self, x, y):
        return self._hit(self._submit_btn, x, y)

    def hit_clear(self, x, y):
        return self._hit(self._clear_btn, x, y)

    # --- status / score / count labels ------------------------------------
    def set_phase_label(self, count):
        self._status.text = get_string("pieces_count", count=count)

    def set_time_label(self, seconds):
        self._status.text = get_string("time_count", count=seconds)

    def set_finished_label(self):
        self._status.text = get_string("finished")

    def set_score_label(self, points):
        self._score.text = get_string("score_count", count=points)

    def set_word_count(self, count):
        self._count.text = get_string("dictionary_count", count=count)

    # --- error / prompt slot ----------------------------------------------
    def show_errors(self, messages):
        self._error.color = self.ERROR_COLOR
        self._error.text = "\n".join(messages)

    def clear_errors(self):
        self._error.color = self.ERROR_COLOR
        self._error.text = ""

    def show_prompt(self, text):
        """Neutral prompt in the message slot (the disambiguation "Select which
        one:" cue), tinted so it doesn't read as a rejection."""
        self._error.color = self.PROMPT_COLOR
        self._error.text = text

    def hide_prompt(self):
        self.clear_errors()

    # --- internals ---------------------------------------------------------
    def _notify(self):
        if self._on_change is not None:
            self._on_change(self._typed)

    def _render_prompt(self):
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
        left = label.x
        right = label.x + label.content_width
        top = label.y
        bottom = label.y - label.content_height
        return left <= x <= right and bottom <= y <= top

    def draw(self):
        self._batch.draw()
        self._word_list.draw()
