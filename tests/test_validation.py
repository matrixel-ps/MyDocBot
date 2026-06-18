from core import validation


class TestValidateDocId:
    def test_valid(self):
        valid, msg = validation.validate_doc_id("abc123def456ghi789")
        assert valid
        assert msg is None

    def test_empty(self):
        valid, msg = validation.validate_doc_id("")
        assert not valid
        assert "empty" in msg

    def test_too_short(self):
        valid, msg = validation.validate_doc_id("short")
        assert not valid
        assert "too short" in msg

    def test_special_chars(self):
        valid, msg = validation.validate_doc_id("doc_id!@#$")
        assert not valid
        assert "letters, numbers" in msg

    def test_underscore_and_hyphen_allowed(self):
        valid, msg = validation.validate_doc_id("my_doc-id_12345")
        assert valid
        assert msg is None


class TestValidateConfig:
    def test_valid_config(self):
        valid, msg = validation.validate_config({
            "default": "log",
            "aliases": {"log": "doc_id_123"}
        })
        assert valid
        assert msg is None

    def test_not_dict(self):
        valid, msg = validation.validate_config("not a dict")
        assert not valid
        assert "dictionary" in msg

    def test_missing_aliases(self):
        valid, msg = validation.validate_config({"default": "log"})
        assert not valid
        assert "aliases" in msg

    def test_missing_default(self):
        valid, msg = validation.validate_config({"aliases": {}})
        assert not valid
        assert "default" in msg


class TestValidateNote:
    def test_valid(self):
        valid, msg = validation.validate_note("Meeting notes")
        assert valid
        assert msg is None

    def test_empty(self):
        valid, msg = validation.validate_note("")
        assert not valid
        assert "empty" in msg

    def test_whitespace_only(self):
        valid, msg = validation.validate_note("   ")
        assert not valid

    def test_too_long(self):
        long_text = "x" * (50 * 1024 + 1)
        valid, msg = validation.validate_note(long_text)
        assert not valid
        assert "exceeds" in msg


class TestValidateHistorySize:
    def test_valid_midrange(self):
        valid, msg = validation.validate_history_size("50")
        assert valid
        assert msg is None

    def test_minimum_boundary(self):
        valid, msg = validation.validate_history_size(1)
        assert valid

    def test_maximum_boundary(self):
        valid, msg = validation.validate_history_size(500)
        assert valid

    def test_too_low(self):
        valid, msg = validation.validate_history_size("0")
        assert not valid
        assert "between" in msg

    def test_too_high(self):
        valid, msg = validation.validate_history_size("501")
        assert not valid
        assert "between" in msg

    def test_non_integer_string(self):
        valid, msg = validation.validate_history_size("abc")
        assert not valid
        assert "integer" in msg

    def test_none_value(self):
        valid, msg = validation.validate_history_size(None)
        assert not valid
        assert "integer" in msg
