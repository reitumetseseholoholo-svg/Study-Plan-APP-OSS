# Tutor Quality Matrix (Slices 1-9)

This folder contains the first executable slice of the Tutor Quality Sprint.

## Scope

- Baseline evaluation matrix for local tutor responses
- Deterministic scorer harness for stable, offline regression checks
- Contract tests that validate matrix shape, coverage, and expected-score fixtures
- Coverage modules: `acca_f9`, `acca_f7`, `acca_f8`, `acca_f6`
- Coverage action types: `explain`, `apply`, `exam_technique`, `drill`

## Files

- `matrix_v1.json`: baseline prompt set with expected response constraints
- `test_tutor_quality_matrix.py`: matrix contract checks
- `quality_scorer.py`: deterministic scoring logic
- `expected_scores_v1.json`: fixed expected scores and summary for regression checks
- `gates_v1.json`: versioned benchmark gate profile for CI/release checks
- `reference_report_v1.json`: pinned reference benchmark output for regression comparison
- `policy_profiles_v1.json`: branch-aware threshold profiles for compare/trend gates
- `test_tutor_quality_scorer.py`: scorer regression tests against expected fixture
- `test_tutor_quality_trends.py`: rolling-window trend gate tests
- `test_tutor_quality_report_validation.py`: artifact schema/invariant validation tests
- `test_tutor_quality_pipeline.py`: end-to-end pipeline orchestration tests

## Run

```bash
pytest tests/tutor_quality -q
```

Reference benchmark (offline deterministic):

```bash
python tools/run_tutor_quality_benchmark.py --mode reference --report tutor_quality_report.json
```

Reference benchmark with versioned gate profile:

```bash
python tools/run_tutor_quality_benchmark.py --mode reference --gates-file tests/tutor_quality/gates_v1.json --report tutor_quality_report.json
```

Ollama benchmark (local model execution + gates):

```bash
python tools/run_tutor_quality_benchmark.py --mode ollama --models "llama3.1:8b" --report tutor_quality_report.json
```

Compare candidate report against a baseline report:

```bash
python tools/compare_tutor_quality_reports.py --baseline tests/tutor_quality/reference_report_v1.json --candidate tutor_quality_report.json --model reference_baseline --report tutor_quality_compare_report.json
```

Analyze quality trends across a rolling report window:

```bash
python tools/analyze_tutor_quality_trends.py --reports "tests/tutor_quality/reference_report_v1.json,tutor_quality_report.json" --model reference_baseline --window-size 2 --report tutor_quality_trend_report.json
```

Run compare/trend with a named policy profile:

```bash
python tools/compare_tutor_quality_reports.py --baseline tests/tutor_quality/reference_report_v1.json --candidate tutor_quality_report.json --model reference_baseline --policy-file tests/tutor_quality/policy_profiles_v1.json --policy balanced_main --report tutor_quality_compare_report.json
python tools/analyze_tutor_quality_trends.py --reports "tests/tutor_quality/reference_report_v1.json,tutor_quality_report.json" --model reference_baseline --policy-file tests/tutor_quality/policy_profiles_v1.json --policy balanced_main --report tutor_quality_trend_report.json
```

Validate benchmark/compare/trend artifact contracts:

```bash
python tools/validate_tutor_quality_reports.py --benchmark tutor_quality_report.json --compare tutor_quality_compare_report.json --trend tutor_quality_trend_report.json --report tutor_quality_validate_report.json
```

Run the full pipeline in one command:

```bash
python tools/run_tutor_quality_pipeline.py --mode reference --baseline-report tests/tutor_quality/reference_report_v1.json --policy-file tests/tutor_quality/policy_profiles_v1.json --policy balanced_main --output-dir .
```

## Case IDs and module prefixes

Matrix `id` values look like `f9_explain_wacc` or `f9_quality_rag_citation`. The **`f9_` / `f7_` / `f8_` / `f6_` prefix matches the module** in `module_id` (`acca_f9`, `acca_f7`, …): **F9 = Financial Management**, **F7 = Financial Reporting**, **F8 = Audit**, **F6 = Tax**. The rest of the slug is a short scenario name. New quality dimensions (e.g. RAG citation style) can add cases under the same module prefix so coverage rules stay satisfied.

## Extension rules

- Keep `id` stable once published.
- Add new cases by appending to `cases` (do not rewrite history in place).
- Preserve module x action coverage.
- Keep prompts module-true and chapter-true.
- Use `expected.must_include` and `expected.disallow` for deterministic checks.
