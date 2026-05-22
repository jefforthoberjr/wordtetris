import json
from pathlib import Path


def load_config():
    config_path = Path(__file__).parent / "assets" / "config.json"
    with open(config_path) as f:
        return json.load(f)


CONFIG = load_config()
