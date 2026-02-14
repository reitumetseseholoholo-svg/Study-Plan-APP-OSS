import os

import pytest

from studyplan_file_safety import enforce_file_size_limit, secure_path_permissions


def test_enforce_file_size_limit_rejects_missing_file_app_style(tmp_path):
    missing = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError, match=r"Import file not found\.$"):
        enforce_file_size_limit(
            str(missing),
            1024,
            "Import",
            human_readable=True,
            punctuate_simple_errors=True,
        )


def test_enforce_file_size_limit_rejects_directory_engine_style(tmp_path):
    with pytest.raises(ValueError, match=r"Snapshot path is not a regular file$"):
        enforce_file_size_limit(
            str(tmp_path),
            1024,
            "Snapshot",
            human_readable=False,
            punctuate_simple_errors=False,
        )


def test_enforce_file_size_limit_human_readable_size_message(tmp_path):
    path = tmp_path / "oversized.txt"
    path.write_text("x" * 2048, encoding="utf-8")
    with pytest.raises(ValueError, match=r"Maximum allowed is 0\.0MB\."):
        enforce_file_size_limit(
            str(path),
            1024,
            "PDF",
            human_readable=True,
            punctuate_simple_errors=True,
        )


def test_secure_path_permissions_swallow_os_errors(monkeypatch):
    def _raise(*_args, **_kwargs):
        raise OSError("deny")

    monkeypatch.setattr(os, "chmod", _raise)
    secure_path_permissions("/tmp/noop", 0o600)
