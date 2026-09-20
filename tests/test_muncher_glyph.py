"""The standing-on glyph overlay (game_screen.muncher_glyph_overlay).

The muncher covers the cell he stands on, so the overlay re-draws that cell's gram
back over him -- see views/muncher_glyph for why this cannot be a draw-order fix.
What matters here is WHEN it has something to draw: it must mirror a real text
glyph exactly, and must go blank for every cell that has no letters to rescue,
rather than leaving the last cell's gram stranded on screen.

Tested against fakes -- pyglet builds a Label with no GL window, so no fixture is
needed beyond a board stub.
"""

import pyglet

from views.muncher_glyph import MuncherGlyphOverlay


class _Label:
    """Stand-in for a cell's pyglet text Label, with the attributes the overlay
    copies. `visible` False is the hover preview having hidden the cell."""
    def __init__(self, text="ING", font_size=20, color=(10, 20, 30, 255),
                 x=40, y=50, visible=True):
        self.text = text
        self.font_size = font_size
        self.color = color
        self.x = x
        self.y = y
        self.visible = visible


class _Cell:
    def __init__(self, label):
        self.label = label


class _Board:
    """{(x, y): cell}; a missing key is off-board / empty, as the real grids'
    get_cell reports it."""
    def __init__(self, cells):
        self._cells = cells

    def get_cell(self, x, y):
        return self._cells.get((x, y))


def _wild_cell():
    """A wild cell renders its 'label' as a SPRITE, not text -- the overlay has to
    recognize that and skip it (and a wild cell cannot be eaten anyway)."""
    image = pyglet.image.SolidColorImagePattern((0, 0, 0, 255)).create_image(4, 4)
    return _Cell(pyglet.sprite.Sprite(image))


def test_it_mirrors_the_cell_label_exactly():
    # Style is copied rather than recomputed, so gram-length font sizing and the
    # score-gradient color stay right with no second copy of those rules.
    label = _Label(text="STR", font_size=17, color=(1, 2, 3, 255), x=64, y=96)
    overlay = MuncherGlyphOverlay()
    overlay.sync(_Board({(1, 1): _Cell(label)}), (1, 1))
    assert overlay._visible is True
    assert overlay._label.text == "STR"
    assert overlay._label.font_size == 17
    assert tuple(overlay._label.color) == (1, 2, 3, 255)
    assert (overlay._label.x, overlay._label.y) == (64, 96)


def test_it_follows_him_from_cell_to_cell():
    board = _Board({(1, 1): _Cell(_Label(text="ING", x=10, y=10)),
                    (2, 1): _Cell(_Label(text="QU", x=20, y=10))})
    overlay = MuncherGlyphOverlay()
    overlay.sync(board, (1, 1))
    assert overlay._label.text == "ING"
    overlay.sync(board, (2, 1))
    assert overlay._label.text == "QU"
    assert overlay._label.x == 20


def test_it_goes_blank_on_a_cell_with_nothing_to_redraw():
    # Each of these would otherwise strand the PREVIOUS cell's gram on screen,
    # which is worse than drawing nothing: it would be a letter that is not there.
    board = _Board({
        (0, 0): _Cell(_Label()),          # a real glyph, to light it up first
        (1, 0): _Cell(None),              # eaten / empty cell
        (2, 0): _wild_cell(),             # wild: a sprite, not text
        (3, 0): _Cell(_Label(text="")),   # a label with no letters
        (4, 0): _Cell(_Label(visible=False)),  # hidden by the hover preview
    })
    overlay = MuncherGlyphOverlay()
    for pos in ((1, 0), (2, 0), (3, 0), (4, 0), (9, 9), None):
        overlay.sync(board, (0, 0))
        assert overlay._visible is True, "expected the real glyph to light up"
        overlay.sync(board, pos)
        assert overlay._visible is False, pos


def test_a_blank_overlay_draws_nothing():
    overlay = MuncherGlyphOverlay()
    overlay.sync(_Board({}), (0, 0))
    # draw() is a no-op rather than a crash on an unsynced/blank label.
    overlay.draw()
