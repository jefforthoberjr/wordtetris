"""The Word Muncher character sprite -- the on-board avatar for MOVING_MUNCHER
(game_screen.mode: rule_mode_muncher).

Owns ONLY the character's presentation: which of the three art frames is showing,
which way he faces, and where he is in pixels between two cell centers. It knows
nothing about the board, the grams, the word being built, or the rules -- the
mode (views/moving_mode.MuncherMovingMode) drives it with four calls:

    place(x, y)     put him on a cell center with no animation (game start)
    step_to(x, y)   begin a glide to the next cell center (one key press)
    chew()          flash the open mouth (one bite)
    tick(dt)        advance both timers, every frame

Input is DISCRETE -- one key press moves him exactly one cell -- so the glide is
pure animation catching up to a move that has already happened logically. That is
why `stepping()` is offered as a lockout: the mode refuses a second move while the
first is still traveling, rather than queueing moves (see step_lockout_fraction).

All timing and sizing come from the swappable animation file
(assets/muncher_animation/, rule assets.muncher_animation) via config.get_muncher_anim,
read once at construction -- so a mode can ship a faster or larger muncher without
any code change. See its comments for what each knob does.

FRAMES. The art has four states, but only three are used: mouth-closed standing,
mouth-closed walking, and mouth-open standing. There is no open-mouth walking
frame in play because a bite happens standing still -- the fourth source frame is
deliberately not even converted (see tools/make_muncher_sprites.py). If chewing
while walking ever becomes a thing, convert it and add it to _frame below.
"""

import math
import pyglet
from config import get_muncher_anim
from views.textures import muncher_image


class MuncherSprite:
    """One character on the board. Constructed per game by the mode, sized off the
    board's cell size, and drawn every frame while MOVING."""

    def __init__(self, cell_size):
        # Target height in pixels: the animation file's cell_scale times the
        # board's cell size, so the character resizes with the board (which is
        # itself sized off the window -- no raw pixel constants here).
        self._height = cell_size * get_muncher_anim("cell_scale")
        self._step_seconds = get_muncher_anim("step_seconds")
        self._chew_seconds = get_muncher_anim("chew_seconds")
        self._walk_cycle_seconds = get_muncher_anim("walk_cycle_seconds")
        self._lockout = (self._step_seconds
                         * get_muncher_anim("step_lockout_fraction"))
        # Step animation: travel from (_from) to (_to) over _step_seconds.
        # _step_elapsed >= _step_seconds means "standing at _to".
        self._from = (0.0, 0.0)
        self._to = (0.0, 0.0)
        self._step_elapsed = self._step_seconds
        # Chew animation: counts UP to _chew_seconds, at which point the mouth
        # closes again. Starts finished (mouth shut).
        self._chew_elapsed = self._chew_seconds
        # Walk-frame alternation, only consulted when walk_cycle_seconds > 0.
        self._walk_elapsed = 0.0
        self._walk_frame_walking = True
        # +1 faces right (the art's native direction), -1 faces left. Vertical
        # moves leave it alone, so he keeps looking the way he last walked.
        self._facing = 1
        # {(state, facing): image} -- see _image; the left-facing frames are
        # built once by flipping the loaded texture.
        self._frames = {}
        self._sprite = pyglet.sprite.Sprite(self._image("closed_standing"))
        self._apply_scale()

    # --- placement / movement ---------------------------------------------
    def place(self, x, y):
        """Snap to the cell center (x, y) with no animation -- the game-start
        placement, and the resync after anything that moves him non-physically."""
        self._from = (x, y)
        self._to = (x, y)
        self._step_elapsed = self._step_seconds
        self._sync_position()

    def step_to(self, x, y):
        """Begin a walk from wherever he currently IS to the cell center (x, y).
        Starting from the current drawn position (not from _to) keeps the motion
        continuous if a step is allowed to interrupt an unfinished one -- which
        step_lockout_fraction below 1.0 permits."""
        self._from = self.position()
        self._to = (x, y)
        self._step_elapsed = 0.0
        self._walk_elapsed = 0.0
        self._walk_frame_walking = True
        if x > self._from[0]:
            self._facing = 1
        elif x < self._from[0]:
            self._facing = -1
        self._sync_position()

    def face(self, facing):
        """Force the facing (+1 right / -1 left) without moving -- for a mode that
        wants a turn-in-place. Unused by the current controls; kept as the seam."""
        if facing != 0:
            self._facing = 1 if facing > 0 else -1

    def chew(self):
        """Flash the open mouth for chew_seconds. The bite itself already
        happened; this is only the tell."""
        self._chew_elapsed = 0.0

    def stepping(self):
        """Whether a step is still traveling far enough along that the mode should
        refuse another move key (the step_lockout_fraction gate)."""
        return self._step_elapsed < self._lockout

    def position(self):
        """Current drawn center in pixels, interpolated along the step."""
        fraction = self._fraction()
        x = self._from[0] + (self._to[0] - self._from[0]) * fraction
        y = self._from[1] + (self._to[1] - self._from[1]) * fraction
        return (x, y)

    # --- per-frame ---------------------------------------------------------
    def tick(self, dt):
        """Advance the step and chew timers and refresh the drawn frame."""
        if self._step_elapsed < self._step_seconds:
            self._step_elapsed += dt
        if self._chew_elapsed < self._chew_seconds:
            self._chew_elapsed += dt
        if self._walk_cycle_seconds > 0 and self._walking():
            self._walk_elapsed += dt
            if self._walk_elapsed >= self._walk_cycle_seconds:
                self._walk_elapsed -= self._walk_cycle_seconds
                self._walk_frame_walking = not self._walk_frame_walking
        self._sync_position()
        self._sync_frame()

    def draw(self):
        self._sprite.draw()

    def delete(self):
        """Release the sprite's GPU resources (game teardown / mode restart)."""
        self._sprite.delete()

    # --- internals ---------------------------------------------------------
    def _fraction(self):
        """How far along the current step he is, 0..1. A zero step_seconds (the
        teleport setting) reads as finished immediately."""
        fraction = 1.0
        if self._step_seconds > 0 and self._step_elapsed < self._step_seconds:
            fraction = self._step_elapsed / self._step_seconds
        return fraction

    def _walking(self):
        return self._step_elapsed < self._step_seconds

    def _chewing(self):
        return self._chew_elapsed < self._chew_seconds

    def _frame(self):
        """Which art frame the current state calls for. Chewing wins over walking:
        there is no open-mouth walking frame, so a bite taken mid-glide shows the
        open mouth and lets the legs rest for those few frames."""
        name = "closed_standing"
        if self._chewing():
            name = "open_standing"
        elif self._walking():
            if self._walk_cycle_seconds > 0 and not self._walk_frame_walking:
                name = "closed_standing"
            else:
                name = "closed_walking"
        return name

    def _image(self, state):
        """The frame image for `state`, flipped horizontally when facing left. The
        flip goes through the texture (not a negative sprite scale) so the anchor
        stays exact. Both orientations are cached per instance: get_transform
        hands back a FRESH region every call, so without this the sprite's image
        would be reassigned every single frame while facing left, and the
        re-anchoring would be applied over and over."""
        key = (state, self._facing)
        if key not in self._frames:
            image = muncher_image(state, self._height)
            if self._facing < 0:
                image = image.get_texture().get_transform(flip_x=True)
                image.anchor_x = math.floor(image.width / 2)
                image.anchor_y = math.floor(image.height / 2)
            self._frames[key] = image
        return self._frames[key]

    def _apply_scale(self):
        """Scale the loaded frame down to the target height. The frames all share
        one crop box, so this scale holds for every state and the character never
        changes size between frames."""
        native = self._sprite.image.height
        if native > 0:
            self._sprite.scale = self._height / native

    def _sync_position(self):
        x, y = self.position()
        self._sprite.position = (x, y, 0)

    def _sync_frame(self):
        image = self._image(self._frame())
        if self._sprite.image is not image:
            self._sprite.image = image
            self._apply_scale()
