import copy
import yaml
from pathlib import Path


def load_config():
    config_path = Path(__file__).parent / "assets" / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


CONFIG = load_config()

# Game modes: each file in assets/game_modes/ is a PARTIAL config -- a shared base
# config.yaml deep-merged with a per-mode override so only the keys that define the
# mode live in the mode file (see AGENTS.md / the menu "Start" submenu). The mode
# is applied at runtime by mutating CONFIG in place (below) so every
# `from config import CONFIG` holder sees the swap without reimporting.
_GAME_MODES_DIR = Path(__file__).parent / "assets" / "game_modes"

# (slug, label, path) of the mode last applied via apply_game_mode, or None while
# the game runs on the bare base config.yaml (e.g. before any menu pick).
_active_mode = None


def _load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base, override):
    """Return a new dict: `override` deep-merged onto `base`. Nested dicts merge
    key-by-key (so a mode file can override a single `rules:` knob without
    restating the block); every other value -- scalars and lists -- from override
    replaces base wholesale. Neither input is mutated."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def list_game_modes():
    """Scan assets/game_modes/*.yaml -> [(slug, label, path), ...] sorted by label.
    `slug` is the filename stem (also used in the session filename); `label` is the
    file's top-level `mode_label:` (falling back to the slug). Reads only the label
    key here -- the full merge happens in apply_game_mode when a mode is chosen."""
    modes = []
    if not _GAME_MODES_DIR.is_dir():
        return modes
    for path in sorted(_GAME_MODES_DIR.glob("*.yaml")):
        data = _load_yaml(path)
        label = data.get("mode_label") or path.stem
        modes.append((path.stem, label, path))
    modes.sort(key=lambda mode: mode[1].lower())
    return modes


def apply_game_mode(path):
    """Load a FRESH base config.yaml, deep-merge the game-mode override at `path`
    on top, and replace CONFIG's contents in place (clear + update -- the dict
    object is never rebound, so all holders track the swap). Reloading the base
    each call means repeated mode switches always merge onto a clean base, never
    onto an already-merged CONFIG. `mode_label` is menu metadata, not a game knob,
    so it's stripped before the merge. Records + returns (slug, label)."""
    global _active_mode
    path = Path(path)
    override = _load_yaml(path)
    label = override.pop("mode_label", None) or path.stem
    merged = _deep_merge(load_config(), override)
    CONFIG.clear()
    CONFIG.update(merged)
    _active_mode = (path.stem, label, path)
    return path.stem, label


def active_mode():
    """The (slug, label, path) of the last-applied game mode, or None if the game
    is still on the bare base config.yaml. Used by session logging to stamp which
    mode a recorded session was played under."""
    return _active_mode


def load_colors():
    colors_path = Path(__file__).parent / "assets" / "colors.yaml"
    with open(colors_path) as f:
        return yaml.safe_load(f)


COLORS = load_colors()


def load_strings():
    # encoding spelled out so accented translations (ñ, ¡, á ...) load on any OS.
    strings_path = Path(__file__).parent / "assets" / "strings.yaml"
    with open(strings_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


STRINGS = load_strings()


def load_loading_anim():
    loading_path = Path(__file__).parent / "assets" / "loading_animation.yaml"
    with open(loading_path) as f:
        return yaml.safe_load(f)


LOADING_ANIM = load_loading_anim()


def select_rule(slot, registry):
    """Resolve the rule name configured for `slot` (e.g. "square_player.gram_pick")
    to a function in `registry`. The YAML `rules` block is the single edit point;
    `registry` is a {name: function} map declared at each rule's swap point."""
    name = CONFIG["rules"][slot]
    return registry[name]


def get_color(path):
    """Resolve a dotted color name (e.g. "board.settled_cell_fill") from colors.yaml to
    an (r, g, b) or (r, g, b, a) tuple. colors.yaml is the single edit point for
    styling; channels are 0-255."""
    node = COLORS
    for key in path.split("."):
        node = node[key]
    return tuple(node)


def get_loading_anim(path):
    """Resolve a dotted key (e.g. "categories.mission") from loading_animation.yaml.
    Single edit point for the LOADING fade-in timeline."""
    node = LOADING_ANIM
    for key in path.split("."):
        node = node[key]
    return node


def get_string(key, **kwargs):
    """Resolve a UI string `key` from strings.yaml in the active language
    (game.language, default "en"). Missing keys -- or a whole missing language --
    fall back to English, then to the key itself, so a typo or untranslated entry
    is visible rather than crashing. Pass template fields as keyword args, e.g.
    get_string("dictionary_count", count=12)."""
    lang = CONFIG.get("game", {}).get("language", "en")
    table = STRINGS.get(lang) or STRINGS.get("en", {})
    text = table.get(key)
    if text is None:
        text = STRINGS.get("en", {}).get(key, key)
    if kwargs:
        text = text.format(**kwargs)
    return text
