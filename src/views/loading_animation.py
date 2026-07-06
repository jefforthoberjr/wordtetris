from config import get_loading_anim


# --- fade easing rules -------------------------------------------------
# How a fade's alpha moves across its `duration`: given progress `p` in [0, 1]
# (0 = fade start, 1 = fade end), return the eased fraction in [0, 1] that maps
# to opacity 0..255. Swap the active rule via the loading_animation.yaml
# `easing` key. New curves (e.g. ease-in-out) drop into the registry below.

def rule_fade_linear(p):
    """Constant-rate ramp: opacity rises in lockstep with elapsed time."""
    return p


_FADE_EASING_RULES = {
    "rule_fade_linear": rule_fade_linear,
}


def _select_fade_easing():
    """Resolve the easing rule named by the loading_animation.yaml `easing` key."""
    name = get_loading_anim("easing")
    return _FADE_EASING_RULES[name]


# --- fade handles ------------------------------------------------------
# A handle wraps one render object and applies a fade fraction (0 = start,
# 1 = revealed) to it. Two kinds, chosen per element by the game screen:

class AlphaFade:
    """Fade by ramping the object's .opacity 0 -> 255: it emerges from whatever
    is drawn behind it, so this is background-agnostic. Used for everything
    except the hex inner fill -- rims, glyphs, grid lines, square cells, and
    wild-vowel sprites."""

    def __init__(self, obj):
        self._obj = obj

    def set_progress(self, frac):
        self._obj.opacity = round(255 * frac)


class WhiteFade:
    """Fade by holding the object fully opaque and lerping its .color from white
    to its assigned color (captured at construction): the object blooms its
    color out of a white board rather than ghosting in.

    Used only for the hex inner fill, which must stay opaque to mask the black
    hex outer -- otherwise the outer bleeds through a translucent inner as a gray
    cell interior mid-fade. This is the one spot that assumes a white board
    background; everything else alpha-fades and adapts to any background."""

    _WHITE = (255, 255, 255)

    def __init__(self, obj):
        self._obj = obj
        self._target = tuple(obj.color)[:3]
        obj.opacity = 255  # opaque for the whole reveal; .color carries the fade

    def set_progress(self, frac):
        w, t = self._WHITE, self._target
        # 3-tuple keeps the alpha set above, so the inner stays opaque.
        self._obj.color = (
            round(w[0] + (t[0] - w[0]) * frac),
            round(w[1] + (t[1] - w[1]) * frac),
            round(w[2] + (t[2] - w[2]) * frac),
        )


class _FadeGroup:
    """One category's fade: the fade handles (AlphaFade / WhiteFade) for its
    cells/glyphs (or grid lines) plus its absolute `delay` and `duration` in
    seconds."""

    def __init__(self, handles, delay, duration):
        self._handles = handles
        self._delay = delay
        self._duration = duration

    def apply(self, clock, easing):
        """Drive every handle's fade for the timeline at `clock` seconds."""
        if self._duration <= 0:
            p = 1.0 if clock >= self._delay else 0.0
        else:
            p = (clock - self._delay) / self._duration
            p = 0.0 if p < 0.0 else (1.0 if p > 1.0 else p)
        frac = easing(p)
        for handle in self._handles:
            handle.set_progress(frac)


class LoadingAnimation:
    """Drives the opening reveal (the LOADING phase): fades each category's
    cells/glyphs -- and the grid lines -- up from transparent on an absolute
    timeline read from loading_animation.yaml.

    Construct with a {category_name: [handles]} map; each handle is an AlphaFade
    or WhiteFade wrapping one render object. Every category name must have a
    {delay, duration} slot in loading_animation.yaml. The map need only list the
    categories the active fade scheme actually produced this game (see
    game_screen.loading_fade_glyphs_category) -- categories NOT in the map don't run and
    don't count toward the timeline, so swapping schemes (by length / strength /
    *fix) doesn't drag in the other schemes' slots as dead air. A listed category
    with an empty handle list still reserves its slot. Tick with update(dt);
    `done` flips true once the last present fade completes, the game screen's cue
    to start play (spawn the live piece / start the mode timer)."""

    def __init__(self, handles_by_category):
        self._easing = _select_fade_easing()
        self._clock = 0.0
        self._groups = []
        # Timeline length is the latest finish among the categories PRESENT this
        # game (each category's delay+duration), so an unused scheme's slots in the
        # yaml don't extend the reveal. A present-but-empty category still counts.
        self._total = 0.0
        for name, handles in handles_by_category.items():
            timing = get_loading_anim("categories." + name)
            self._groups.append(
                _FadeGroup(handles, timing["delay"], timing["duration"])
            )
            self._total = max(self._total, timing["delay"] + timing["duration"])
        # Start fully blank: the first drawn frame shows only the board
        # background and the loading pane.
        self._apply()

    @property
    def done(self):
        return self._clock >= self._total

    def update(self, dt):
        if self.done:
            return
        self._clock += dt
        self._apply()

    def _apply(self):
        for group in self._groups:
            group.apply(self._clock, self._easing)
