"""Offline: turn the raw Word Muncher art into game-ready sprite PNGs.

The source frames (src/assets/sprites/original_word_muncher/*.png) are all
1254x1254. The ORIGINAL walk/bite frames paint their background SOLID BLACK with
no usable alpha; the board draws on a white background, so dropped in as-is each
one would be a black square. The later fade frames instead ship a genuinely
transparent background. This tool does the conversions ONCE, offline, so the game
never pays for them:

  1. BACKGROUND -> ALPHA, by one of two routes, because the art arrives in two
     conventions (see FRAMES / ALPHA_FRAMES):
     a. COLOR KEY (the walk/bite frames): every pixel at (or near) black becomes
        fully transparent. The character's own colors (green / blue / white) are
        nowhere near black, so a plain threshold is enough -- no edge blending to
        undo, because the art is flat low-bit pixel art with hard edges. Output
        alpha is therefore binary: 0 or 255.
     b. ALPHA PASSTHROUGH (the fade-in frames): these already ship a real alpha
        channel with a transparent background, and their whole point is partial
        coverage -- the fade is a DISSOLVE, lighting up more of the character in
        each frame. Color-keying them would force every lit pixel to alpha 255
        and flatten the dissolve into a solid character, so their source alpha is
        copied through untouched.
  2. CROP: the source frames are mostly empty background -- the character fills
     only the middle ~40% of the canvas. Every frame is cropped to ONE shared
     bounding box (the union across all frames, so the character never jumps
     between frames), which makes the sprite's on-screen size a direct multiple
     of the cell size instead of a guess about padding.
  3. DOWNSAMPLE: emit a couple of smaller sizes by NEAREST sampling at an exact
     integer factor (1254 = 3 * 418 = 6 * 209). Nearest keeps the hard pixel-art
     edges crisp; a box average would smear the keyed-out black into a dark fringe
     around every edge. The game loads the smallest size at least as big as the
     cell it draws into (same "scale DOWN, never up" rule as the wild-vowel
     emblem and the error icons -- see views/textures.py).

Run from the repo root, with the venv active:

    python tools/make_muncher_sprites.py

Writes src/assets/sprites/muncher_<state>_<size>.png. Rerunnable; overwrites.
Pure pyglet + stdlib, no numpy / PIL (they are not project dependencies).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pyglet


SOURCE_DIR = os.path.join(os.path.dirname(__file__), "..", "src", "assets",
                          "sprites", "original_word_muncher")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "src", "assets", "sprites")

# Source frame -> the state name the game addresses it by. "mouthopen_walking"
# is deliberately absent: the current design never shows an open mouth in
# motion (a bite happens standing still), so it is not converted. Add it here
# if a later animation rule wants it.
FRAMES = {
    "wordmuncher_mouthclosed_standing.png": "closed_standing",
    "wordmuncher_mouthclosed_walking.png": "closed_walking",
    "wordmuncher_mouthopen_standing.png": "open_standing",
}

# The same, for source frames that ALREADY carry a transparent background in a
# real alpha channel -- converted by route (b) above (alpha passthrough, no color
# key). The three fade frames are a dissolve, ordered least-formed to most:
# fade_01 is the faintest scatter of pixels and fade_03 is nearly the whole
# character, so playing 01 -> 02 -> 03 -> closed_standing materializes him and
# the reverse dissolves him away. Both dicts share ONE crop box, so a fade frame
# and a standing frame put the character in exactly the same place.
ALPHA_FRAMES = {
    "wordmuncher_fadein_01.png": "fade_01",
    "wordmuncher_fadein_02.png": "fade_02",
    "wordmuncher_fadein_03.png": "fade_03",
    # BELLY overlays, smallest first: a stomach blob drawn ON TOP of whichever
    # walk/bite frame is showing, sized by how many letters he is carrying. They
    # are partial images by design -- just the belly, transparent everywhere else
    # -- so they go through the alpha path for the same reason the fade frames do.
    # Sharing the crop box is what makes them line up: the blob is already drawn
    # in the right place on the source canvas, so cropping it identically lands it
    # on his middle with no offset to tune.
    "bellyoverlay_size01.png": "belly_01",
    "bellyoverlay_size02.png": "belly_02",
    "bellyoverlay_size03.png": "belly_03",
    "bellyoverlay_size04.png": "belly_04",
}

# Integer downsample factors applied to the CROPPED frame. 3 and 6 give a
# roughly cell-sized frame and a comfortable 2x for large cells / retina.
FACTORS = [3, 6]

# Background pixels kept around the cropped character on every side, in SOURCE
# pixels -- a little breathing room so a rounding error can never shave a limb.
CROP_PAD = 6

# A pixel whose channels are all <= this counts as background. The art's darkest
# real color is a deep blue (0, 0, 139), well above it on the blue channel.
BLACK_THRESHOLD = 8


def content_bounds(data, source, alpha_keyed):
    """(left, bottom, right, top) of the non-background content in one frame, as
    inclusive source-pixel indices. Scans whole rows/columns with max() over a
    strided slice, which runs at C speed -- a per-pixel Python loop over the
    1254^2 source would take seconds per frame.

    `alpha_keyed` picks which byte says "this pixel is background": the alpha
    channel for a frame that already has one, or brightness for a black-keyed
    frame (whose alpha is a useless 255 everywhere, so testing it would call the
    whole canvas content). Everything here is in RGBA -- the loader normalizes
    both conventions to four channels so the two paths share one stride."""
    width, height = data.width, data.height
    # Which of the four bytes of a pixel decide whether it is content: alpha
    # alone, or any of R/G/B (the brightest wins the near-black test).
    channels = (3,) if alpha_keyed else (0, 1, 2)
    left, bottom, right, top = width, height, -1, -1
    for row in range(height):
        start = row * width * 4
        end = start + width * 4
        brightest = max(max(source[start + channel:end:4]) for channel in channels)
        if brightest > BLACK_THRESHOLD:
            if bottom > row:
                bottom = row
            top = row
    for col in range(width):
        start = col * 4
        # Step by the pixel-row stride, once per channel of interest.
        brightest = max(max(source[start + channel::width * 4]) for channel in channels)
        if brightest > BLACK_THRESHOLD:
            if left > col:
                left = col
            right = col
    return left, bottom, right, top


def union_bounds(frames):
    """The single crop box covering the content of EVERY frame, padded by
    CROP_PAD and clamped to the canvas. Shared across frames so the character
    holds still while its legs animate."""
    left = min(bounds[0] for bounds in frames)
    bottom = min(bounds[1] for bounds in frames)
    right = max(bounds[2] for bounds in frames)
    top = max(bounds[3] for bounds in frames)
    return left, bottom, right, top


def key_and_scale(data, source, crop, factor, alpha_keyed):
    """Return (width, height, rgba_bytes): the `crop` box of a frame, nearest-
    sampled down by `factor`. Touches only the sampled OUTPUT pixels, so the cost
    is the output size.

    With `alpha_keyed` the source alpha is copied straight through (the fade
    frames' dissolve IS their alpha -- see route (b) in the module docstring).
    Without it, the original color-key runs: near-black becomes fully
    transparent, everything else fully opaque."""
    left, bottom, right, top = crop
    out_w = int((right - left + 1) / factor)
    out_h = int((top - bottom + 1) / factor)
    rgba = bytearray(out_w * out_h * 4)
    for row in range(out_h):
        src_row = bottom + row * factor
        for col in range(out_w):
            i = (src_row * data.width + left + col * factor) * 4
            r = source[i]
            g = source[i + 1]
            b = source[i + 2]
            o = (row * out_w + col) * 4
            rgba[o] = r
            rgba[o + 1] = g
            rgba[o + 2] = b
            if alpha_keyed:
                rgba[o + 3] = source[i + 3]
            elif r <= BLACK_THRESHOLD and g <= BLACK_THRESHOLD and b <= BLACK_THRESHOLD:
                rgba[o + 3] = 0
            else:
                rgba[o + 3] = 255
    return out_w, out_h, bytes(rgba)


def load_frame(filename):
    """(image_data, rgba_bytes) for one source frame -- read once and reused for
    both the bounds scan and every output size. Always RGBA, even for the
    black-background originals, so the bounds scan and the sampler need only one
    stride; those frames simply carry a uniform 255 alpha that nothing reads."""
    image = pyglet.image.load(os.path.join(SOURCE_DIR, filename))
    data = image.get_image_data()
    return data, data.get_data("RGBA", data.width * 4)


def padded(crop, width, height):
    """The crop box grown by CROP_PAD on every side, clamped to the canvas."""
    left, bottom, right, top = crop
    left = max(0, left - CROP_PAD)
    bottom = max(0, bottom - CROP_PAD)
    right = min(width - 1, right + CROP_PAD)
    top = min(height - 1, top + CROP_PAD)
    return left, bottom, right, top


def main():
    # state -> (image_data, rgba_bytes, alpha_keyed). Both source conventions go
    # into ONE dict so the crop box below is the union over every frame of both:
    # a fade frame and a standing frame have to land the character on the same
    # pixels, or he would jump as the fade hands off to the idle art.
    frames = {}
    for source_frames, alpha_keyed in ((FRAMES, False), (ALPHA_FRAMES, True)):
        for filename, state in source_frames.items():
            data, source = load_frame(filename)
            frames[state] = (data, source, alpha_keyed)
            print("read {0}".format(filename))
    bounds = []
    for state in frames:
        data, source, alpha_keyed = frames[state]
        bounds.append(content_bounds(data, source, alpha_keyed))
    first_data = frames[list(frames)[0]][0]
    crop = padded(union_bounds(bounds), first_data.width, first_data.height)
    print("shared crop box (l, b, r, t): {0}".format(crop))
    for state in frames:
        data, source, alpha_keyed = frames[state]
        for factor in FACTORS:
            width, height, rgba = key_and_scale(data, source, crop, factor,
                                                alpha_keyed)
            out = pyglet.image.ImageData(width, height, "RGBA", rgba, pitch=width * 4)
            name = "muncher_{0}_{1}x{2}.png".format(state, width, height)
            out.save(os.path.join(OUT_DIR, name))
            print("wrote {0}".format(name))


main()
