import importlib.util
from pathlib import Path


def _load_trainer_module():
    root = Path(__file__).resolve().parents[1]
    script = root / "tools" / "train_recall_model_sklearn.py"
    spec = importlib.util.spec_from_file_location("train_recall_model_sklearn_testmod", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_c_grid_filters_and_sorts():
    trainer = _load_trainer_module()
    vals = trainer._parse_c_grid("2, 1, foo, -1, 2, 0.5", fallback_c=1.0)
    assert vals == [0.5, 1.0, 2.0]


def test_expected_calibration_error_perfect_is_zero():
    trainer = _load_trainer_module()
    y_true = [0, 1, 0, 1]
    probs = [0.0, 1.0, 0.0, 1.0]
    ece = trainer._expected_calibration_error(y_true, probs, bins=10)
    assert ece == 0.0


def test_resolve_calibration_mode_auto():
    trainer = _load_trainer_module()
    assert trainer._resolve_calibration_mode("auto", 50) == "sigmoid"
    assert trainer._resolve_calibration_mode("auto", 600) == "isotonic"
    assert trainer._resolve_calibration_mode("none", 600) == "none"
