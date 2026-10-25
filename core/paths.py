import os
import shutil
import sys

# Where every personal data file lives. Resolved once at import, with no side
# effects; prepare_data_dir() creates it (and migrates) at startup.
LEGACY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILES = (
    'docs_config.json', 'read_config.json', 'tags_index.json',
    'pending_queue.json', 'token.json', 'credentials.json',
)


def resolve_data_dir(env=None):
    """$MYDOCBOT_HOME, else $XDG_CONFIG_HOME/mydocbot, else ~/.config/mydocbot."""
    env = os.environ if env is None else env
    if env.get('MYDOCBOT_HOME'):
        return os.path.abspath(os.path.expanduser(env['MYDOCBOT_HOME']))
    base = env.get('XDG_CONFIG_HOME') or os.path.join(os.path.expanduser('~'), '.config')
    return os.path.join(base, 'mydocbot')


DATA_DIR = resolve_data_dir()


def data_path(name):
    return os.path.join(DATA_DIR, name)


def prepare_data_dir(data_dir=None, legacy_dir=None):
    """Create the data dir (0700) and, on its first creation only, copy files from the old location.

    Migration runs only when the directory doesn't exist yet. pending_queue.json
    is deleted whenever the queue empties, so "copy whatever is missing" would
    resurrect a stale repo-root queue and write those notes twice. Originals are
    copied, never moved, so nothing is lost if something goes wrong.
    Returns the list of file names copied.
    """
    data_dir = DATA_DIR if data_dir is None else data_dir
    legacy_dir = LEGACY_DIR if legacy_dir is None else legacy_dir
    if os.path.isdir(data_dir):
        return []
    os.makedirs(data_dir, mode=0o700)
    if os.path.realpath(legacy_dir) == os.path.realpath(data_dir):
        return []
    copied = []
    for name in DATA_FILES:
        src = os.path.join(legacy_dir, name)
        if os.path.isfile(src):
            dst = os.path.join(data_dir, name)
            shutil.copy2(src, dst)
            try:
                os.chmod(dst, 0o600)
            except OSError:
                pass  # best-effort on platforms without POSIX permission support
            copied.append(name)
    if copied:
        print(f"MyDocBot now keeps its data in {data_dir}.\n"
              f"Copied from {legacy_dir}: {', '.join(copied)}.\n"
              "The originals were left in place; delete them once everything works.",
              file=sys.stderr)
    return copied
