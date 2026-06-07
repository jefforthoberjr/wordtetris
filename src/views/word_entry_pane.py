import pyglet
from views.shaders import get_shape_shader
from views.scrolling_word_list import ScrollingWordList
from config import get_color


class WordEntryPane:
    """Right-pane UI for the interactive word-selection phase (the SELECTING
    game state): the player types a word and submits it to clear it from the
    board. Reuses ScrollingWordList as a sub-component for the this-phase
    accepted-word list, so it stays separate from the side pane's game-long
    cleared-word ring buffer.

    Manual throughout, matching the in-game menu idiom: the text field is a
    Label showing the typed word with a faux caret, and Submit/Next are plain
    clickable Labels (bounds-checked in on_mouse_press) -- no hover/click
    styling. Validation lives in GameScreen; this pane only captures input and
    shows results via the on_submit / on_next callbacks plus accept_word /
    show_errors.

    Layout, top to bottom: prompt + typed-word field, error messages, the
    Submit word and Next piece controls, then the accepted-word list filling
    the remaining space.
    """

    DIVIDER_COLOR = get_color("selection.divider")
    PROMPT_COLOR = get_color("selection.prompt")
    INPUT_COLOR = get_color("selection.input_text")
    PLACEHOLDER_COLOR = get_color("selection.placeholder")
    BUTTON_COLOR = get_color("selection.button_text")
    ERROR_COLOR = get_color("selection.error_text")
    MAX_ERRORS = 3
    PROMPT = "Type a word:"

    def __init__(self, x, y, width, height, on_submit, on_next):
        # on_submit(word): Enter or the Submit label. on_next(): the Next label.
        self._on_submit = on_submit
        self._on_next = on_next
        self._typed = ""
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

        # Prompt + typed-word field.
        self._prompt = pyglet.text.Label(
            self.PROMPT, font_size=base * 0.7, x=left, y=top,
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

        # Controls (clickable labels).
        controls_top = error_top - self.MAX_ERRORS * error_step - line_h * 0.3
        self._submit_btn = pyglet.text.Label(
            "Submit word", font_size=base, x=left, y=controls_top,
            anchor_x="left", anchor_y="top",
            color=self.BUTTON_COLOR, batch=self._batch,
        )
        next_y = controls_top - line_h
        self._next_btn = pyglet.text.Label(
            "Next piece", font_size=base, x=left, y=next_y,
            anchor_x="left", anchor_y="top",
            color=self.BUTTON_COLOR, batch=self._batch,
        )

        # This-phase accepted-word list fills whatever space is left.
        list_top = next_y - line_h
        list_bottom = y + margin
        list_height = max(line_h, list_top - list_bottom)
        self._word_list = ScrollingWordList(x, list_bottom, width, list_height)

        self._render_input()

    # --- lifecycle ---------------------------------------------------------
    def begin(self):
        """Reset for a fresh selecting phase: empty input, no errors, empty
        this-phase word list."""
        self._typed = ""
        self.clear_errors()
        self._word_list.reset()
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
        if symbol == pyglet.window.key.BACKSPACE:
            self._typed = self._typed[:-1]
            self.clear_errors()
            self._render_input()
        elif symbol in (pyglet.window.key.ENTER, pyglet.window.key.RETURN):
            self._on_submit(self._typed)
        # Swallow every key while selecting (there is no active piece to drive).
        return True

    def on_mouse_press(self, x, y, button, modifiers):
        if self._hit(self._submit_btn, x, y):
            self._on_submit(self._typed)
        elif self._hit(self._next_btn, x, y):
            self._on_next()

    # --- feedback from GameScreen -----------------------------------------
    def accept_word(self, word, is_new=False):
        """A submitted word was valid and cleared: list it and reset the field.
        `is_new` shows it green when the word is new to the player's dictionary."""
        self._word_list.add_word(word, is_new)
        self._typed = ""
        self.clear_errors()
        self._render_input()

    def show_errors(self, messages):
        # One message at a time today; join defensively if several are passed.
        self._error.text = "\n".join(messages)

    def clear_errors(self):
        self._error.text = ""

    # --- internals ---------------------------------------------------------
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
