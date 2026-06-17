import json
import os
import sys

from core.validation import validate_config

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, 'docs_config.json')


def load_config():
    if not os.path.exists(CONFIG_PATH):
        config = {"default": "log", "aliases": {}}
        save_config(config)
        return config
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        valid, msg = validate_config(cfg)
        if not valid:
            print(f"Warning: Invalid config schema — {msg}. Starting fresh.", file=sys.stderr)
            cfg = {"default": "", "aliases": {}}
            save_config(cfg)
        return cfg
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: Corrupt config at {CONFIG_PATH} — {e}. Starting fresh.", file=sys.stderr)
        config = {"default": "", "aliases": {}}
        save_config(config)
        return config


def save_config(config):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)
        f.write('\n')


def resolve_alias(config, alias):
    aliases = config.get("aliases", {})
    if alias in aliases:
        return aliases[alias]
    return None
