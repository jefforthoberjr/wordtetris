import pyglet
from views.shaders import get_shape_shader
from views.scrolling_word_list import ScrollingWordList
from config import get_color, get_string
from controls import control_keys


class MovingSidePane:
    """Right pane shown during the MOVING phase. Owns the divider line that
    visually separates it from the grid area on its left edge, a word-HUNT input
    field at the top, and a scrolling list of the words the player has cleared.

    The hunt field: the player types a word and every gram on the board involved
    in it lights up (the highlight itself lives in GameScreen / hunt_highlight;
    this pane only captures the text and reports each change via on_change). It
    has no submit or buttons -- highlighting updates live as the player types, and
    the field is cleared when MOVING is left (GameScreen calls clear_hunt on the
    phase change), so nothing lingers into the next MOVING phase.
    """

    DIVIDER_COLOR = get_color("moving_side_pane.divider")
    COUNT_COLOR = get_color("moving_side_pane.word_count")
    PHASE_LABEL_COLOR = get_color("moving_side_pane.phase_label")
    SCORE_LABEL_COLOR = get_color("moving_side_pane.score_label")
    HUNT_PROMPT_COLOR = get_color("moving_side_pane.hunt_prompt")
    HUNT_INPUT_COLOR = get_color("moving_side_pane.hunt_input")
    HUNT_PLACEHOLDER_COLOR = get_color("moving_side_pane.hunt_placeholder")

    def __init__(self, x, y, width, height, on_change=None):
        # on_change(text): called with the current hunt text after every edit so
        # GameScreen can re-highlight. Optional so the pane is usable standalone.
        self._on_change = on_change
        self._hunt_text = ""
        self._x = x
        self._y = y
        self._width = width
        self._height = height
        self._batch = pyglet.graphics.Batch()

        # Sized from the pane width (not fixed pixels) so it scales on retina
        # displays, matching the selecting side pane.
        margin = max(6, width // 12)
        base = max(12, int(width * 0.09))
        line_h = base * 1.6

        # Divider sits on the pane's left edge, between it and the grid.
        self._divider = pyglet.shapes.Line(
            x, y, x, y + height,
            thickness=1, color=self.DIVIDER_COLOR, batch=self._batch,
            program=get_shape_shader()
        )

        # Word-hunt field pinned to the very top: a prompt then the typed word
        # with a faux caret (the SelectingSidePane idiom).
        top = y + height - margin
        self._hunt_prompt = pyglet.text.Label(
            get_string("hunt_a_word"), font_size=base * 0.7, x=x + margin, y=top,
            anchor_x="left", anchor_y="top",
            color=self.HUNT_PROMPT_COLOR, batch=self._batch,
        )
        input_y = top - line_h
        self._hunt_input = pyglet.text.Label(
            "", font_size=base, x=x + margin, y=input_y,
            anchor_x="left", anchor_y="top",
            color=self.HUNT_INPUT_COLOR, batch=self._batch,
        )

        # Placements left until the next selection phase ("Pieces: N"), now one
        # field-height below the hunt input rather than at the very top.
        phase_label_y = input_y - line_h
        self._phase_label = pyglet.text.Label(
            "", font_size=base * 0.7, x=x + margin, y=phase_label_y,
            anchor_x="left", anchor_y="top",
            color=self.PHASE_LABEL_COLOR, batch=self._batch,
        )

        # Running point total, one line under the pieces/time label so it reads
        # right beside the timer (see set_score_label / models/scoring.py).
        score_label_y = phase_label_y - line_h
        self._score = pyglet.text.Label(
            "", font_size=base * 0.7, x=x + margin, y=score_label_y,
            anchor_x="left", anchor_y="top",
            color=self.SCORE_LABEL_COLOR, batch=self._batch,
        )

        # Player's lifetime dictionary size, pinned to the very bottom edge.
        count_y = y + margin
        self._count = pyglet.text.Label(
            "", font_size=base * 0.7, x=x + margin, y=count_y,
            anchor_x="left", anchor_y="bottom",
            color=self.COUNT_COLOR, batch=self._batch,
        )

        # The cleared-word list fills the pane between the count label (bottom)
        # and the score label (top), reserving one line for each.
        list_top = score_label_y - line_h
        list_bottom = count_y + line_h
        list_height = max(line_h, list_top - list_bottom)
        self._word_list = ScrollingWordList(x, list_bottom, width, list_height)

        self._render_hunt_input()

    @property
    def x(self):
        return self._x

    @property
    def width(self):
        return self._width

    def add_cleared_words(self, words, new_flags=None, obscure_flags=None):
        """Show words just cleared, newest on top. `new_flags` / `obscure_flags`,
        if given, mark which words are new to the player's dictionary (green) and
        which are obscure-tier only (orange -- when also new)."""
        self._word_list.add_words(words, new_flags, obscure_flags)

    def word_at(self, x, y):
        """The cleared word displayed at pixel (x, y), or None if the click is
        outside the pane or on a blank row. Drives the player word-piece feature
        (a click on a word swaps the live piece for that word; see GameScreen)."""
        if x < self._x or x > self._x + self._width:
            return None
        return self._word_list.word_at(x, y)

    def set_word_count(self, count):
        """Show the player's lifetime dictionary size along the bottom edge."""
        self._count.text = get_string("dictionary_count", count=count)

    def set_phase_label(self, count):
        """Show how many more pieces until the next selection phase, top edge."""
        self._phase_label.text = get_string("pieces_count", count=count)

    def set_time_label(self, seconds):
        """Show the seconds left in the moving phase, top edge -- the
        MOVING_OMNISWAP countdown, in place of the pieces-until-select count."""
        self._phase_label.text = get_string("time_count", count=seconds)

    def set_score_label(self, points):
        """Show the running point total, one line under the timer/pieces label."""
        self._score.text = get_string("score_count", count=points)

    def set_finished_label(self):
        """Replace the top-edge countdown / pieces label with the game-over text,
        shown the moment the game ends (e.g. the omniswap race clock hits zero)."""
        self._phase_label.text = get_string("finished")

    def reset(self):
        """Clear the cleared-words list back to empty for a new game, and empty
        the hunt field."""
        self._word_list.reset()
        self.clear_hunt()

    # --- word-hunt input ---------------------------------------------------
    def on_text(self, text):
        """A typed character during MOVING. Words are letters only; digits, space
        and punctuation are ignored -- so the movement/rotate keys that emit text
        (none are letters now) never leak into the hunt field. Highlighting
        updates live via on_change."""
        if text.isalpha():
            self._hunt_text += text.upper()
            self._render_hunt_input()
            self._notify()

    def on_key_press(self, symbol, modifiers):
        """Backspace deletes the last hunted letter. Returns True if it consumed
        the key so GameScreen knows not to pass it on to the moving mode."""
        if symbol in control_keys("game.word_backspace"):
            if self._hunt_text:
                self._hunt_text = self._hunt_text[:-1]
                self._render_hunt_input()
                self._notify()
            return True
        return False

    def clear_hunt(self):
        """Empty the hunt field (GameScreen calls this when MOVING is left, so no
        highlight lingers into the next MOVING phase)."""
        if self._hunt_text:
            self._hunt_text = ""
            self._render_hunt_input()
            self._notify()
        else:
            self._render_hunt_input()

    def hunt_text(self):
        """The word currently typed in the hunt field (upper-case, may be empty)."""
        return self._hunt_text

    def _notify(self):
        if self._on_change is not None:
            self._on_change(self._hunt_text)

    def _render_hunt_input(self):
        # Faux caret: a trailing underscore, faint when nothing's typed yet
        # (mirrors SelectingSidePane._render_input).
        if self._hunt_text:
            self._hunt_input.text = self._hunt_text + "_"
            self._hunt_input.color = self.HUNT_INPUT_COLOR
        else:
            self._hunt_input.text = "_"
            self._hunt_input.color = self.HUNT_PLACEHOLDER_COLOR

    def draw(self):
        self._batch.draw()
        self._word_list.draw()
