import math
import pyglet
from config import get_color, get_string
from controls import control_keys, control_names


class ControlsScreen:
    """The "Controls" reference (main menu -> Controls): a read-only, two-column
    listing of every player control, with a section per GRID STYLE because the
    same physical keys mean different things on each board.

    Every key shown is resolved through controls.control_names, so this page
    always reflects the live controls.yaml -- rebinding a key there changes what
    is printed here, with no edit to this screen. What it does NOT track is
    config.yaml: the grid sections are all listed side by side regardless of which
    grid is active, which is the point (it is a reference for all three, not a
    readout of the current game). Rows whose control is gated on a rule carry that
    condition in their own text.

    Static content, so it is all built once in __init__; the only interaction is
    Back / ESCAPE.
    """

    # (heading, [(action, spec)]) where spec is a list of PARTS concatenated to
    # form the key text: a part starting with LITERAL is printed as-is (for
    # joiners like " + " and controls with no single rebindable key), anything
    # else is a controls.yaml path resolved to its live binding. Several parts let
    # one row show a whole chord or a set of direction keys ("LEFT / RIGHT"),
    # which is what most of the movement rows actually are.
    _LITERAL = "="

    def _sections(self):
        sep = self._LITERAL + " / "
        return [
            (get_string("controls_section_menus"), [
                ("Move highlight", ["main_menu.nav_up", sep, "main_menu.nav_down"]),
                ("Select item", ["main_menu.select"]),
                ("Back / pause", ["game.pause"]),
                ("Debug panel", ["global.debug_panel_toggle"]),
            ]),
            (get_string("controls_section_square"), [
                ("Move piece (4 cardinals)", ["game.move_left", sep,
                                              "game.move_right", sep,
                                              "game.move_up", sep,
                                              "game.move_down"]),
            ]),
            (get_string("controls_section_hex"), [
                ("Up-left / up-right", ["game.move_left", sep, "game.move_right"]),
                ("Down-left / down-right", ["game.hex_down_modifier",
                                            self._LITERAL + " + ",
                                            "game.move_left", sep,
                                            "game.move_right"]),
                ("Straight up / down", ["game.move_up", sep, "game.move_down"]),
            ]),
            (get_string("controls_section_triangle"), [
                ("Step left / right", ["game.move_left", sep, "game.move_right"]),
                ("Flip across flat edge", ["game.move_up", sep, "game.move_down"]),
                ("  (the flip lands BELOW a", []),
                ("  point-up cell, ABOVE a", []),
                ("  point-down one)", []),
            ]),
            (get_string("controls_section_bigcell"), [
                ("Up-left / up-right", ["game.move_left", sep, "game.move_right"]),
                ("Down-left / down-right", ["game.hex_down_modifier",
                                            self._LITERAL + " + ",
                                            "game.move_left", sep,
                                            "game.move_right"]),
                ("Straight up / down", ["game.move_up", sep, "game.move_down"]),
                ("  (a big cell sits on the", []),
                ("  hex lattice, so it moves", []),
                ("  in six directions)", []),
            ]),
            (get_string("controls_section_piece"), [
                ("Rotate clockwise", ["game.rotate_clockwise"]),
                ("Rotate counter-clockwise", ["game.rotate_counterclockwise"]),
                ("Drop / place piece", ["game.place"]),
                ("Move piece (mouse)", ["mouse.move_primary"]),
                ("Change a cell's gram (mouse)", ["mouse.gram_manipulate"]),
            ]),
            (get_string("controls_section_words"), [
                ("Type letters", [self._LITERAL + "A-Z"]),
                ("Delete last letter", ["game.word_backspace"]),
                ("Clear the word", ["game.word_clear"]),
                ("Submit the word", ["game.word_submit"]),
                ("End the select phase", ["game.selection_end"]),
                ("Cycle which word clears", ["game.word_cycle_prev", sep,
                                             "game.word_cycle_next"]),
            ]),
        ]

    def __init__(self, window, screen_manager, back_screen_type):
        self._window = window
        self._screen_manager = screen_manager
        self._back_screen_type = back_screen_type
        self._highlight_color = get_color("menu.highlight")
        self._normal_color = get_color("menu.normal")
        self._batch = pyglet.graphics.Batch()
        # Kept so the labels aren't garbage-collected out of the batch.
        self._labels = []

        self._title = pyglet.text.Label(
            get_string("controls_title"),
            font_size=36,
            x=math.floor(window.width / 2),
            y=window.height - 60,
            anchor_x="center", anchor_y="center",
            color=self._normal_color,
            batch=self._batch,
        )
        self._build_columns()

        # The one interactive row: Back, at the bottom center.
        self._back_label = pyglet.text.Label(
            get_string("menu_back"),
            font_size=28,
            x=math.floor(window.width / 2),
            y=50,
            anchor_x="center", anchor_y="center",
            color=self._highlight_color,
            batch=self._batch,
        )

    def _build_columns(self):
        """Lay the sections into two columns, filling the left one first. Sections
        are kept whole -- a section starts in the right column rather than
        splitting across the two."""
        sections = self._sections()
        column_x = [
            math.floor(self._window.width * 0.06),
            math.floor(self._window.width * 0.52),
        ]
        top_y = self._window.height - 130
        line_height = 30
        section_gap = 22
        # Rows that fit above the Back row.
        column_capacity = math.floor((top_y - 100) / line_height)

        column = 0
        y = top_y
        used = 0
        for heading, rows in sections:
            needed = len(rows) + 2
            if used + needed > column_capacity and column == 0:
                column = 1
                y = top_y
                used = 0
            self._add_label(heading, column_x[column], y, 24,
                            self._highlight_color)
            y -= line_height
            used += 1
            for action, binding in rows:
                self._add_row(action, binding, column_x[column], y)
                y -= line_height
                used += 1
            y -= section_gap
            used += 1

    def _add_row(self, action, spec, x, y):
        """One "action .... KEYS" line. An empty spec is a continuation line (prose
        under a row, no keys of its own)."""
        self._add_label(action, x, y, 18, self._normal_color)
        keys = self._spec_text(spec)
        if keys:
            self._add_label(keys, x + self._key_offset(), y,
                            18, self._normal_color)

    def _spec_text(self, spec):
        """Render a row's parts to one key string (see _sections)."""
        parts = []
        for part in spec:
            if part.startswith(self._LITERAL):
                parts.append(part[len(self._LITERAL):])
            else:
                parts.append(control_names(part))
        return "".join(parts)

    def _key_offset(self):
        """How far right of an action's text its keys are printed. Must stay under
        the gap between the two columns (_build_columns) or a long chord in the
        left column runs into the right column's action text."""
        return math.floor(self._window.width * 0.26)

    def _add_label(self, text, x, y, font_size, color):
        label = pyglet.text.Label(
            text,
            font_size=font_size,
            x=x, y=y,
            anchor_x="left", anchor_y="center",
            color=color,
            batch=self._batch,
        )
        self._labels.append(label)

    def _back(self):
        self._screen_manager.switch_to(self._back_screen_type)

    def _over_back(self, x, y):
        half_width = math.floor(self._back_label.content_width / 2)
        half_height = math.floor(self._back_label.content_height / 2)
        return (self._back_label.x - half_width <= x <= self._back_label.x + half_width and
                self._back_label.y - half_height <= y <= self._back_label.y + half_height)

    def on_enter(self):
        pass

    def on_exit(self):
        pass

    def draw(self):
        self._window.clear()
        self._batch.draw()

    def update(self, dt):
        pass

    def on_key_press(self, symbol, modifiers):
        # ESCAPE (the dictionary screen's back key) or the menu select key both
        # leave; there is nothing else to do on this screen.
        if symbol in control_keys("dictionary.back"):
            self._back()
            return True
        if symbol in control_keys("main_menu.select"):
            self._back()
            return True
        return False

    def on_mouse_press(self, x, y, button, modifiers):
        if self._over_back(x, y):
            self._back()

    def on_mouse_motion(self, x, y, dx, dy):
        pass
