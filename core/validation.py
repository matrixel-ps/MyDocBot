import re

MAX_NOTE_LENGTH = 50 * 1024
MIN_HISTORY_SIZE = 1
MAX_HISTORY_SIZE = 500


def validate_doc_id(doc_id):
    if not doc_id or not doc_id.strip():
        return False, "Doc ID cannot be empty"
    if not re.match(r'^[a-zA-Z0-9_-]+$', doc_id):
        return False, "Doc ID must contain only letters, numbers, underscores, and hyphens"
    if len(doc_id) < 10:
        return False, "Doc ID seems too short (must be at least 10 characters)"
    return True, None


def validate_config(config):
    if not isinstance(config, dict):
        return False, "Config must be a dictionary"
    if "aliases" not in config or not isinstance(config["aliases"], dict):
        return False, "Config must contain an 'aliases' dictionary"
    if "default" not in config:
        return False, "Config must contain a 'default' key"
    return True, None


def validate_note(text):
    if not text or not text.strip():
        return False, "Note cannot be empty"
    if len(text) > MAX_NOTE_LENGTH:
        return False, f"Note exceeds maximum length of {MAX_NOTE_LENGTH // 1024}KB"
    return True, None


def validate_history_size(value):
    """Validate the history_size config value. Accepts int or string representation."""
    try:
        n = int(value)
    except (ValueError, TypeError):
        return False, "history_size must be an integer"
    if n < MIN_HISTORY_SIZE or n > MAX_HISTORY_SIZE:
        return False, f"history_size must be between {MIN_HISTORY_SIZE} and {MAX_HISTORY_SIZE}"
    return True, None
