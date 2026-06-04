import yaml
from pathlib import Path


def load_config():
    config_path = Path(__file__).parent / "assets" / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


CONFIG = load_config()


def load_colors():
    colors_path = Path(__file__).parent / "assets" / "colors.yaml"
    with open(colors_path) as f:
        return yaml.safe_load(f)


COLORS = load_colors()


def select_rule(slot, registry):
    """Resolve the rule name configured for `slot` (e.g. "square_piece.gram_pick")
    to a function in `registry`. The YAML `rules` block is the single edit point;
    `registry` is a {name: function} map declared at each rule's swap point."""
    name = CONFIG["rules"][slot]
    return registry[name]


def get_color(path):
    """Resolve a dotted color name (e.g. "board.cell_fill") from colors.yaml to
    an (r, g, b) or (r, g, b, a) tuple. colors.yaml is the single edit point for
    styling; channels are 0-255."""
    node = COLORS
    for key in path.split("."):
        node = node[key]
    return tuple(node)
