import os
import types

import pytest

try:
    from studyplan_app import StudyPlanGUI
except Exception as exc:  # pragma: no cover - environment-dependent import gate
    pytest.skip(f"studyplan_app import unavailable: {exc}", allow_module_level=True)


def _make_dummy():
    dummy = types.SimpleNamespace()
    dummy._normalize_user_file_path = types.MethodType(StudyPlanGUI._normalize_user_file_path, dummy)
    dummy._validate_import_source_path = types.MethodType(StudyPlanGUI._validate_import_source_path, dummy)
    dummy._prepare_export_target_path = types.MethodType(StudyPlanGUI._prepare_export_target_path, dummy)
    dummy._secure_user_path = types.MethodType(StudyPlanGUI._secure_user_path, dummy)
    dummy._atomic_write_bytes_file = types.MethodType(StudyPlanGUI._atomic_write_bytes_file, dummy)
    dummy._atomic_write_text_file = types.MethodType(StudyPlanGUI._atomic_write_text_file, dummy)
    dummy._atomic_write_csv_rows = types.MethodType(StudyPlanGUI._atomic_write_csv_rows, dummy)
    return dummy


def test_validate_import_source_path_accepts_file_with_allowed_extension(tmp_path):
    dummy = _make_dummy()
    src = tmp_path / "questions.json"
    src.write_text("{}", encoding="utf-8")
    got = StudyPlanGUI._validate_import_source_path(dummy, str(src), "Import", (".json", ".csv"))
    assert got == str(src.resolve())


def test_validate_import_source_path_accepts_backup_extension(tmp_path):
    dummy = _make_dummy()
    src = tmp_path / "studyplan_data.20260214-120000.bak"
    src.write_text("{}", encoding="utf-8")
    got = StudyPlanGUI._validate_import_source_path(dummy, str(src), "Snapshot", (".json", ".bak"))
    assert got == str(src.resolve())


def test_validate_import_source_path_rejects_wrong_extension(tmp_path):
    dummy = _make_dummy()
    src = tmp_path / "questions.txt"
    src.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        StudyPlanGUI._validate_import_source_path(dummy, str(src), "Import", (".json", ".csv"))


def test_validate_import_source_path_rejects_directory(tmp_path):
    dummy = _make_dummy()
    with pytest.raises(ValueError):
        StudyPlanGUI._validate_import_source_path(dummy, str(tmp_path), "Import", (".json",))


def test_prepare_export_target_path_appends_default_extension(tmp_path):
    dummy = _make_dummy()
    target = tmp_path / "report"
    got = StudyPlanGUI._prepare_export_target_path(
        dummy,
        str(target),
        "Export",
        default_extension=".csv",
        allowed_extensions=(".csv",),
    )
    assert got.endswith("report.csv")
    assert os.path.dirname(got) == str(tmp_path.resolve())


def test_prepare_export_target_path_rejects_disallowed_extension(tmp_path):
    dummy = _make_dummy()
    target = tmp_path / "report.json"
    with pytest.raises(ValueError):
        StudyPlanGUI._prepare_export_target_path(
            dummy,
            str(target),
            "Export",
            default_extension=".csv",
            allowed_extensions=(".csv",),
        )


def test_prepare_export_target_path_rejects_symlink_target(tmp_path):
    dummy = _make_dummy()
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
        StudyPlanGUI._prepare_export_target_path(
            dummy,
            str(link_file),
            "Export",
            default_extension=".csv",
            allowed_extensions=(".csv",),
        )


def test_atomic_write_text_file_replaces_existing_content(tmp_path):
    dummy = _make_dummy()
    target = tmp_path / "state.txt"
    target.write_text("old", encoding="utf-8")
    StudyPlanGUI._atomic_write_text_file(dummy, str(target), "new-content")
    assert target.read_text(encoding="utf-8") == "new-content"


def test_atomic_write_csv_rows_outputs_expected_csv(tmp_path):
    dummy = _make_dummy()
    target = tmp_path / "rows.csv"
    StudyPlanGUI._atomic_write_csv_rows(dummy, str(target), [["A", "B"], [1, 2]])
    content = target.read_text(encoding="utf-8")
    assert "A,B" in content
    assert "1,2" in content
