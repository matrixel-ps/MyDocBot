"""File locking for read-modify-write (A6): two processes or threads updating
the queue or tag index at once must not lose each other's changes, and only
one flush runs at a time."""
import fcntl
import os
import stat
import subprocess
import sys
import threading
from contextlib import contextmanager

import core.parser as prs
from core import storage

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@contextmanager
def held_by_other_process(path):
    """Hold <path>.lock on a separate open file, as another process would.
    flock is per open file, so this process's locked() sees it as taken."""
    fd = os.open(f"{path}.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


class TestLocked:
    def test_creates_owner_only_lock_file_next_to_data_file(self, tmp_path):
        path = str(tmp_path / "x.json")
        with storage.locked(path) as held:
            assert held
        assert stat.S_IMODE(os.stat(f"{path}.lock").st_mode) == 0o600
        assert not os.path.exists(path)  # locking never creates the data file

    def test_reentrant_in_the_same_thread(self, tmp_path):
        path = str(tmp_path / "x.json")
        with storage.locked(path) as outer:
            with storage.locked(path) as inner:
                assert outer and inner
        # Fully released: another "process" can take it now.
        with held_by_other_process(path):
            pass

    def test_non_blocking_reports_busy_when_another_process_holds_it(self, tmp_path):
        path = str(tmp_path / "x.json")
        with held_by_other_process(path):
            with storage.locked(path, blocking=False) as held:
                assert held is False
        with storage.locked(path, blocking=False) as held:
            assert held is True

    def test_non_blocking_reports_busy_when_another_thread_holds_it(self, tmp_path):
        path = str(tmp_path / "x.json")
        inside, release = threading.Event(), threading.Event()

        def holder():
            with storage.locked(path):
                inside.set()
                release.wait(5)

        t = threading.Thread(target=holder)
        t.start()
        try:
            assert inside.wait(5)
            with storage.locked(path, blocking=False) as held:
                assert held is False
        finally:
            release.set()
            t.join(5)

    def test_missing_directory_still_locks_within_the_process(self, tmp_path):
        path = str(tmp_path / "missing" / "x.json")
        with storage.locked(path) as held:
            assert held
        assert not os.path.exists(tmp_path / "missing")


# Each child process appends PER_PROCESS notes to the same queue file.
_CHILD = """
import sys
import core.parser as prs
prs.PENDING_PATH = sys.argv[1]
for i in range(int(sys.argv[3])):
    prs.queue_note(f"{sys.argv[2]}-{i}", "doc_1", "t")
"""


class TestConcurrentUpdates:
    def test_processes_queueing_at_once_lose_nothing(self, tmp_path):
        path = str(tmp_path / "pending_queue.json")
        per_process, processes = 40, 4
        env = {**os.environ, "MYDOCBOT_HOME": str(tmp_path / "home")}
        children = [
            subprocess.Popen([sys.executable, "-c", _CHILD, path, f"p{n}", str(per_process)],
                             cwd=REPO_ROOT, env=env)
            for n in range(processes)
        ]
        assert [c.wait(60) for c in children] == [0] * processes
        prs.PENDING_PATH = path  # the autouse fixture restores it afterwards
        texts = [e["text"] for e in prs.load_pending_notes()]
        assert len(texts) == per_process * processes
        assert set(texts) == {f"p{n}-{i}" for n in range(processes) for i in range(per_process)}

    def test_threads_indexing_at_once_lose_nothing(self, tmp_tags_index_path):
        def worker(n):
            for i in range(25):
                prs.index_note(f"#t{n} note {i}", f"ts{i}", "doc_1", "p")

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        index = prs.load_tags_index()
        assert sorted(index) == ["t0", "t1", "t2", "t3"]
        assert all(len(entries) == 25 for entries in index.values())


class TestFlushUnderConcurrency:
    def test_note_queued_during_a_flush_is_kept(self, tmp_pending_path, tmp_tags_index_path):
        from conftest import RecordingService

        class QueueingService(RecordingService):
            """Another process queues a note while this one is talking to Google."""
            def execute(self):
                if self._pending is not None and not self.calls:
                    prs.queue_note("arrived mid-flush", "doc_1", "t9")
                return super().execute()

        prs.queue_note("first", "doc_1", "t1")
        sent = prs.flush_pending_notes(QueueingService())
        assert [e["text"] for e in sent] == ["first"]
        assert [e["text"] for e in prs.load_pending_notes()] == ["arrived mid-flush"]

    def test_second_flush_is_skipped_while_one_is_running(self, tmp_pending_path, tmp_tags_index_path):
        from conftest import RecordingService
        prs.queue_note("first", "doc_1", "t1")
        service = RecordingService()
        with held_by_other_process(tmp_pending_path + '.flush'):
            assert prs.flush_pending_notes(service) == []
        assert service.calls == []  # nothing sent twice
        assert prs.count_pending() == 1

    def test_failure_error_not_written_onto_a_note_moved_meanwhile(
            self, tmp_pending_path, tmp_tags_index_path, monkeypatch):
        from conftest import RecordingService
        monkeypatch.setattr('core.google_docs.time.sleep', lambda s: None)

        class MovingService(RecordingService):
            """/queue move runs elsewhere while this flush's write is failing."""
            def execute(self):
                if self._pending is not None and self._pending[0] == "doc_a":
                    prs.move_pending(1, "doc_b")
                return super().execute()

        prs.queue_note("a1", "doc_a", "t1")
        assert prs.flush_pending_notes(MovingService(failing={"doc_a"})) == []
        [entry] = prs.load_pending_notes()
        assert entry["doc_id"] == "doc_b"
        assert "error" not in entry  # the move cleared it; the stale failure isn't put back
