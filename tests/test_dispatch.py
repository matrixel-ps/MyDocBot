from unittest.mock import MagicMock, patch


class TestDispatchRemove:
    @staticmethod
    def _fake_removal(svc_config, args, current_alias):
        svc_config["aliases"].pop(args[0], None)
        if svc_config.get("default") == args[0]:
            svc_config["default"] = next(iter(svc_config["aliases"])) if svc_config["aliases"] else ""
        return True

    def test_remove_current_triggers_switch_to_default(self):
        with patch('main.cmd_remove', side_effect=self._fake_removal):
            with patch('main.google_docs.fetch_doc_title', return_value="Default Doc"):
                from main import dispatch
                config = {
                    "default": "other",
                    "aliases": {"current_doc": "id_current", "other": "id_other"}
                }
                new_alias, new_doc_id = dispatch(
                    MagicMock(), config, "/remove current_doc", "current_doc", "id_current"
                )
                assert new_alias == "other"
                assert new_doc_id == "id_other"

    def test_remove_current_triggers_switch_to_first_remaining(self):
        with patch('main.cmd_remove', side_effect=self._fake_removal):
            with patch('main.google_docs.fetch_doc_title', return_value="First Doc"):
                from main import dispatch
                config = {
                    "default": "removed_alias",
                    "aliases": {"removed_alias": "id_removed", "first_remaining": "id_first"}
                }
                new_alias, new_doc_id = dispatch(
                    MagicMock(), config, "/remove removed_alias", "removed_alias", "id_removed"
                )
                assert new_alias == "first_remaining"
                assert new_doc_id == "id_first"

    def test_remove_current_returns_none_none_when_no_docs_left(self):
        with patch('main.cmd_remove', side_effect=self._fake_removal):
            from main import dispatch
            config = {"default": "last", "aliases": {"last": "id_last"}}
            new_alias, new_doc_id = dispatch(
                MagicMock(), config, "/remove last", "last", "id_last"
            )
            assert new_alias is None
            assert new_doc_id is None

    def test_remove_non_current_returns_unchanged(self):
        with patch('main.cmd_remove', side_effect=self._fake_removal):
            from main import dispatch
            config = {"default": "current", "aliases": {"current": "id_current", "other": "id_other"}}
            new_alias, new_doc_id = dispatch(
                MagicMock(), config, "/remove other", "current", "id_current"
            )
            assert new_alias == "current"
            assert new_doc_id == "id_current"

    def test_remove_failure_returns_unchanged(self):
        with patch('main.cmd_remove', return_value=False):
            from main import dispatch
            config = {"default": "current", "aliases": {"current": "id_current", "other": "id_other"}}
            new_alias, new_doc_id = dispatch(
                MagicMock(), config, "/remove other", "current", "id_current"
            )
            assert new_alias == "current"
            assert new_doc_id == "id_current"

    def test_remove_current_but_failure_returns_unchanged(self):
        with patch('main.cmd_remove', return_value=False):
            from main import dispatch
            config = {"default": "current", "aliases": {"current": "id_current"}}
            new_alias, new_doc_id = dispatch(
                MagicMock(), config, "/remove current", "current", "id_current"
            )
            assert new_alias == "current"
            assert new_doc_id == "id_current"
