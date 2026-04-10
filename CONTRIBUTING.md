# Contributing to Study Assistant

Thank you for your interest in contributing! This document covers the development workflow, code style, and PR process.

## Table of Contents

1. [Getting Started](#getting-started)
2. [Project Structure](#project-structure)
3. [Code Style and Standards](#code-style-and-standards)
4. [Running the Test Suite](#running-the-test-suite)
5. [Lint and Type Checking](#lint-and-type-checking)
6. [Smoke Testing](#smoke-testing)
7. [Pull Request Guidelines](#pull-request-guidelines)
8. [Adding or Changing Features](#adding-or-changing-features)
9. [Writing Tests](#writing-tests)
10. [Module JSON Format](#module-json-format)

---

## Getting Started

```bash
# Clone the repo
git clone https://github.com/reitumetseseholoholo-svg/Study-Plan-APP-OSS
cd Study-Plan-APP-OSS

# Install system GTK4 dependencies (Ubuntu/Debian)
sudo apt install python3-gi gir1.2-gtk-4.0 xvfb

# Install Python dependencies
pip install -e .
pip install pyright pytest

# Verify the setup
python -m py_compile studyplan_app.py studyplan_ai_tutor.py studyplan_engine.py
python tools/gtk4_lint.py
pytest -q
```

Python **3.11 or later** is required. The project uses Poetry for dependency management (`pyproject.toml`). `uv` is also supported (`uv.lock` is included).

---

## Project Structure

```
studyplan_app.py          # GTK4 application window — UI entry point
studyplan_engine.py       # Data model, SRS, scheduling, ML, persistence
studyplan_ai_tutor.py     # AI tutor session management, RAG, prompt assembly
studyplan_app_kpi_routing.py  # KPI/smoke routing helpers (GTK-independent)
studyplan_app_path_utils.py   # Path helpers (GTK-independent, unit-testable)
studyplan_ui_runtime.py       # UI state at startup (GTK-independent)
studyplan_file_safety.py      # File size limits, secure path enforcement
studyplan_theme.py            # CSS/GTK4 theming
studyplan_ui_state_store.py   # UI state store

studyplan/                # Pure-Python library (no GTK imports here)
  config.py               # Config class — all settings via env vars
  fsrs.py                 # FSRS-4.5 spaced-repetition scheduler
  contracts.py            # Typed dataclass API contracts
  services.py             # Protocol interfaces
  coach_fsm.py            # Socratic coaching FSM
  mastery_kernel.py       # Bayesian mastery updates
  cognitive_state.py      # Cognitive state and working memory
  ai/                     # LLM routing, prompts, gateway, telemetry
  ui/gtk4/                # Reusable GTK4 panel components
  testing/                # Integration and scenario tests

tests/                    # Unit tests (no GTK required for most)
tools/                    # CLI tools: ML training, quality benchmarks, GTK4 linter
modules/                  # Built-in module JSON configs and question banks
scripts/                  # Helper scripts (remind, update, flashcard export)
```

### Key design rule: keep `studyplan/` GTK-free

Everything under `studyplan/` must be importable without GTK. If new logic does not need the UI, put it there. This keeps the unit-test surface large and the CI fast.

When you add non-GTK logic to `studyplan_app.py`, consider whether it belongs in a new small module under `studyplan/` or one of the existing GTK-independent helper files.

---

## Code Style and Standards

| Requirement | Detail |
|---|---|
| Language | Python 3.11+ |
| Line length | 120 characters (`pyproject.toml [tool.ruff] line-length`) |
| Type hints | Required for all new public functions and class attributes; use `from __future__ import annotations` |
| Imports | stdlib first, then third-party, then local |
| String quotes | Double quotes preferred |
| Comments | Add comments only when they explain *why*, not *what* — match the style of surrounding code |
| Docstrings | Follow existing patterns; one-line summary for simple functions, multi-line for complex ones |

The linter is **ruff** with ruleset `E, F, W, N, C, B` and `E501` (line length) suppressed globally. Run it with:

```bash
python tools/gtk4_lint.py   # GTK4-specific pattern checks (used in CI)
```

Type checking is **pyright** in `basic` mode:

```bash
pyright studyplan_app.py studyplan_ai_tutor.py studyplan_engine.py studyplan tests
```

---

## Running the Test Suite

```bash
# Default suite (no GTK needed — ~388 tests)
pytest -q

# Full suite (requires system GTK4 + PyGObject — ~545 tests)
pip install -e ".[test-full]"
pytest -q
```

Tests live in two directories (both discovered by pytest):
- `tests/` — unit and integration tests
- `studyplan/testing/` — scenario and service tests

### Protected no-regression flows

The following test files protect critical paths and **must pass** on every PR:

| Test file | Guards |
|---|---|
| `tests/test_studyplan_engine.py` | Core engine logic |
| `tests/test_studyplan_app_paths.py`, `tests/test_studyplan_file_safety.py` | Module loading and path safety |
| `tests/test_cognitive_runtime.py`, `studyplan/testing/test_persistence.py`, `studyplan/testing/test_schema_migration.py` | Cognitive/runtime state, persistence, schema migration |
| `tests/test_model_routing.py`, `tests/test_tutor_prompt_layers.py`, `tests/test_golden_tutor_prompts.py`, `tests/tutor_quality/` | Tutor prompt and routing |
| `tests/test_smoke_kpi.py`, `tests/test_soak_kpi.py` | KPI and smoke routing helpers |
| `tests/test_action_registry.py`, `tests/test_studyplan_ui_runtime.py` | GTK-independent action/runtime seams |
| `studyplan/testing/test_secure_importer.py`, `studyplan/testing/test_module_reconfig.py`, `tests/test_rag_and_reconfig_safety.py` | Secure import and module reconfig |
| `tests/test_fsrs.py` | FSRS-4.5 scheduler |

---

## Lint and Type Checking

The CI runs these in order:

```bash
# 1. GTK4 lint
python tools/gtk4_lint.py

# 2. Pyright type check
pyright studyplan_app.py studyplan_ai_tutor.py studyplan_engine.py studyplan tests

# 3. Unit tests
pytest -q

# 4. Strict dialog smoke (requires Xvfb)
xvfb-run -a timeout 180s python studyplan_app.py --dialog-smoke-strict
```

All four must pass before a PR can merge to `main`.

---

## Smoke Testing

The smoke test launches the real GTK4 app in headless mode and validates KPI thresholds:

```bash
# Exploratory (does not fail on KPI issues)
xvfb-run -a timeout 40s python studyplan_app.py --dialog-smoke-test

# Strict gate (exits non-zero on KPI/report failure — used in CI)
xvfb-run -a timeout 40s python studyplan_app.py --dialog-smoke-strict
```

To avoid touching your real config during smoke runs:

```bash
STUDYPLAN_CONFIG_HOME=$(mktemp -d) xvfb-run -a timeout 40s \
  python studyplan_app.py --dialog-smoke-strict
```

### KPI thresholds

| KPI | Threshold |
|---|---|
| `coach_pick_consistency_rate` | ≥ 0.999 |
| `coach_only_toggle_integrity_rate` | == 1.0 |
| `coach_next_burst_integrity_rate` | == 1.0 |

---

## Pull Request Guidelines

1. **Branch from `main`** — use descriptive branch names: `feature/`, `fix/`, `docs/`, `refactor/`
2. **Keep PRs focused** — one feature or bug fix per PR
3. **Write tests** — new behaviour must have tests; bug fixes must have a regression test
4. **Run the full CI check locally** before pushing: lint → pyright → pytest → smoke
5. **Update documentation** — if you change user-facing behaviour, update `README.md` or `USER_GUIDE.md`; if you change internals, update `DEVELOPER_DOC.md`
6. **Golden prompt fixture** — if your change affects prompt output, update `tests/fixtures/golden_tutor_prompts.json` and explain why in the PR description
7. **Do not remove or weaken existing tests** — if a test needs updating because behaviour legitimately changed, explain that change explicitly

### Commit messages

Use the imperative mood and reference the relevant area:

```
engine: add outcome-gap boost to drill selection
tutor: fix context budget overflow for long histories
docs: update USER_GUIDE for Section C practice
ci: raise strict smoke timeout to 180s
```

---

## Adding or Changing Features

### New non-GTK logic

1. Create a new file under `studyplan/` (or extend an existing one)
2. Import it in `studyplan_engine.py` or `studyplan_ai_tutor.py` as appropriate
3. Write unit tests in `tests/` that do **not** require GTK
4. Update `DEVELOPER_DOC.md` if the change affects the architecture

### New GTK UI elements

1. Add the widget in `studyplan_app.py` in the appropriate `_build_*` method
2. Register any new menu action in `studyplan/app/action_registry.py`
3. Add a smoke-mode assertion if the new UI path has a KPI impact
4. Run `python tools/gtk4_lint.py` to catch deprecated GTK4 patterns

### New AI prompt or tutor change

1. Update the relevant file under `studyplan/ai/`
2. Run the tutor quality pipeline to check for regressions:
   ```bash
   python tools/run_tutor_quality_pipeline.py \
     --mode reference \
     --matrix tests/tutor_quality/matrix_v1.json \
     --expected tests/tutor_quality/expected_scores_v1.json \
     --gates-file tests/tutor_quality/gates_v1.json \
     --baseline tests/tutor_quality/reference_report_v1.json \
     --model reference_baseline \
     --policy-file tests/tutor_quality/policy_profiles_v1.json \
     --policy feature_relaxed
   ```
3. If you intentionally change the prompt structure, regenerate the golden fixture:
   `tests/fixtures/golden_tutor_prompts.json`

### New SRS or scheduling logic

1. Extend `studyplan_engine.py` methods; keep FSRS and SM-2 paths separate via `_update_srs_fsrs` / `_update_srs_sm2`
2. Add tests in `tests/test_fsrs.py` or `tests/test_studyplan_engine.py`
3. Check backward compatibility: FSRS and SM-2 SRS items coexist in `data.json`

---

## Writing Tests

### Guidelines

- Prefer pure-Python tests in `tests/` that do not import `studyplan_app`
- Use `pytest` fixtures and parametrize where applicable
- Mock Ollama/LLM calls; never require a live model in CI
- Use `STUDYPLAN_CONFIG_HOME=$(mktemp -d)` for tests that write files, to isolate them from real user data
- Test edge cases: empty data, corrupt JSON, missing fields, zero quiz history

### Test discovery

pytest discovers from `tests/` and `studyplan/testing/`. Test files must match `test_*.py`.

### Example skeleton

```python
import pytest
from studyplan_engine import StudyPlanEngine

@pytest.fixture
def engine(tmp_path):
    e = StudyPlanEngine(module_id="test_mod")
    e.DATA_FILE = str(tmp_path / "data.json")
    e.QUESTIONS_FILE = str(tmp_path / "questions.json")
    return e

def test_daily_plan_returns_chapters(engine):
    plan = engine.get_daily_plan(num_topics=3)
    assert isinstance(plan, list)
    assert all(ch in engine.CHAPTERS for ch in plan)
```

---

## Module JSON Format

Built-in modules live in `modules/`. To add a new module:

1. Create `modules/<your_module_id>.json`
2. Follow the schema documented in `README.md § Module JSON format` and validated by `module_schema.json`
3. Add at least a `title`, `chapters`, `chapter_flow`, and `importance_weights`
4. Add questions under `"questions": { "Chapter Name": [...] }` (optional but recommended)
5. Test by switching to the module in the app: **Module → Switch Module…**
