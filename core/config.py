import json
import os
import sys

from core.paths import data_path
from core.validation import DEFAULT_HISTORY_SIZE, validate_config

CONFIG_PATH = data_path('docs_config.json')
READ_CONFIG_PATH = data_path('read_config.json')


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


def _chmod_owner_only(path):
    """Best-effort restrict a config file to owner read/write (0600)."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # platforms without POSIX permission support (e.g. some Windows setups)


def save_config(config):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)
        f.write('\n')
    _chmod_owner_only(CONFIG_PATH)


def resolve_alias(config, alias):
    aliases = config.get("aliases", {})
    if alias in aliases:
        return aliases[alias]
    return None


def get_history_size(config):
    """Return the configured history_size, defaulting to DEFAULT_HISTORY_SIZE."""
    try:
        return int(config.get("history_size", DEFAULT_HISTORY_SIZE))
    except (ValueError, TypeError):
        return DEFAULT_HISTORY_SIZE


def load_read_config():
    if not os.path.exists(READ_CONFIG_PATH):
        cfg = {"default": "", "aliases": {}}
        save_read_config(cfg)
        return cfg
    try:
        with open(READ_CONFIG_PATH) as f:
            cfg = json.load(f)
        valid, msg = validate_config(cfg)
        if not valid:
            print(f"Warning: Invalid read config schema — {msg}. Starting fresh.", file=sys.stderr)
            cfg = {"default": "", "aliases": {}}
            save_read_config(cfg)
        return cfg
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: Corrupt read config at {READ_CONFIG_PATH} — {e}. Starting fresh.", file=sys.stderr)
        cfg = {"default": "", "aliases": {}}
        save_read_config(cfg)
        return cfg


def save_read_config(config):
    with open(READ_CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)
        f.write('\n')
    _chmod_owner_only(READ_CONFIG_PATH)


def resolve_read_alias(config, alias):
    aliases = config.get("aliases", {})
    return aliases.get(alias)
