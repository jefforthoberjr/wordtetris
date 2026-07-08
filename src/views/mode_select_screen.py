import math
import pyglet
from config import get_color, get_string, list_game_modes
from controls import control_keys


class ModeSelectScreen:
    """The "Start Game" submenu: one item per game mode (assets/game_modes/*.yaml,
    labelled by each file's mode_label) plus a Back item. Picking a mode hands its
    override path to `on_select_mode` (wired in main.py) which applies the config
    and (re)builds the game screen -- see config.apply_game_mode. The mode list is
    rebuilt on every on_enter, so dropping a new mode file in the folder shows it
    without a restart."""

    def __init__(self, window, screen_manager, back_screen_type, on_select_mode):
        self._window = window
        self._screen_manager = screen_manager
        self._back_screen_type = back_screen_type
        self._on_select_mode = on_select_mode
        self._highlight_color = get_color("menu.highlight")
        self._normal_color = get_color("menu.normal")

        # Built fresh each on_enter from the current mode folder; see _rebuild.
        self._batch = pyglet.graphics.Batch()
        self._title = None
        self._labels = []
        # Parallel to the mode rows only (NOT the trailing Back item): the override
        # path each row applies. Back is handled by index, past this list's end.
        self._mode_paths = []
        self._selected_index = 0

    def _rebuild(self):
        """Rebuild the title + item labels from the live mode list. A brand-new
        batch drops the previous enter's labels together for GC rather than
        stacking hidden text behind the new list."""
        self._batch = pyglet.graphics.Batch()
        self._labels = []
        self._mode_paths = []

        modes = list_game_modes()
        item_texts = [label for _slug, label, _path in modes]
        self._mode_paths = [path for _slug, _label, path in modes]
        item_texts.append(get_string("menu_back"))

        self._title = pyglet.text.Label(
            get_string("menu_mode_select_title"),
            font_size=36,
            x=math.floor(self._window.width / 2),
            y=self._window.height - 90,
            anchor_x="center", anchor_y="center",
            batch=self._batch,
        )

        # Center the item column in the space below the title. Spacing shrinks a
        # little if a long mode list would otherwise run off the bottom.
        count = len(item_texts)
        spacing = min(56, math.floor((self._window.height - 200) / max(count, 1)))
        start_y = math.floor(self._window.height / 2) + (count - 1) * spacing // 2
        for i, text in enumerate(item_texts):
            label = pyglet.text.Label(
                text,
                font_size=26,
                x=math.floor(self._window.width / 2),
                y=start_y - i * spacing,
                anchor_x="center", anchor_y="center",
                batch=self._batch,
            )
            self._labels.append(label)

        if self._selected_index >= len(self._labels):
            self._selected_index = 0
        self._update_highlight()

    def _update_highlight(self):
        for i, label in enumerate(self._labels):
            label.color = (self._highlight_color if i == self._selected_index
                           else self._normal_color)

    def _back_index(self):
        # The Back item is always the last row.
        return len(self._labels) - 1

    def _select_current(self):
        if self._selected_index == self._back_index():
            self._screen_manager.switch_to(self._back_screen_type)
        else:
            # A mode row: hand its override path to the coordinator, which applies
            # the config and switches into a freshly-built game screen.
            self._on_select_mode(self._mode_paths[self._selected_index])

    def _get_item_at(self, x, y):
        for i, label in enumerate(self._labels):
            half_w = math.floor(label.content_width / 2)
            half_h = math.floor(label.content_height / 2)
            if (label.x - half_w <= x <= label.x + half_w and
                    label.y - half_h <= y <= label.y + half_h):
                return i
        return None

    def on_enter(self):
        self._selected_index = 0
        self._rebuild()

    def on_exit(self):
        pass

    def draw(self):
        self._window.clear()
        self._batch.draw()

    def update(self, dt):
        pass

    def on_key_press(self, symbol, modifiers):
        if symbol in control_keys("main_menu.nav_up"):
            self._selected_index = (self._selected_index - 1) % len(self._labels)
            self._update_highlight()
            return True
        elif symbol in control_keys("main_menu.nav_down"):
            self._selected_index = (self._selected_index + 1) % len(self._labels)
            self._update_highlight()
            return True
        elif symbol in control_keys("main_menu.select"):
            self._select_current()
            return True
        elif symbol in control_keys("dictionary.back"):
            # ESCAPE backs out to the previous menu (reuses the dictionary screen's
            # back binding rather than adding a near-duplicate control key).
            self._screen_manager.switch_to(self._back_screen_type)
            return True
        return False

    def on_mouse_press(self, x, y, button, modifiers):
        item_index = self._get_item_at(x, y)
        if item_index is not None:
            self._selected_index = item_index
            self._update_highlight()
            self._select_current()

    def on_mouse_motion(self, x, y, dx, dy):
        item_index = self._get_item_at(x, y)
        if item_index is not None:
            self._selected_index = item_index
            self._update_highlight()
