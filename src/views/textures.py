import math
import os
import pyglet


# The wild-vowel emblem, available at several native resolutions. We load the
# smallest one at least as tall as the target cell, so it scales DOWN (crisp)
# rather than up. The white background is currently baked into the PNG; alpha
# versions can drop in later by swapping these files.
_ASSETS = os.path.join(os.path.dirname(__file__), "..", "assets")
_WILD_VOWEL_TEXTURES = [
    (23, "vowel_rings_tighter_18x23.png"),
    (46, "vowel_rings_tighter_36x46.png"),
    (91, "vowel_rings_tighter_72x91.png"),
    (182, "vowel_rings_tighter_143x182.png"),
    (364, "vowel_rings_tighter_286x364.png"),
]
_image_cache = {}


def wild_vowel_image(target_height):
    """Load (and cache) the wild-vowel emblem texture that best fits a cell of
    `target_height` pixels: the smallest native texture at least that tall, or
    the largest if the cell is bigger than all of them. The returned image is
    center-anchored, so a sprite placed at a cell's center sits centered."""
    name = _WILD_VOWEL_TEXTURES[-1][1]
    for height, candidate in _WILD_VOWEL_TEXTURES:
        if height >= target_height:
            name = candidate
            break
    if name not in _image_cache:
        image = pyglet.image.load(os.path.join(_ASSETS, name))
        image.anchor_x = math.floor(image.width / 2)
        image.anchor_y = math.floor(image.height / 2)
        _image_cache[name] = image
    return _image_cache[name]
