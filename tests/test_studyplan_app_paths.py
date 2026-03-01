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
