"""
Tests for main.py REPL loop — specifically the note submission paths that were
broken by the parser/arg_parser naming collision bug.

These tests verify that after the fix:
  - parser.count_pending()         is called from core.parser (not argparse)
  - parser.index_note()            is called on successful submit
  - parser.flush_pending_notes()   is called on successful submit
  - parser.queue_note()            is called on failed (offline) submit
  - pending count is shown in the offline message
"""
import sys
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_main_with_inputs(inputs, *, prepend_ok=True, pending=0, flushed=(),
                          monkeypatch=None):
    """
    Drive main() through one full REPL iteration then quit.

    inputs : list[str] — values returned by builtins.input() in sequence.
    Returns the capsys-captured output (caller must capture separately).
    """
    import main  # re-import each time so module-level state is fresh

    mock_service = MagicMock()

    with patch.object(sys, 'argv', ['main.py']):
        with patch('main.config.load_config', return_value={
            "default": "log",
            "aliases": {"log": "doc_id_abc123"}
        }):
            with patch('main.google_docs.get_service', return_value=mock_service):
                with patch('main.google_docs.fetch_doc_title', return_value="My Log"):
                    with patch('main.google_docs.prepend_text', return_value=prepend_ok):
                        with patch('main.parser.count_pending', return_value=pending):
                            with patch('main.parser.index_note') as mock_index:
                                with patch('main.parser.flush_pending_notes', return_value=list(flushed)) as mock_flush:
                                    with patch('main.parser.queue_note') as mock_queue:
                                        with patch('builtins.input', side_effect=inputs):
                                            main.main()
                                            return mock_index, mock_flush, mock_queue


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------

class TestMainParserIsNotArgparse:
    """Confirm that core.parser functions are reachable from main() — i.e.
    the naming collision is fixed and calling them does not raise AttributeError."""

    def test_count_pending_does_not_raise(self):
        """parser.count_pending() in the prompt-building path must not crash."""
        # Inputs: one note line, blank line to submit, then 'exit'
        inputs = ["my note text", "", "exit"]
        # If the bug were present, this would raise AttributeError inside main().
        # A successful return (no exception) means core.parser was reached.
        _run_main_with_inputs(inputs, prepend_ok=True, pending=0)

    def test_index_note_called_on_success(self):
        """parser.index_note() must be called after a successful prepend."""
        inputs = ["note with #tag", "", "exit"]
        mock_index, _, _ = _run_main_with_inputs(inputs, prepend_ok=True)
        mock_index.assert_called_once()

    def test_flush_pending_called_on_success(self):
        """parser.flush_pending_notes() must be called after a successful prepend."""
        inputs = ["flush test note", "", "exit"]
        _, mock_flush, _ = _run_main_with_inputs(inputs, prepend_ok=True)
        mock_flush.assert_called_once()

    def test_queue_note_called_on_failure(self):
        """parser.queue_note() must be called when prepend_text returns False."""
        inputs = ["offline note", "", "exit"]
        _, _, mock_queue = _run_main_with_inputs(inputs, prepend_ok=False, pending=1)
        mock_queue.assert_called_once()

    def test_queue_note_not_called_on_success(self):
        """parser.queue_note() must NOT be called when prepend succeeds."""
        inputs = ["online note", "", "exit"]
        _, _, mock_queue = _run_main_with_inputs(inputs, prepend_ok=True)
        mock_queue.assert_not_called()


class TestMainSubmitOutput:
    """Verify the status messages printed after note submission."""

    def test_success_message_printed(self, capsys):
        inputs = ["my note", "", "exit"]
        with patch.object(sys, 'argv', ['main.py']):
            with patch('main.config.load_config', return_value={
                "default": "log", "aliases": {"log": "docid_123abc"}
            }):
                with patch('main.google_docs.get_service', return_value=MagicMock()):
                    with patch('main.google_docs.fetch_doc_title', return_value="My Log"):
                        with patch('main.google_docs.prepend_text', return_value=True):
                            with patch('main.parser.count_pending', return_value=0):
                                with patch('main.parser.index_note'):
                                    with patch('main.parser.flush_pending_notes', return_value=[]):
                                        with patch('main.parser.queue_note'):
                                            with patch('builtins.input', side_effect=inputs):
                                                import main
                                                main.main()
        out = capsys.readouterr().out
        assert "Prepended" in out

    def test_offline_message_shows_pending_count(self, capsys):
        inputs = ["offline note", "", "exit"]
        with patch.object(sys, 'argv', ['main.py']):
            with patch('main.config.load_config', return_value={
                "default": "log", "aliases": {"log": "docid_123abc"}
            }):
                with patch('main.google_docs.get_service', return_value=MagicMock()):
                    with patch('main.google_docs.fetch_doc_title', return_value="My Log"):
                        with patch('main.google_docs.prepend_text', return_value=False):
                            with patch('main.parser.count_pending', return_value=3):
                                with patch('main.parser.index_note'):
                                    with patch('main.parser.flush_pending_notes', return_value=[]):
                                        with patch('main.parser.queue_note'):
                                            with patch('builtins.input', side_effect=inputs):
                                                import main
                                                main.main()
        out = capsys.readouterr().out
        assert "Queued" in out
        assert "3 pending" in out

    def test_flushed_count_shown_in_success_message(self, capsys):
        inputs = ["flush note", "", "exit"]
        with patch.object(sys, 'argv', ['main.py']):
            with patch('main.config.load_config', return_value={
                "default": "log", "aliases": {"log": "docid_123abc"}
            }):
                with patch('main.google_docs.get_service', return_value=MagicMock()):
                    with patch('main.google_docs.fetch_doc_title', return_value="My Log"):
                        with patch('main.google_docs.prepend_text', return_value=True):
                            with patch('main.parser.count_pending', return_value=0):
                                with patch('main.parser.index_note'):
                                    with patch('main.parser.flush_pending_notes', return_value=[{}, {}]):
                                        with patch('main.parser.queue_note'):
                                            with patch('builtins.input', side_effect=inputs):
                                                import main
                                                main.main()
        out = capsys.readouterr().out
        assert "flushed 2 pending" in out


class TestMainPromptShowsPending:
    """Confirm pending count appears in the CLI prompt when there are queued notes."""

    def test_pending_tag_in_prompt(self, capsys):
        # We can't capture the prompt string directly, but we can confirm
        # count_pending is called (not crashing) by a clean run.
        inputs = ["exit"]
        with patch.object(sys, 'argv', ['main.py']):
            with patch('main.config.load_config', return_value={
                "default": "log", "aliases": {"log": "docid_123abc"}
            }):
                with patch('main.google_docs.get_service', return_value=MagicMock()):
                    with patch('main.google_docs.fetch_doc_title', return_value="My Log"):
                        with patch('main.parser.count_pending', return_value=5) as mock_pending:
                            with patch('builtins.input', side_effect=inputs):
                                import main
                                main.main()
        mock_pending.assert_called()


class TestMainAddFlag:
    """Verify --add argparse flag validates doc_id (Fix 1)."""

    def _run_add(self, alias, doc_id, *, capsys):
        import main
        with patch.object(sys, 'argv', ['main.py', '--add', alias, doc_id]):
            with patch('main.config.load_config', return_value={
                "default": "", "aliases": {}
            }):
                with patch('main.config.save_config') as mock_save:
                    main.main()
        return mock_save, capsys.readouterr()

    def test_valid_doc_id_is_added(self, capsys):
        mock_save, captured = self._run_add("mynotes", "validDocId123456789", capsys=capsys)
        mock_save.assert_called_once()
        assert "Added alias" in captured.out

    def test_invalid_doc_id_rejected(self, capsys):
        mock_save, captured = self._run_add("bad", "short", capsys=capsys)
        mock_save.assert_not_called()
        assert "Invalid doc_id" in captured.out

    def test_invalid_doc_id_with_special_chars_rejected(self, capsys):
        mock_save, captured = self._run_add("bad", "doc!@#$%^invalid", capsys=capsys)
        mock_save.assert_not_called()
        assert "Invalid doc_id" in captured.out

    def test_duplicate_alias_rejected(self, capsys):
        import main
        with patch.object(sys, 'argv', ['main.py', '--add', 'log', 'validDocId123456789']):
            with patch('main.config.load_config', return_value={
                "default": "log", "aliases": {"log": "existingDocId123456"}
            }):
                with patch('main.config.save_config') as mock_save:
                    main.main()
        out = capsys.readouterr().out
        mock_save.assert_not_called()
        assert "already exists" in out


class TestMainIndexNoteArgs:
    """Verify index_note is called with correct arguments."""

    def test_index_note_receives_text_timestamp_docid(self):
        note_text = "review sprint #standup"
        inputs = [note_text, "", "exit"]
        mock_index, _, _ = _run_main_with_inputs(inputs, prepend_ok=True)
        assert mock_index.call_count == 1
        call_args = mock_index.call_args
        # index_note(full_note, timestamp, doc_id, full_note)
        assert call_args[0][0] == note_text      # text
        assert call_args[0][2] == "doc_id_abc123"  # doc_id
