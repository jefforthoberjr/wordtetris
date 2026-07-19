"""Window input event handlers extracted from GameScreen: on_key_press,
on_text, on_mouse_press, on_mouse_motion, the menu-action dispatch they call, and
the shared disambiguation-chooser routing. A mixin -- every method runs with
GameScreen's self; it reads the same rules/panes/mode the other mixins set up.
Kept out of game_screen.py to bound its size (see AGENTS.md).

The chooser routing (_chooser_keys / _chooser_mouse) is factored out because the
"select which one" chooser is hosted in TWO places now: the SELECTING phase (the
two-phase model) and the MOVING phase (single-phase MOVING_AND_SELECTING, where
the chooser opens without ever leaving MOVING). Both call the same helpers, and
both talk to self._selecting_side_pane -- which in single-phase is the very same
merged pane as self._moving_side_pane, so the helpers need no phase branch."""

import pyglet

from views.game_phase import Phase
from controllers.screen_manager import ScreenType
import log_codes as L


# Modifier bits worth recording on a logged key press; the OS lock keys
# (NUMLOCK / CAPSLOCK / SCROLLLOCK) are dropped as noise. See log_20001.
_LOG_MODIFIERS = (
    (pyglet.window.key.MOD_SHIFT, "SHIFT"),
    (pyglet.window.key.MOD_CTRL, "CTRL"),
    (pyglet.window.key.MOD_ALT, "ALT"),
    (pyglet.window.key.MOD_COMMAND, "CMD"),
)


def _mods_str(modifiers):
    """The meaningful held modifiers as a '+'-joined string ('' if none)."""
    return "+".join(name for bit, name in _LOG_MODIFIERS if modifiers & bit)


class InputMixin:
    def _handle_menu_action(self, action):
        if action == "resume":
            self._menu_open = False
            # Re-hide the system cursor if play resumes in shooting mode.
            self._sync_shooting_cursor()
        elif action == "main_menu":
            self._screen_manager.switch_to(ScreenType.MAIN_MENU)
        elif action == "exit":
            self._window.close()

    # --- disambiguation chooser routing (shared by SELECTING + single-phase) ---
    def _chooser_keys(self, symbol, modifiers):
        """Route a key to the open chooser: cycle the highlight, confirm, or back
        out (word_clear / Backspace / any letter, gated by game_screen.disambig_
        cancel). Backspace also EDITs after backing out, so the player flows
        straight into re-typing; a swallowed stray key can't edit mid-choice. The
        chooser owns the keyboard, so the caller always consumes the key."""
        if symbol in self._keys["word_cycle_prev"]:
            self._cycle_disambiguation(-1)
        elif symbol in self._keys["word_cycle_next"]:
            self._cycle_disambiguation(1)
        elif symbol in self._keys["word_submit"]:
            self._confirm_disambiguation()
        elif symbol in self._keys["word_backspace"]:
            if self._backout_disambiguation():
                self._selecting_side_pane.on_key_press(symbol, modifiers)
        elif symbol in self._keys["word_clear"]:
            self._backout_disambiguation()

    def _chooser_mouse(self, x, y):
        """Route a click to the open chooser: the Submit label confirms the
        highlighted candidate, Clear backs out (per disambig_cancel). Board clicks
        and gram-typing are inert so a click can't edit the field mid-choice."""
        if self._selecting_side_pane.hit_submit(x, y):
            self._confirm_disambiguation()
        elif self._selecting_side_pane.hit_clear(x, y):
            self._disambig_cancel_rule()

    # --- key input ---------------------------------------------------------
    def on_key_press(self, symbol, modifiers):
        # Log the raw press before any delegation so the session log holds the
        # complete control stream a replay re-feeds (record #2).
        L.log_20001(pyglet.window.key.symbol_string(symbol),
                    _mods_str(modifiers), self._phase.name)
        if self._menu_open:
            action = self._ingame_menu.on_key_press(symbol, modifiers)
            if action:
                self._handle_menu_action(action)
            return True

        # Escape backs out of the open disambiguation chooser instead of opening
        # the pause menu (one of the chooser back-out gestures alongside Backspace
        # / any letter). The chooser lives in SELECTING (two-phase) or MOVING
        # (single-phase), so this is keyed on _disambiguating, not the phase. If
        # cancel is disabled the back-out is inert and Escape falls through.
        if (symbol in self._keys["pause"]
                and self._disambiguating() and self._backout_disambiguation()):
            return True

        if symbol in self._keys["pause"]:
            self._menu_open = True
            self._ingame_menu.reset()
            # Restore the system cursor over the pause menu (shooting mode hid it).
            self._sync_shooting_cursor()
            return True

        # During the opening reveal nothing on the board responds; only the pause
        # menu (handled above) works -- no move, rotate, place, or word entry.
        if self._phase == Phase.LOADING:
            return True

        # Once won, the game is frozen: no piece movement, rotation, placement,
        # or word entry -- only the menu (Escape, handled above) responds.
        if self._phase == Phase.VICTORY:
            return True

        # While selecting words, keys drive the entry pane; letters arrive
        # separately via on_text. Control scheme (anti-fat-finger): ENTER is the
        # one action key -- with text it submits the word (pane default), on an
        # empty field it ends selection (Next piece / omniswap surrender).
        # word_clear (spacebar) clears the typed word (a lingering failed attempt),
        # so it can no longer end the game by reflex.
        if self._phase == Phase.SELECTING:
            # The chooser owns the keyboard while it's open.
            if self._disambiguating():
                self._chooser_keys(symbol, modifiers)
                return True
            if symbol in self._keys["word_clear"]:       # spacebar -> clear field
                self._selecting_side_pane.clear_word()
                return True
            if (symbol in self._keys["selection_end"]
                    and self._selecting_side_pane.is_empty()):
                self._end_selection()                    # ENTER on empty -> end
                return True
            return self._selecting_side_pane.on_key_press(symbol, modifiers)

        # Single-phase (MOVING_AND_SELECTING): the chooser can be open here too --
        # it opened on a submit without ever leaving MOVING -- so route its keys
        # before the hunt field / mode, mirroring the SELECTING branch above.
        if self._single_phase and self._disambiguating():
            self._chooser_keys(symbol, modifiers)
            return True

        # Word-hunt field: Backspace edits the typed hunt word (letters arrive via
        # on_text). Consumed only when the field handles it, so other keys fall
        # through to the moving mode.
        if self._moving_side_pane.on_key_press(symbol, modifiers):
            return True

        # MOVING phase: the active mode owns piece/cursor input.
        return self._moving_mode.on_key_press(symbol, modifiers)

    # --- text input --------------------------------------------------------
    def on_text(self, text):
        # Typed characters only matter while selecting words; on_key_press
        # handles Backspace/Enter and the pane filters to letters.
        L.log_20002(text, self._phase.name)
        if self._menu_open:
            return
        if self._phase == Phase.SELECTING:
            # Typing a LETTER while the chooser is open backs out of it, then the
            # letter appends -- the player abandons the confirmation and keeps
            # hunting. If cancel is disabled the letter is swallowed (the chooser
            # keeps the keyboard until confirm). Gate on isalpha: Enter's '\r' (and
            # other control chars) are NOT edit gestures and must fall through so
            # on_key_press can CONFIRM the chooser -- this on_text fires before
            # on_key_press here, so a blind back-out would cancel every Enter.
            if (text.isalpha() and self._disambiguating()
                    and not self._backout_disambiguation()):
                return
            self._selecting_side_pane.on_text(text)
        elif self._phase == Phase.MOVING:
            # Single-phase: a letter backs out of an open chooser first (same as
            # SELECTING), then appends to the merged field.
            if (self._single_phase and text.isalpha() and self._disambiguating()
                    and not self._backout_disambiguation()):
                return
            # Typed letters feed the word-hunt field (movement/rotate keys are all
            # non-letters now, so they never leak in); highlighting updates live.
            self._moving_side_pane.on_text(text)

    # --- mouse input -------------------------------------------------------
    def on_mouse_press(self, x, y, button, modifiers):
        # Log the board cell the pixel resolves to alongside the raw coord, so a
        # coordinate-scale desync shows up as clicks that stop matching cells.
        board = getattr(self, "_board", None)
        cell = board.cell_at(x, y) if board is not None else None
        L.log_20003(x, y, pyglet.window.mouse.buttons_string(button),
                    self._phase.name, cell)
        if self._menu_open:
            action = self._ingame_menu.on_mouse_press(x, y, button, modifiers)
            if action:
                self._handle_menu_action(action)
            return
        # Once the game has ended, a click dismisses the end-state overlay (if it's
        # still up), leaving the player looking at the final board. The game stays
        # frozen otherwise -- only the menu (Escape) responds.
        if self._phase == Phase.VICTORY:
            self._end_overlay_dismissed = True
            return
        if self._phase == Phase.SELECTING:
            # While the chooser is open the Submit label confirms and Clear backs
            # out; board clicks and gram-typing are inert. Enter/arrows handle the
            # keyboard.
            if self._disambiguating():
                self._chooser_mouse(x, y)
                return
            # Right-click manipulates a board gram during SELECTING too, when
            # game_screen.gram_manip_in_selecting is enabled (omniswap lives in
            # SELECT, so gram-doubling must reach here). Consumes the click before
            # the selection handling below, mirroring MOVING.
            if self._gram_manip_in_selecting and self._try_gram_manipulate(x, y, button):
                return
            self._selecting_side_pane.on_mouse_press(x, y, button, modifiers)
            # A left-click on the board (left of the pane) types that cell's gram
            # into the entry field, per the select-click rule. The pane handles
            # its own right-side button clicks above; this drives the board side.
            # Skip it if the pane click just ended the game (End game -> VICTORY):
            # the select-click rule would recompute candidates on a finished board.
            if (button == self._buttons["select_primary"]
                    and self._phase == Phase.SELECTING):
                self._select_click_rule(x, y)
            # Stop here: the pane click may have ended selection (Next piece),
            # flipping the phase to MOVING. Without this return, the same click
            # would fall through to the MOVING handling below and be re-read as a
            # board move / word-piece swap at the Next-piece button's position.
            return
        # MOVING phase: the gram-manipulate button (right-click) transforms a
        # cell's gram, mode-agnostic; every other button goes to the active mode
        # (which owns piece/cursor input). _try_gram_manipulate keeps an UNASSIGNED
        # gram_manipulate (None) from swallowing clicks.
        if self._phase == Phase.MOVING:
            # Single-phase: an open chooser owns the click here too (confirm/cancel
            # on the merged pane's buttons; board + gram-manip inert), mirroring the
            # SELECTING branch above.
            if self._single_phase and self._disambiguating():
                self._chooser_mouse(x, y)
                return
            # Single-phase (MOVING_AND_SELECTING): the merged pane's Clear / Submit
            # / End controls live in MOVING (there is no SELECTING phase to click
            # them in). Consume the click if it hit one; board clicks fall through
            # unconsumed to the gram-manip / mode handling below.
            if (self._single_phase
                    and self._moving_side_pane.on_mouse_press(x, y, button, modifiers)):
                return
            # The moving pane's "Select words" button jumps straight to SELECTING,
            # the click-equivalent of the omniswap ENTER route. Handled before the
            # mode so a click on it never reads as a board move / gram-manip.
            if (button == self._buttons["move_primary"]
                    and self._moving_side_pane.hit_select(x, y)):
                self._request_select()
                return
            if not self._try_gram_manipulate(x, y, button):
                self._moving_mode.on_mouse_press(x, y, button)

    def on_mouse_motion(self, x, y, dx, dy):
        if self._menu_open:
            self._ingame_menu.on_mouse_motion(x, y, dx, dy)
        # Shooting gallery: the crosshair overlay follows the mouse. Tracked even
        # with the menu open so it's in the right place the instant play resumes;
        # it just isn't drawn until then (see draw / _sync_shooting_cursor).
        if self._shooting and self._phase == Phase.MOVING:
            self._moving_mode.on_mouse_motion(x, y)
