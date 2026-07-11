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


# Submission-rejection icons, one artwork per reason family, each at several
# native resolutions (width, filename). Same load-smallest-that-fits idea as the
# wild-vowel emblem so we scale DOWN, not up. Reasons not listed here (too_short,
# not_involved, not_fossil) have no icon and fall back to the text message.
_ERROR_ICON_TEXTURES = {
    "not_in_dictionary": [
        (64, "icon_error_wordnotindictionary_64x64.png"),
        (128, "icon_error_wordnotindictionary_128x128.png"),
        (256, "icon_error_wordnotindictionary_256x256.png"),
        (1254, "icon_error_wordnotindictionary_1254x1254.png"),
    ],
    "not_on_board": [
        (96, "icon_error_wordnotonboard_96x64.png"),
        (192, "icon_error_wordnotonboard_192x128.png"),
        (384, "icon_error_wordnotonboard_384x256.png"),
        (1536, "icon_error_wordnotonboard_1536x1024.png"),
    ],
    "duplicate": [
        (104, "icon_error_duplicateword_104_64.png"),
        (207, "icon_error_duplicateword_207_128.png"),
        (414, "icon_error_duplicateword_414_256.png"),
        (1139, "icon_error_duplicateword_1139_705.png"),
    ],
}
# Several distinct rejection reasons share the one "duplicate" artwork.
_REASON_TO_ICON = {
    "not_in_dictionary": "not_in_dictionary",
    "not_on_board": "not_on_board",
    "already_cleared": "duplicate",
    "already_selected_one_way": "duplicate",
    "every_way_selected": "duplicate",
}


def error_icon_image(reason, target_width):
    """Load (and cache) the center-anchored error icon for a rejection `reason`,
    at the smallest native width at least `target_width` (or the largest if the
    slot is wider than all of them). Returns None for a reason with no icon, so
    the caller can fall back to the text message."""
    family = _REASON_TO_ICON.get(reason)
    if family is None:
        return None
    textures = _ERROR_ICON_TEXTURES[family]
    name = textures[-1][1]
    for width, candidate in textures:
        if width >= target_width:
            name = candidate
            break
    if name not in _image_cache:
        image = pyglet.image.load(os.path.join(_ASSETS, name))
        image.anchor_x = math.floor(image.width / 2)
        image.anchor_y = math.floor(image.height / 2)
        _image_cache[name] = image
    return _image_cache[name]


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
