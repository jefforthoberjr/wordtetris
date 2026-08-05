import yaml
from pathlib import Path
import pyglet


# Loads assets/controls.yaml -- the single edit point for every keyboard/mouse
# binding (see that file's header for the value formats and rule-combo gating).
# Mirrors config.py's load_colors / load_strings; kept in its own module because
# resolving a binding needs pyglet (key/mouse/modifier constants), which the pure
# data loaders in config.py deliberately avoid importing.
def load_controls():
    controls_path = Path(__file__).parent / "assets" / "controls.yaml"
    with open(controls_path) as f:
        return yaml.safe_load(f)


CONTROLS = load_controls()


def _control_node(path):
    """Resolve a dotted controls.yaml path (e.g. "game.move_left") to its raw
    value (a key/button name string, or a list of names)."""
    node = CONTROLS
    for key in path.split("."):
        node = node[key]
    return node


def control_keys(path):
    """Resolve a dotted controls.yaml path to a TUPLE of pyglet key symbols. The
    YAML value may be a single key name ("A") or a list (["ENTER", "RETURN"]); a
    tuple is always returned so callers can test `symbol in control_keys(...)`
    uniformly, whether one key or several are bound to the action."""
    value = _control_node(path)
    if isinstance(value, str):
        names = [value]
    else:
        names = value
    symbols = []
    for name in names:
        symbols.append(getattr(pyglet.window.key, name))
    return tuple(symbols)


def control_names(path, joiner=" / "):
    """The bound key/button NAMES as a display string (e.g. "LEFT", or
    "ENTER / RETURN" for a multi-key action); "--" when the binding is
    unassigned. For showing a control to the player -- the Controls reference
    screen reads every row through this, so a rebinding in controls.yaml shows up
    there without the screen knowing anything about specific keys."""
    value = _control_node(path)
    if isinstance(value, str) or value is None:
        names = [value]
    else:
        names = value
    shown = [n for n in names
             if n is not None and str(n).lower() not in ("none", "null")]
    if not shown:
        return "--"
    return joiner.join(shown)


def control_button(path):
    """Resolve a dotted controls.yaml path to a pyglet mouse-button constant
    (e.g. "LEFT" -> pyglet.window.mouse.LEFT). An UNASSIGNED binding -- the YAML
    value left blank (null) or set to "none" -- returns None, so the action is
    disabled (e.g. freeing RIGHT for another feature). Callers must guard against
    None before comparing a real button to it."""
    name = _control_node(path)
    button = None
    if name is not None and str(name).lower() not in ("none", "null"):
        button = getattr(pyglet.window.mouse, name)
    return button


def control_modifier(path):
    """Resolve a dotted controls.yaml path to a pyglet key modifier bit (e.g.
    "SHIFT" -> pyglet.window.key.MOD_SHIFT), for chord controls like the hex
    down-direction hold."""
    name = _control_node(path)
    return getattr(pyglet.window.key, "MOD_" + name)
