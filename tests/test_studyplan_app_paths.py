# pyright: reportArgumentType=false

import os

import pytest

from studyplan_app_path_utils import (
    atomic_write_csv_rows,
    atomic_write_text_file,
    prepare_export_target_path,
    validate_import_source_path,
)


def test_validate_import_source_path_accepts_file_with_allowed_extension(tmp_path):
    src = tmp_path / "questions.json"
    src.write_text("{}", encoding="utf-8")
    got = validate_import_source_path(str(src), "Import", (".json", ".csv"))
    assert got == str(src.resolve())


def test_validate_import_source_path_accepts_backup_extension(tmp_path):
    src = tmp_path / "studyplan_data.20260214-120000.bak"
    src.write_text("{}", encoding="utf-8")
    got = validate_import_source_path(str(src), "Snapshot", (".json", ".bak"))
    assert got == str(src.resolve())


def test_validate_import_source_path_rejects_wrong_extension(tmp_path):
    src = tmp_path / "questions.txt"
    src.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        validate_import_source_path(str(src), "Import", (".json", ".csv"))


def test_validate_import_source_path_rejects_directory(tmp_path):
    with pytest.raises(ValueError):
        validate_import_source_path(str(tmp_path), "Import", (".json",))


def test_validate_import_source_path_rejects_path_outside_permitted_roots(tmp_path):
    """Path traversal: reject paths outside home, /tmp, or /media."""
    allowed = tmp_path / "ok.json"
    allowed.write_text("{}", encoding="utf-8")
    validate_import_source_path(str(allowed), "Import", (".json",))
    if os.name != "posix":
        return
    etc_hosts = "/etc/hosts"
    if os.path.exists(etc_hosts) and os.path.isfile(etc_hosts):
        with pytest.raises(ValueError, match="not allowed|path must be"):
            validate_import_source_path(etc_hosts, "Import", (".json", ".txt"))


def test_prepare_export_target_path_appends_default_extension(tmp_path):
    target = tmp_path / "report"
    got = prepare_export_target_path(
        str(target),
        "Export",
        default_extension=".csv",
        allowed_extensions=(".csv",),
    )
    assert got.endswith("report.csv")
    assert os.path.dirname(got) == str(tmp_path.resolve())


def test_prepare_export_target_path_rejects_disallowed_extension(tmp_path):
    target = tmp_path / "report.json"
    with pytest.raises(ValueError):
        prepare_export_target_path(
            str(target),
            "Export",
            default_extension=".csv",
            allowed_extensions=(".csv",),
        )


def test_prepare_export_target_path_rejects_symlink_target(tmp_path):
    if not hasattr(os, "symlink"):
        pytest.skip("symlink not available on this platform")
    real_file = tmp_path / "real.csv"
    real_file.write_text("ok", encoding="utf-8")
    link_file = tmp_path / "link.csv"
    try:
        os.symlink(real_file, link_file)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not supported in this environment")
    with pytest.raises(ValueError):
        prepare_export_target_path(
            str(link_file),
            "Export",
            default_extension=".csv",
            allowed_extensions=(".csv",),
        )


def test_atomic_write_text_file_replaces_existing_content(tmp_path):
    target = tmp_path / "state.txt"
    target.write_text("old", encoding="utf-8")
    atomic_write_text_file(str(target), "new-content")
    assert target.read_text(encoding="utf-8") == "new-content"


def test_atomic_write_csv_rows_outputs_expected_csv(tmp_path):
    target = tmp_path / "rows.csv"
    atomic_write_csv_rows(str(target), [["A", "B"], [1, 2]])
    content = target.read_text(encoding="utf-8")
    assert "A,B" in content
    assert "1,2" in content


def test_atomic_write_text_file_sets_restrictive_permissions(tmp_path):
    """File must be written with 0o600 permissions (chmod set before rename)."""
    import stat

    target = tmp_path / "secret.txt"
    atomic_write_text_file(str(target), "sensitive", mode=0o600)
    mode = stat.S_IMODE(os.stat(str(target)).st_mode)
    if os.name == "posix":
        # On POSIX the written file must not be world- or group-readable.
        assert mode & 0o077 == 0, f"File has excess permissions: {oct(mode)}"
    else:
        # On non-POSIX platforms os.chmod behaviour is platform-defined;
        # verify only that the file was created successfully.
        assert os.path.isfile(str(target))
