from enum import Enum


class Phase(Enum):
    """Game-screen phases. LOADING: the opening reveal -- formation cells and
    grid lines fade in on a timeline and all input is blocked; no live piece,
    no timer (see loading_animation). MOVING: a piece is live and the player
    moves/places it. SELECTING: a piece has been placed and the player is
    choosing which words to clear before the next piece spawns (interactive
    selection rules only; the auto selector never leaves MOVING). VICTORY: the
    active victory rule was met -- no live piece, no word entry; the player can
    only open the menu (Escape).

    Lives here (not on game_screen) so the extracted GameScreen mixins can import
    it without importing back into game_screen; game_screen re-imports it, so
    gs.Phase still resolves."""
    LOADING = 0
    MOVING = 1
    SELECTING = 2
    VICTORY = 3
