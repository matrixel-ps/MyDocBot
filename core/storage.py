"""Atomic, owner-only writes for MyDocBot's data files (A6).

open(path, 'w') empties a file before writing it, so a reader in between (the
CLI and a TUI at once, or a TUI worker and its UI thread) saw an empty file.
The loaders treat that as "start fresh" and then saved over the real data.
Here the new content goes to a temp file in the same directory, which is
fsync'ed and then os.replace()'d over the target: a reader sees the old file
or the new one, never a partial one. Two processes doing read-modify-write
at the same instant can still lose one update; that needs locking (backlog A6).
"""
import json
import os
import tempfile


def write_text(path, text):
    """Atomically replace path with text, mode 0600 (the temp file is created 0600)."""
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=f".{os.path.basename(path)}.", suffix=".tmp")
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def write_json(path, data):
    """Atomically replace path with data as indented JSON plus a trailing newline."""
    # Serialise first, so an unserialisable value fails before any file is touched.
    write_text(path, json.dumps(data, indent=2) + "\n")
