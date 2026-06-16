import os
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, 'docs_config.json')


def load_config():
    if not os.path.exists(CONFIG_PATH):
        config = {"default": "log", "aliases": {}}
        save_config(config)
        return config
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)


def save_config(config):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)
        f.write('\n')


def resolve_alias(config, alias):
    aliases = config.get("aliases", {})
    if alias in aliases:
        return aliases[alias]
    return None
