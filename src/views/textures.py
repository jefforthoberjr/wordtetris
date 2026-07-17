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
    "missing_letter": [
        (96, "icon_error_wordnotonboard_absentletter_96x64.png"),
        (192, "icon_error_wordnotonboard_absentletter_192x128.png"),
        (384, "icon_error_wordnotonboard_absentletter_384x256.png"),
        (1536, "icon_error_wordnotonboard_absentletter_1536x1024.png"),
    ],
    "gram_mismatch": [
        (96, "icon_error_wordnotonboard_tilingmismatch_96x64.png"),
        (192, "icon_error_wordnotonboard_tilingmismatch_192x128.png"),
        (384, "icon_error_wordnotonboard_tilingmismatch_384x256.png"),
        (768, "icon_error_wordnotonboard_tilingmismatch_768x512.png"),
        (1536, "icon_error_wordnotonboard_tilingmismatch_1536x1024.png"),
    ],
    "too_short": [
        (104, "icon_error_wordtooshort_104x60.png"),
        (208, "icon_error_wordtooshort_208x119.png"),
        (415, "icon_error_wordtooshort_415x237.png"),
        (830, "icon_error_wordtooshort_830x474.png"),
        (1659, "icon_error_wordtooshort_1659x948.png"),
    ],
    "duplicate": [
        (104, "icon_error_duplicateword_104_64.png"),
        (207, "icon_error_duplicateword_207_128.png"),
        (414, "icon_error_duplicateword_414_256.png"),
        (1139, "icon_error_duplicateword_1139_705.png"),
    ],
}
# Several distinct rejection reasons share the one "duplicate" artwork. The two
# not_on_board sub-reasons (see game_screen._not_on_board_reason) now each have their
# own icon: missing-letter -> the absentletter art, gram-mismatch -> the tiling
# art. The bare "not_on_board" key stays mapped (to missing_letter) for old session
# logs that still carry the pre-split reason.
_REASON_TO_ICON = {
    "not_in_dictionary": "not_in_dictionary",
    "not_on_board": "missing_letter",
    "not_on_board_missing_letter": "missing_letter",
    "not_on_board_gram_mismatch": "gram_mismatch",
    "too_short": "too_short",
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
