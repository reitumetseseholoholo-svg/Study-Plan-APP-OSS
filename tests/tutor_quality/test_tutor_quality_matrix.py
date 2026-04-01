from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
MATRIX_PATH = HERE / "matrix_v1.json"

REQUIRED_MODULES = {"acca_f9", "acca_f7", "acca_f8", "acca_f6"}
REQUIRED_ACTION_TYPES = {"explain", "apply", "exam_technique", "drill"}


def _load_matrix() -> dict:
    with MATRIX_PATH.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    assert isinstance(payload, dict), "matrix must be a JSON object"
    return payload


def test_matrix_file_exists() -> None:
    assert MATRIX_PATH.exists(), f"missing matrix file: {MATRIX_PATH}"


def test_matrix_top_level_contract() -> None:
    data = _load_matrix()
    for key in ("version", "slice", "created_on", "description", "modules", "action_types", "cases"):
        assert key in data, f"missing key: {key}"
    assert isinstance(data["version"], str) and data["version"].strip()
    assert isinstance(data["slice"], str) and data["slice"].strip()
    assert isinstance(data["created_on"], str) and data["created_on"].strip()
    assert isinstance(data["description"], str) and data["description"].strip()
    assert isinstance(data["modules"], list) and data["modules"]
    assert isinstance(data["action_types"], list) and data["action_types"]
    assert isinstance(data["cases"], list) and data["cases"]


def test_matrix_case_shape_and_ids() -> None:
    data = _load_matrix()
    ids: set[str] = set()
    for row in data["cases"]:
        assert isinstance(row, dict), "case row must be object"
        for key in ("id", "module_id", "chapter", "action_type", "prompt", "expected"):
            assert key in row, f"missing case key: {key}"
        rid = str(row["id"]).strip()
        assert rid, "case id must be non-empty"
        assert rid not in ids, f"duplicate case id: {rid}"
        ids.add(rid)

        module_id = str(row["module_id"]).strip()
        action_type = str(row["action_type"]).strip()
        chapter = str(row["chapter"]).strip()
        prompt = str(row["prompt"]).strip()
        expected = row["expected"]

        assert module_id in REQUIRED_MODULES, f"unsupported module_id: {module_id}"
        assert action_type in REQUIRED_ACTION_TYPES, f"unsupported action_type: {action_type}"
        assert chapter, f"empty chapter for case {rid}"
        assert len(prompt) >= 20, f"prompt too short for case {rid}"
        assert isinstance(expected, dict), f"expected must be object for case {rid}"
        assert "must_include" in expected and "disallow" in expected, f"expected keys missing for case {rid}"
        assert isinstance(expected["must_include"], list) and expected["must_include"], f"must_include empty for case {rid}"
        assert isinstance(expected["disallow"], list) and expected["disallow"], f"disallow empty for case {rid}"


def test_matrix_module_and_action_coverage() -> None:
    data = _load_matrix()
    listed_modules = {str(x).strip() for x in data["modules"]}
    listed_action_types = {str(x).strip() for x in data["action_types"]}
    assert listed_modules == REQUIRED_MODULES
    assert listed_action_types == REQUIRED_ACTION_TYPES

    seen_modules: set[str] = set()
    seen_action_types: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    for row in data["cases"]:
        module_id = str(row["module_id"]).strip()
        action_type = str(row["action_type"]).strip()
        seen_modules.add(module_id)
        seen_action_types.add(action_type)
        seen_pairs.add((module_id, action_type))

    assert seen_modules == REQUIRED_MODULES
    assert seen_action_types == REQUIRED_ACTION_TYPES

    required_pairs = {(m, a) for m in REQUIRED_MODULES for a in REQUIRED_ACTION_TYPES}
    assert required_pairs.issubset(seen_pairs), "matrix must include each module x action_type pair"
