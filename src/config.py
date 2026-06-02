import yaml
from pathlib import Path


def load_config():
    config_path = Path(__file__).parent / "assets" / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


CONFIG = load_config()


def select_rule(slot, registry):
    """Resolve the rule name configured for `slot` (e.g. "square_piece.gram_pick")
    to a function in `registry`. The YAML `rules` block is the single edit point;
    `registry` is a {name: function} map declared at each rule's swap point."""
    name = CONFIG["rules"][slot]
    return registry[name]
