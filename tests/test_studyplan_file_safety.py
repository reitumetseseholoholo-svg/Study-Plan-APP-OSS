import os

import pytest

from studyplan_file_safety import (
    enforce_file_size_limit,
    secure_path_permissions,
    validate_path_under,
)


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


def test_validate_path_under_accepts_under_base(tmp_path):
    base = str(tmp_path)
    child = tmp_path / "sub" / "file.txt"
    child.parent.mkdir(parents=True, exist_ok=True)
    child.write_text("ok", encoding="utf-8")
    resolved = validate_path_under(base, str(child), must_be_file=True, must_exist=True)
    assert os.path.isfile(resolved)
    assert resolved.startswith(os.path.realpath(base))


def test_validate_path_under_rejects_outside_base(tmp_path):
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="not under"):
        validate_path_under(str(base_dir), str(outside), must_be_file=True, must_exist=True)


def test_validate_path_under_empty_path_raises():
    with pytest.raises(ValueError, match="empty"):
        validate_path_under("/tmp", "  ", must_exist=False)


def test_validate_path_under_must_be_file_rejects_dir(tmp_path):
    base = str(tmp_path)
    sub = tmp_path / "subdir"
    sub.mkdir(exist_ok=True)
    with pytest.raises(ValueError, match="not a regular file"):
        validate_path_under(base, str(sub), must_be_file=True, must_exist=True)


def test_secure_path_permissions_swallow_os_errors(monkeypatch):
    def _raise(*_args, **_kwargs):
        raise OSError("deny")

    monkeypatch.setattr(os, "chmod", _raise)
    secure_path_permissions("/tmp/noop", 0o600)
