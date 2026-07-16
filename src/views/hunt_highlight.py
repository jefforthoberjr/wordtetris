"""The MOVING-phase word-hunt highlight layer.

A player types a word in the moving side pane and the grams on the board that
belong to it light up. Rather than recolor the cells' base labels (which would
entangle this with the loading-fade / relabel paths), each gram cell gets an
OPTIONAL overlay drawn on TOP of its base label: a transparent per-letter paint
sheet. The base label always draws the letters in their normal color; the overlay
draws ONLY the highlighted letters in the hunt color, leaving the rest alpha-0 so
the base shows through (design note: base = "the letters always", overlay =
"highlight paint on top"). Because the overlay shares the base's exact text, font,
size, weight, anchor and position, a matched letter lands pixel-perfect over its
base glyph and the transparent slots reveal the base underneath.

Two things this layer is built around:
  * PRE-ALLOCATION for flat frame times. Each overlay is built ONCE (with the
    piece, in the pieces' constructors) carrying the gram's text; a highlight is
    then only a per-glyph COLOR flip -- never a text change -- so typing costs a
    handful of ~3us color writes, not label creation / glyph reshaping. Idle
    overlays are visible=False, so they cost nothing to draw.
  * A SWAPPABLE STYLE (game_screen.hunt_highlight_style). Today the only style is
    a text recolor; a future rect-tint or outline style is a new rule returning an
    object with the same tiny interface (set_position / set_matched / clear /
    delete), dropped into the same shared batch. Keep the style rules at the top.

The overlays share one batch (like get_shape_shader / get_text_shader) so the
pieces need not thread a batch through every constructor; GameScreen.draw() draws
it once, above the piece glyphs. Overlays are registered here so a new game can
delete last game's before rebuilding the board (reset_hunt_highlight).
"""

import pyglet

from config import get_color, select_rule


# Shared batch for every hunt overlay, drawn on top of the board/piece glyphs.
_batch = pyglet.graphics.Batch()

# Every live overlay, so a new game can tear them all down (their base labels are
# dropped when the piece batches are rebuilt; without this the overlays would
# linger in the shared batch across games).
_overlays = []

_HIGHLIGHT_COLOR = get_color("board.hunt_highlight")
_TRANSPARENT = (0, 0, 0, 0)


def get_hunt_highlight_batch():
    """The shared batch holding every hunt overlay. GameScreen.draw() draws it
    just after the piece batch so overlays sit on top of the gram glyphs."""
    return _batch


def reset_hunt_highlight():
    """Delete every overlay from the shared batch. Called when a new game rebuilds
    the board, so last game's overlays don't linger in GPU memory."""
    for overlay in _overlays:
        overlay.delete()
    _overlays.clear()


# --- highlight-style rule (game_screen.hunt_highlight_style) ------------------
# Which visual a highlighted gram cell gets. Only the text-recolor style exists
# today; a rect-tint / outline style would be a sibling rule returning an object
# with the same interface. Swapped from one place (config.yaml).

def rule_hunt_style_text_recolor(text, font_size, bold):
    """Recolor the matching letters of the gram, in place, on a transparent
    overlay label (the first / only style)."""
    return _TextRecolorOverlay(text, font_size, bold)


_HUNT_STYLE_RULES = {
    "rule_hunt_style_text_recolor": rule_hunt_style_text_recolor,
}


def make_hunt_overlay(text, font_size, bold=True):
    """Build the overlay for one gram cell via the active style rule, or None for
    empty text (a wild vowel has no letters to highlight -- it renders as a sprite,
    not a label, and hunts ignore wilds). Called from the piece constructors. The
    rule is resolved per call (not cached at import) so a game mode's
    game_screen.hunt_highlight_style override takes effect -- this module is
    imported before apply_game_mode swaps CONFIG, so an import-time binding would
    freeze the base config's rule."""
    if not text:
        return None
    return select_rule("game_screen.hunt_highlight_style", _HUNT_STYLE_RULES)(text, font_size, bold)


# --- match rule (game_screen.hunt_highlight) ---------------------------------
# WHICH letters of a board gram light up for the typed search word. Each rule
# takes the gram's text and the search word (both upper-case) and returns one bool
# per letter of the gram -- exactly the shape the overlay's set_matched wants.
# Swapped from one place (config.yaml).

def rule_hunt_none(gram_text, search):
    """Light nothing -- the hunt highlight is off. Typing / hunt matching still
    drive the field and submit; only the on-board green paint is suppressed. Used
    by modes that want a bare typing surface (constellation speed type)."""
    return [False] * len(gram_text)


def rule_hunt_full_gram(gram_text, search):
    """Light a cell only if its WHOLE gram is a contiguous chunk of the search word
    (INDICATIVE lights 'IVE', not 'CU' / 'EN' / 'ING'); then all its letters
    color."""
    hit = bool(gram_text) and gram_text in search
    return [hit] * len(gram_text)


def rule_hunt_single_letters(gram_text, search):
    """Light each single letter of the gram that appears ANYWHERE in the search
    word, even a partial / out-of-order cell (INDICATIVE lights C of 'CU', both of
    'EN', I + N of 'ING')."""
    return [ch in search for ch in gram_text]


# Mirror of game_screen._STRICT_VOWELS (Y is a CONSONANT); kept local to avoid a
# circular import (game_screen imports this module). Keep in sync.
_MANIP_VOWELS = set("AEIOU")


def _dedup_collapse(gram_text):
    """If the gram holds one adjacent DOUBLED consonant -- the shape a right-click
    would collapse, C -> CC's reverse (MMP, ANN, BBA, SST, ARRE, MMER, MERR) --
    return (collapsed_text, kept_positions): the gram with the redundant copy
    dropped, plus the ORIGINAL indices that survive. The DROPPED copy is the outer
    one so the survivors read as the contiguous chunk (MMP -> 'MP' keeping [1, 2];
    ANN -> 'AN' keeping [0, 1]). Only consonant doubles collapse -- a vowel double
    (EE) has no manipulation rule, so it's ignored. Returns None when there's no
    collapsible consonant double. Mirrors the game_screen.rightclick_* collapses."""
    n = len(gram_text)
    for i in range(n - 1):
        ch = gram_text[i]
        if ch == gram_text[i + 1] and ch not in _MANIP_VOWELS:
            if i == 0:
                kept = list(range(1, n))                     # drop the leading copy
            elif i + 1 == n - 1:
                kept = list(range(0, n - 1))                 # drop the trailing copy
            else:
                kept = [j for j in range(n) if j != i + 1]   # interior: drop the later copy
            return "".join(gram_text[j] for j in kept), kept
    return None


def rule_hunt_full_gram_or_dedup(gram_text, search):
    """Like rule_hunt_full_gram, but also lights a gram that is one right-click (a
    doubling/dedup collapse) away from being a contiguous chunk of the search
    word. If the whole gram already fits, every letter lights (the full-gram
    case). Otherwise, if collapsing its doubled consonant would fit -- search
    'LAMP', gram 'MMP' collapses to 'MP' -- only the SURVIVING letters light; the
    redundant doubled copy stays dark, signalling 'one right-click makes this
    usable'. Mirrors the game_screen.rightclick_* doubling rules."""
    if not gram_text:
        return []
    if gram_text in search:
        return [True] * len(gram_text)
    collapse = _dedup_collapse(gram_text)
    if collapse is not None:
        collapsed, kept = collapse
        if collapsed and collapsed in search:
            kept_set = set(kept)
            return [i in kept_set for i in range(len(gram_text))]
    return [False] * len(gram_text)


_HUNT_MATCH_RULES = {
    "rule_hunt_none": rule_hunt_none,
    "rule_hunt_full_gram": rule_hunt_full_gram,
    "rule_hunt_single_letters": rule_hunt_single_letters,
    "rule_hunt_full_gram_or_dedup": rule_hunt_full_gram_or_dedup,
}


def get_hunt_match_rule():
    """The active match rule (game_screen.hunt_highlight)."""
    return select_rule("game_screen.hunt_highlight", _HUNT_MATCH_RULES)


class _TextRecolorOverlay:
    """A transparent DocumentLabel sitting exactly over one gram's base label,
    painting only the matched letters in the hunt color. Pre-built with the gram
    text so highlighting is a per-glyph color flip, never a text change."""

    def __init__(self, text, font_size, bold):
        self._text = text
        self._doc = pyglet.text.document.FormattedDocument(text)
        # Match the base label's shaping exactly (SquarePiece/HexPiece build the
        # base with weight='bold' at this font_size) so the overlay glyphs align.
        weight = "bold" if bold else "normal"
        self._doc.set_style(0, len(text), {
            "font_size": font_size,
            "weight": weight,
            "color": _TRANSPARENT,
        })
        self._label = pyglet.text.DocumentLabel(
            document=self._doc,
            anchor_x="center", anchor_y="center",
            batch=_batch,
        )
        self._label.visible = False
        _overlays.append(self)

    def set_position(self, x, y):
        """Track the base label's resolved position (inherits any per-cell nudge,
        e.g. the hex vertical recenter, because it copies the base's final x/y)."""
        self._label.x = x
        self._label.y = y

    def set_matched(self, matched):
        """`matched` is one bool per letter. Paint matched letters in the hunt
        color and the rest transparent, and show the overlay iff any letter
        matches (an all-miss overlay draws nothing at all)."""
        any_match = False
        for i in range(len(self._text)):
            on = i < len(matched) and matched[i]
            self._doc.set_style(i, i + 1, {"color": _HIGHLIGHT_COLOR if on else _TRANSPARENT})
            any_match = any_match or on
        self._label.visible = any_match

    def clear(self):
        """Hide the overlay (no letters highlighted)."""
        self._label.visible = False

    def set_text(self, text, font_size, bold=True):
        """Re-text the overlay after its cell's gram changed (relabel_cell -- the
        digram right-click flip / partial-clear leftover). This is a text change,
        not a color flip, so it's for that rare path only; it re-applies the base
        transparent style and hides the overlay (a following refresh re-lights it)."""
        self._text = text
        self._label.text = text
        weight = "bold" if bold else "normal"
        self._doc.set_style(0, len(text), {
            "font_size": font_size,
            "weight": weight,
            "color": _TRANSPARENT,
        })
        self._label.visible = False

    def delete(self):
        self._label.delete()
