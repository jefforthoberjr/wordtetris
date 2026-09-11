"""Offline: turn the raw Word Muncher art into game-ready sprite PNGs.

The source frames (src/assets/sprites/original_word_muncher/*.png) are 1254x1254
RGB with the background painted SOLID BLACK -- no alpha channel. The board draws
on a white background, so dropped in as-is each frame would be a black square.
This tool does the two conversions ONCE, offline, so the game never pays for them:

  1. COLOR KEY: every pixel at (or near) black becomes fully transparent. The
     character's own colors (green / blue / white) are nowhere near black, so a
     plain threshold is enough -- no edge blending to undo, because the art is
     flat low-bit pixel art with hard edges.
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

# Integer downsample factors applied to the CROPPED frame. 3 and 6 give a
# roughly cell-sized frame and a comfortable 2x for large cells / retina.
FACTORS = [3, 6]

# Background pixels kept around the cropped character on every side, in SOURCE
# pixels -- a little breathing room so a rounding error can never shave a limb.
CROP_PAD = 6

# A pixel whose channels are all <= this counts as background. The art's darkest
# real color is a deep blue (0, 0, 139), well above it on the blue channel.
BLACK_THRESHOLD = 8


def content_bounds(data, source):
    """(left, bottom, right, top) of the non-background content in one frame, as
    inclusive source-pixel indices. Scans whole rows/columns with max() over a
    strided slice, which runs at C speed -- a per-pixel Python loop over the
    1254^2 source would take seconds per frame."""
    width, height = data.width, data.height
    left, bottom, right, top = width, height, -1, -1
    for row in range(height):
        start = row * width * 3
        if max(source[start:start + width * 3]) > BLACK_THRESHOLD:
            if bottom > row:
                bottom = row
            top = row
    for col in range(width):
        start = col * 3
        # Every byte of this column's pixels: R at start, G/B follow, so step by
        # the pixel stride three times and take the brightest of the three.
        brightest = max(max(source[start + channel::width * 3]) for channel in range(3))
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


def key_and_scale(data, source, crop, factor):
    """Return (width, height, rgba_bytes): the `crop` box of a frame, nearest-
    sampled down by `factor`, with near-black pixels made fully transparent.
    Touches only the sampled OUTPUT pixels, so the cost is the output size."""
    left, bottom, right, top = crop
    out_w = int((right - left + 1) / factor)
    out_h = int((top - bottom + 1) / factor)
    rgba = bytearray(out_w * out_h * 4)
    for row in range(out_h):
        src_row = bottom + row * factor
        for col in range(out_w):
            i = (src_row * data.width + left + col * factor) * 3
            r = source[i]
            g = source[i + 1]
            b = source[i + 2]
            o = (row * out_w + col) * 4
            rgba[o] = r
            rgba[o + 1] = g
            rgba[o + 2] = b
            if r <= BLACK_THRESHOLD and g <= BLACK_THRESHOLD and b <= BLACK_THRESHOLD:
                rgba[o + 3] = 0
            else:
                rgba[o + 3] = 255
    return out_w, out_h, bytes(rgba)


def load_frame(filename):
    """(image_data, rgb_bytes) for one source frame -- read once and reused for
    both the bounds scan and every output size."""
    image = pyglet.image.load(os.path.join(SOURCE_DIR, filename))
    data = image.get_image_data()
    return data, data.get_data("RGB", data.width * 3)


def padded(crop, width, height):
    """The crop box grown by CROP_PAD on every side, clamped to the canvas."""
    left, bottom, right, top = crop
    left = max(0, left - CROP_PAD)
    bottom = max(0, bottom - CROP_PAD)
    right = min(width - 1, right + CROP_PAD)
    top = min(height - 1, top + CROP_PAD)
    return left, bottom, right, top


def main():
    frames = {}
    for filename, state in FRAMES.items():
        frames[state] = load_frame(filename)
        print("read {0}".format(filename))
    bounds = []
    for state in frames:
        data, source = frames[state]
        bounds.append(content_bounds(data, source))
    first_data = frames[list(frames)[0]][0]
    crop = padded(union_bounds(bounds), first_data.width, first_data.height)
    print("shared crop box (l, b, r, t): {0}".format(crop))
    for state in frames:
        data, source = frames[state]
        for factor in FACTORS:
            width, height, rgba = key_and_scale(data, source, crop, factor)
            out = pyglet.image.ImageData(width, height, "RGBA", rgba, pitch=width * 4)
            name = "muncher_{0}_{1}x{2}.png".format(state, width, height)
            out.save(os.path.join(OUT_DIR, name))
            print("wrote {0}".format(name))


main()
