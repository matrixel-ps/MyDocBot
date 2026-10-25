"""Atomic, owner-only writes for MyDocBot's data files (A6).

open(path, 'w') empties a file before writing it, so a reader in between (the
CLI and a TUI at once, or a TUI worker and its UI thread) saw an empty file.
The loaders treat that as "start fresh" and then saved over the real data.
Here the new content goes to a temp file in the same directory, which is
fsync'ed and then os.replace()'d over the target: a reader sees the old file
or the new one, never a partial one. locked() serialises read-modify-write
across processes and threads, so two writers can't lose each other's update.
"""
import contextlib
import json
import os
import tempfile
import threading
from datetime import datetime

try:
    import fcntl
except ImportError:  # not POSIX: locked() falls back to in-process locking only
    fcntl = None  # type: ignore[assignment]


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


def _stamp():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def quarantine(path):
    """Move an unparseable data file to <path>.corrupt-YYYYMMDD-HHMMSS (owner-only)
    and return the new path (B11). Moving rather than copying means later loads
    in the session see no file (no repeat warning) and the next save starts
    clean; the timestamp (plus -N if needed) means no backup is ever overwritten."""
    base = f"{path}.corrupt-{_stamp()}"
    target, n = base, 1
    while os.path.exists(target):
        target, n = f"{base}-{n}", n + 1
    os.replace(path, target)
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass  # best-effort on platforms without POSIX permission support
    return target


# One reentrant thread lock per data file, plus how deep the owning thread is
# in it. The depth is only touched while holding that lock.
_thread_locks: dict[str, threading.RLock] = {}
_depths: dict[str, int] = {}
_registry = threading.Lock()


def _thread_lock(key):
    with _registry:
        return _thread_locks.setdefault(key, threading.RLock())


def _open_lock_file(path):
    """fd of <path>.lock (created 0600, never deleted: deleting a lock file lets
    two processes lock different files), or None if its directory is missing."""
    try:
        return os.open(f"{path}.lock", os.O_RDWR | os.O_CREAT, 0o600)
    except FileNotFoundError:
        return None


@contextlib.contextmanager
def locked(path, blocking=True):
    """Hold the lock for one data file across a load-modify-save (A6).

    An advisory flock on <path>.lock keeps out other processes (the CLI, a TUI,
    the Discord bot); a reentrant thread lock keeps out this process's other
    threads, and lets a function that holds the lock call another that takes
    it. flock is per open file, so only the outermost level takes it.
    Yields True once held. With blocking=False it yields False instead of
    waiting if someone else holds it. POSIX-only across processes."""
    key = os.path.abspath(path)
    lock = _thread_lock(key)
    if not lock.acquire(blocking=blocking):
        yield False
        return
    fd = None
    busy = False
    try:
        if _depths.get(key, 0) == 0 and fcntl is not None:
            fd = _open_lock_file(key)
            if fd is not None:
                flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
                try:
                    fcntl.flock(fd, flags)
                except BlockingIOError:
                    busy = True
        if busy:
            yield False
        else:
            _depths[key] = _depths.get(key, 0) + 1
            try:
                yield True
            finally:
                _depths[key] -= 1
    finally:
        if fd is not None:
            os.close(fd)  # closing the fd releases the flock
        lock.release()
