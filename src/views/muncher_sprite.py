"""The Word Muncher character sprite -- the on-board avatar for MOVING_MUNCHER
(game_screen.mode: rule_mode_muncher).

Owns ONLY the character's presentation: which of the three art frames is showing,
which way he faces, and where he is in pixels between two cell centers. It knows
nothing about the board, the grams, the word being built, or the rules -- the
mode (views/moving_mode.MuncherMovingMode) drives it with four calls:

    place(x, y)     put him on a cell center with no animation (game start)
    step_to(x, y)   begin a glide to the next cell center (one key press)
    chew()          flash the open mouth (one bite)
    fade_in()       materialize him (spawn, and the far side of a lost life)
    fade_out()      dissolve him away (a lost life)
    set_belly(n)    how full his stomach is drawn (0 = empty, no overlay)
    tick(dt)        advance every timer, once per frame

Input is DISCRETE -- one key press moves him exactly one cell -- so the glide is
pure animation catching up to a move that has already happened logically. That is
why `stepping()` is offered as a lockout: the mode refuses a second move while the
first is still traveling, rather than queueing moves (see step_lockout_fraction).

All timing and sizing come from the swappable animation file
(assets/muncher_animation/, rule assets.muncher_animation) via config.get_muncher_anim,
read once at construction -- so a mode can ship a faster or larger muncher without
any code change. See its comments for what each knob does.

FRAMES. The art has four walk/bite states, but only three are used: mouth-closed
standing, mouth-closed walking, and mouth-open standing. There is no open-mouth
walking frame in play because a bite happens standing still -- the fourth source
frame is deliberately not even converted (see tools/make_muncher_sprites.py). If
chewing while walking ever becomes a thing, convert it and add it to _frame below.

THE BELLY is four more images, and unlike everything else here they are not
FRAMES of the character -- they are a stomach blob drawn OVER whichever frame is
showing, so one belly rides the standing, walking and chewing art alike instead of
needing three variants of each. They share the crop box with the frames, so the
overlay needs no offset: same size, same center, and the blob lands on his middle.
The SIZE is the mode's call (it counts letters); this class only draws the size it
is handed. A belly is suppressed during a fade -- a solid blob over a half-
dissolved character would read as a bug rather than a stomach.

THE FADE is three more frames (fade_01 / fade_02 / fade_03) and is a DISSOLVE, not
an opacity ramp: each frame draws more of the character than the last, so playing
them forward materializes him and playing them backward dissolves him. Nothing
here touches sprite opacity -- the partial coverage is baked into the art's alpha.
The frames share the walk frames' crop box, so he fades in exactly where he will
stand. A fade is a hard MODAL state: while one runs, _frame ignores walking and
chewing entirely, and the mode refuses input (see MuncherMovingMode).
"""

import math
import pyglet
from config import get_muncher_anim
from views.textures import muncher_image


# The dissolve frames in MATERIALIZE order (least of him to most of him). A
# fade-out is this list walked backwards -- see _fade_frame. Names match the
# states registered in views/textures.
FADE_FRAMES = ("fade_01", "fade_02", "fade_03")

# The belly overlays in order, emptiest first -- index 0 is belly SIZE 1, because
# size 0 means no overlay at all. The length of this tuple IS the cap: a mode that
# counts past it gets the fattest belly, not an error. Names match the states
# registered in views/textures.
BELLY_IMAGES = ("belly_01", "belly_02", "belly_03", "belly_04")


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
        self._fade_seconds = get_muncher_anim("fade_seconds")
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
        # Fade animation: 0 = no fade running, +1 = materializing, -1 = dissolving.
        # _hidden is the state a finished fade-OUT leaves behind -- he is gone from
        # the board until something fades him back in, which is what makes the two
        # calls a matched pair rather than two independent effects.
        self._fade_dir = 0
        self._fade_elapsed = 0.0
        self._hidden = False
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
        # The belly overlay: its own sprite so it can change independently of the
        # frame underneath. Size 0 (an empty stomach) draws nothing; that is the
        # _belly_size guard in draw(), NOT sprite.visible -- pyglet collapses an
        # invisible sprite's four vertices onto the origin and _get_vertices keeps
        # returning zeros while it stays False, so a sprite switched off that way
        # once never draws again however its image or position is set afterwards.
        # It is loaded with the smallest belly purely so the sprite has a texture.
        self._belly_size = 0
        self._belly = pyglet.sprite.Sprite(self._image(BELLY_IMAGES[0]))
        self._apply_belly_scale()

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

    def fade_in(self):
        """Materialize him over fade_seconds: fade_01 -> fade_02 -> fade_03, then
        the ordinary standing frame. Ends with him visible, so this is also how a
        hidden character is brought back. A zero fade_seconds shows him at once."""
        self._hidden = False
        if self._fade_seconds > 0:
            self._fade_dir = 1
            self._fade_elapsed = 0.0

    def fade_out(self):
        """Dissolve him away over fade_seconds, the same frames in reverse. When it
        finishes he is HIDDEN -- draw() puts nothing on the board -- and stays that
        way until a fade_in. A zero fade_seconds hides him at once."""
        if self._fade_seconds > 0:
            self._fade_dir = -1
            self._fade_elapsed = 0.0
        else:
            self._hidden = True

    def set_belly(self, size):
        """Draw his stomach at `size`: 0 for empty (no overlay at all), up to the
        number of belly images. Out-of-range values are clamped rather than
        rejected, so the mode's letters-to-size arithmetic cannot crash the draw.
        Cheap to call every frame -- it does nothing unless the size changed."""
        size = max(0, min(len(BELLY_IMAGES), int(size)))
        if size != self._belly_size:
            self._belly_size = size
            if size > 0:
                self._belly.image = self._image(BELLY_IMAGES[size - 1])
                self._apply_belly_scale()

    def belly_size(self):
        """The stomach size currently drawn -- the mode's own value, echoed back
        for tests and logging."""
        return self._belly_size

    def fading(self):
        """Whether a fade is running. The mode uses this as an input lockout: he is
        materializing or dissolving and may not be walked or made to bite."""
        return self._fade_dir != 0

    def hidden(self):
        """Whether he is off the board entirely -- a finished fade_out with no
        fade_in yet. The mode holds the player frozen through this too."""
        return self._hidden

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
        self._tick_fade(dt)
        self._sync_position()
        self._sync_frame()

    def draw(self):
        # A finished fade-out leaves nothing to draw: he is off the board until a
        # fade_in brings him back.
        if not self._hidden:
            self._sprite.draw()
            # The stomach goes on top of the frame. Suppressed mid-fade: the fade
            # frames are a dissolve, and a solid blob over a half-formed character
            # reads as a rendering bug rather than a full stomach.
            if self._belly_size > 0 and self._fade_dir == 0:
                self._belly.draw()

    def delete(self):
        """Release the sprite's GPU resources (game teardown / mode restart)."""
        self._sprite.delete()
        self._belly.delete()

    # --- internals ---------------------------------------------------------
    def _fraction(self):
        """How far along the current step he is, 0..1. A zero step_seconds (the
        teleport setting) reads as finished immediately."""
        fraction = 1.0
        if self._step_seconds > 0 and self._step_elapsed < self._step_seconds:
            fraction = self._step_elapsed / self._step_seconds
        return fraction

    def _tick_fade(self, dt):
        """Advance a running fade and settle what it leaves behind: a finished
        fade-IN hands off to the ordinary frames, a finished fade-OUT hides him."""
        if self._fade_dir != 0:
            self._fade_elapsed += dt
            if self._fade_elapsed >= self._fade_seconds:
                self._hidden = self._fade_dir < 0
                self._fade_dir = 0

    def _fade_frame(self):
        """The dissolve frame for how far the current fade has run. The elapsed
        time is split into as many equal slices as there are frames; a fade-OUT
        walks the same list backwards, so the two directions are one animation
        played either way."""
        fraction = self._fade_elapsed / self._fade_seconds
        index = int(fraction * len(FADE_FRAMES))
        # Clamp: the last tick can land exactly on (or a hair past) 1.0 before
        # _tick_fade ends the fade, which would index off the end.
        index = max(0, min(len(FADE_FRAMES) - 1, index))
        if self._fade_dir < 0:
            index = len(FADE_FRAMES) - 1 - index
        return FADE_FRAMES[index]

    def _walking(self):
        return self._step_elapsed < self._step_seconds

    def _chewing(self):
        return self._chew_elapsed < self._chew_seconds

    def _frame(self):
        """Which art frame the current state calls for. A running fade wins over
        everything -- he is not walking or biting while he is materializing, and
        the mode refuses the keys that would say otherwise. Below that, chewing
        wins over walking: there is no open-mouth walking frame, so a bite taken
        mid-glide shows the open mouth and lets the legs rest for those few
        frames."""
        if self._fade_dir != 0:
            return self._fade_frame()
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

    def _apply_belly_scale(self):
        """Scale the belly to the SAME height as the character. The overlay shares
        the frames' crop box, so matching the height is the entire alignment
        requirement -- there is no offset to compute."""
        native = self._belly.image.height
        if native > 0:
            self._belly.scale = self._height / native

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
        self._belly.position = (x, y, 0)

    def _sync_frame(self):
        image = self._image(self._frame())
        if self._sprite.image is not image:
            self._sprite.image = image
            self._apply_scale()
        # The belly is flipped by the same _image() facing cache as the frames, so
        # a left-facing character wears a left-facing stomach and the two stay
        # registered. Re-read every tick because facing can change without the
        # belly size changing.
        if self._belly_size > 0:
            belly = self._image(BELLY_IMAGES[self._belly_size - 1])
            if self._belly.image is not belly:
                self._belly.image = belly
                self._apply_belly_scale()
