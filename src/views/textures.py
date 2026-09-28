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
    "needs_rearrange": [
        (96, "icon_error_rearrange_96x64.png"),
        (192, "icon_error_rearrange_192x128.png"),
        (384, "icon_error_rearrange_384x256.png"),
        (1536, "icon_error_rearrange_1536x1024.png"),
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
# Several distinct rejection reasons share the one "duplicate" artwork. The three
# not_on_board sub-reasons (see game_screen._not_on_board_reason) each have their own
# icon: missing-letter -> the absentletter art, needs-rearrange -> the rearrange art
# (right pieces, wrong spots), gram-mismatch -> the tiling art. The bare
# "not_on_board" key stays mapped (to missing_letter) for old session logs that still
# carry the pre-split reason.
_REASON_TO_ICON = {
    "not_in_dictionary": "not_in_dictionary",
    "not_on_board": "missing_letter",
    "not_on_board_missing_letter": "missing_letter",
    "not_on_board_needs_rearrange": "needs_rearrange",
    "not_on_board_gram_mismatch": "gram_mismatch",
    "too_short": "too_short",
    "already_cleared": "duplicate",
    # The muncher's dead-end forced clear (game_screen.muncher_dead_end): the eaten
    # letters can never become a word, which is the not-a-word artwork's message.
    "muncher_dead_end": "not_in_dictionary",
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


# The Word Muncher character (game_screen.mode: rule_mode_muncher), one entry per
# animation state -> its native sizes (height, filename), smallest first. Built
# offline from the raw art by tools/make_muncher_sprites.py, which crops every
# frame to ONE shared box and keys the black background out to alpha -- so the
# frames are interchangeable in place and drop onto the white board cleanly.
# Same "load the smallest size at least as tall as the target" rule as the icons
# above, so the character always scales DOWN.
#
# The filenames here carry NO directory: the character has several skins, and
# which one is loaded comes from the rule assets.muncher_sprites at load time (see
# muncher_image). Every skin ships the same state names at the same sizes -- the
# build tool crops all of them to one box across all sets -- so this table
# describes every skin at once.
_MUNCHER_TEXTURES = {
    "closed_standing": [
        (134, "muncher_closed_standing_110x134.png"),
        (268, "muncher_closed_standing_220x268.png"),
    ],
    "closed_walking": [
        (134, "muncher_closed_walking_110x134.png"),
        (268, "muncher_closed_walking_220x268.png"),
    ],
    "open_standing": [
        (134, "muncher_open_standing_110x134.png"),
        (268, "muncher_open_standing_220x268.png"),
    ],
    # The materialize dissolve, faintest first. Unlike the three frames above
    # these are PARTIALLY TRANSPARENT by design -- the character is drawn in
    # pieces, more of him in each frame -- so they read as a fade even though no
    # sprite opacity is being touched. Played forward he appears; played backward
    # (fade_03 -> fade_01) he dissolves away. See MuncherSprite's fade states and
    # tools/make_muncher_sprites.py (they skip the black color-key).
    "fade_01": [
        (134, "muncher_fade_01_110x134.png"),
        (268, "muncher_fade_01_220x268.png"),
    ],
    "fade_02": [
        (134, "muncher_fade_02_110x134.png"),
        (268, "muncher_fade_02_220x268.png"),
    ],
    "fade_03": [
        (134, "muncher_fade_03_110x134.png"),
        (268, "muncher_fade_03_220x268.png"),
    ],
    # The BELLY overlays, smallest first. These are not frames of the character --
    # they are a stomach blob drawn OVER whichever frame is showing, so the same
    # belly rides the standing, walking and chewing art. They share the crop box
    # with every frame above, which is the whole alignment story: drawn at the same
    # place and the same size as the character, the blob lands on his middle.
    "belly_01": [
        (134, "muncher_belly_01_110x134.png"),
        (268, "muncher_belly_01_220x268.png"),
    ],
    "belly_02": [
        (134, "muncher_belly_02_110x134.png"),
        (268, "muncher_belly_02_220x268.png"),
    ],
    "belly_03": [
        (134, "muncher_belly_03_110x134.png"),
        (268, "muncher_belly_03_220x268.png"),
    ],
    "belly_04": [
        (134, "muncher_belly_04_110x134.png"),
        (268, "muncher_belly_04_220x268.png"),
    ],
}


def muncher_sprite_set():
    """The active skin's directory name, from the rule assets.muncher_sprites.

    Read HERE rather than cached in a module global on purpose: this module is
    imported long before apply_game_mode merges a game mode's overrides into
    CONFIG, so a module-level read would freeze the base config's skin and every
    mode that picks a different one would be silently ignored -- the same
    freeze-at-import trap the class-level config constants document."""
    from config import CONFIG
    return CONFIG["rules"]["assets.muncher_sprites"]


def muncher_image(state, target_height):
    """Load (and cache) the muncher frame for `state` ("closed_standing" /
    "closed_walking" / "open_standing" / "fade_*" / "belly_*") at the smallest
    native height at least `target_height` (or the largest if the target is bigger
    than all of them), from the active skin. Center-anchored, so drawing it at a
    cell's center sits it on the cell."""
    textures = _MUNCHER_TEXTURES[state]
    filename = textures[-1][1]
    for height, candidate in textures:
        if height >= target_height:
            filename = candidate
            break
    # The skin directory rides in the cache key, so two skins never collide and
    # switching modes mid-session reloads rather than serving the old face.
    name = os.path.join("sprites", muncher_sprite_set(), filename)
    if name not in _image_cache:
        image = pyglet.image.load(os.path.join(_ASSETS, name))
        image.anchor_x = math.floor(image.width / 2)
        image.anchor_y = math.floor(image.height / 2)
        _image_cache[name] = image
    return _image_cache[name]
