import math
import pyglet
from config import get_color, get_string, debug_end_video_path, list_video_paths
from controls import control_keys
from views.end_video_overlay import EndVideoOverlay


class DebugMenuScreen:
    """The "Debug" submenu (main menu -> Debug): developer-only actions for testing
    isolated features without playing a full game.

    Its actions are one "Play endgame video" row PER clip in assets/video/ (goldeneye,
    mario, ...), each playing that specific clip fullscreen right here so the
    EndVideoOverlay trigger + playback can be eyeballed in a single click without
    swapping game_screen.end_video first. This screen owns its OWN overlay, separate
    from the game screen's, so a clip is exercised in isolation from game state. See
    ONGOING_BUGS.md ("End video does not play on misspell-instadeath end")."""

    def __init__(self, window, screen_manager, back_screen_type):
        self._window = window
        self._screen_manager = screen_manager
        self._back_screen_type = back_screen_type
        self._highlight_color = get_color("menu.highlight")
        self._normal_color = get_color("menu.normal")
        self._batch = pyglet.graphics.Batch()

        # One "Play <clip>" row per video in assets/video/, then a trailing Back row
        # (handled by index). _video_paths[i] is the clip for row i; Back has no entry.
        self._video_paths = list_video_paths()
        label_prefix = get_string("debug_play_end_video")
        self._menu_items = [
            f"{label_prefix}: {p.stem}" for p in self._video_paths
        ] + [get_string("menu_back")]
        self._selected_index = 0
        self._labels = []

        # This screen's own end-video overlay (rebuilt on each play so a config swap
        # since construction is picked up). Seeded with the debug default clip.
        self._end_video = EndVideoOverlay(window, debug_end_video_path())

        self._title = pyglet.text.Label(
            get_string("menu_debug_title"),
            font_size=36,
            x=math.floor(window.width / 2),
            y=window.height - 90,
            anchor_x="center", anchor_y="center",
            batch=self._batch,
        )
        start_y = math.floor(window.height / 2) + 30
        spacing = 60
        for i, text in enumerate(self._menu_items):
            label = pyglet.text.Label(
                text,
                font_size=28,
                x=math.floor(window.width / 2),
                y=start_y - i * spacing,
                anchor_x="center", anchor_y="center",
                batch=self._batch,
            )
            self._labels.append(label)
        self._update_highlight()

    def _update_highlight(self):
        for i, label in enumerate(self._labels):
            label.color = (self._highlight_color if i == self._selected_index
                           else self._normal_color)

    def _back_index(self):
        # The Back item is always the last row.
        return len(self._labels) - 1

    def _play_end_video(self, path):
        """Start the given clip fullscreen over this menu. A fresh overlay each call
        covers a replay of the same clip within one screen visit. A no-op flash when
        the path is None (no clip)."""
        self._end_video = EndVideoOverlay(self._window, path)
        self._end_video.play()

    def _select_current(self):
        if self._selected_index == self._back_index():
            self._screen_manager.switch_to(self._back_screen_type)
        else:
            # A video row: play its own clip (rows and _video_paths share indices).
            self._play_end_video(self._video_paths[self._selected_index])

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
        self._update_highlight()
        self._end_video.stop()

    def on_exit(self):
        # Stop any clip so its audio does not keep playing off-screen.
        self._end_video.stop()

    def draw(self):
        self._window.clear()
        self._batch.draw()
        # The clip plays fullscreen over the menu; it self-dismisses when it ends.
        if self._end_video.active:
            self._end_video.draw()

    def update(self, dt):
        # Tear the clip down once it has played through (polls play time / duration).
        self._end_video.update()

    def on_key_press(self, symbol, modifiers):
        # A key press while the clip is up cuts it short (handy for testing).
        if self._end_video.active:
            self._end_video.stop()
            return True
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
            # back binding, as the mode-select submenu does).
            self._screen_manager.switch_to(self._back_screen_type)
            return True
        return False

    def on_mouse_press(self, x, y, button, modifiers):
        # A click while the clip is up cuts it short rather than selecting a row.
        if self._end_video.active:
            self._end_video.stop()
            return
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
