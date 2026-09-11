"""The muncher's remaining lives, drawn as a row of little characters.

MOVING_MUNCHER (game_screen.mode: rule_mode_muncher) has no clock, so the lives
take the slot a countdown would occupy -- the top status row of the right pane --
and they are drawn rather than spelled out: three small mouth-closed munchers
standing in a row, one vanishing each time a bad word is submitted.

The art is the SAME frame the character on the board uses when standing still
(views.textures.muncher_image, "closed_standing"), so the icon and the thing it
counts are unmistakably the same creature. Size and spacing come from the
swappable animation file (assets/muncher_animation/, life_scale + life_gap).

Owned by MovingSelectingSidePane, which builds it on the first set_lives call and
draws it with the rest of the pane. GameScreen never touches it directly -- it
calls _muncher_show_lives, which is the seam this replaced the plain text readout
behind.
"""

import pyglet
from config import get_muncher_anim
from views.textures import muncher_image


class MuncherLivesRow:
    """A left-aligned row of life icons inside a status-row-sized box."""

    def __init__(self, x, top, row_height):
        # `top` is the top edge of the status row and `row_height` its height, so
        # the icons hang from the same line the status text would sit on. Sizing
        # off the row (not raw pixels) keeps the lives in proportion on a retina
        # window, where the pane itself is sized in physical pixels.
        self._x = x
        self._top = top
        self._height = row_height * get_muncher_anim("life_scale")
        self._gap_fraction = get_muncher_anim("life_gap")
        self._batch = pyglet.graphics.Batch()
        self._sprites = []
        self._count = 0

    def set_count(self, count):
        """Show exactly `count` lives. Rebuilds only when the number actually
        changes -- this is called on every life event and at game start, and lives
        change a handful of times per game at most."""
        if count != self._count:
            self._count = max(0, count)
            self._rebuild()

    def draw(self):
        self._batch.draw()

    def delete(self):
        for sprite in self._sprites:
            sprite.delete()
        self._sprites = []

    def _rebuild(self):
        self.delete()
        image = muncher_image("closed_standing", self._height)
        scale = 1.0
        if image.height > 0:
            scale = self._height / image.height
        width = image.width * scale
        step = width * (1.0 + self._gap_fraction)
        for index in range(self._count):
            # The image is center-anchored (see muncher_image), so place each icon
            # at the center of its own slot.
            sprite = pyglet.sprite.Sprite(
                image,
                x=self._x + step * index + width / 2,
                y=self._top - self._height / 2,
                batch=self._batch,
            )
            sprite.scale = scale
            self._sprites.append(sprite)
