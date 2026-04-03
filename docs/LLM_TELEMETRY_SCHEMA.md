# LLM telemetry schema

This repository keeps the golden tutor prompt fixture in `tests/fixtures/golden_tutor_prompts.json`.

Current telemetry/documentation contract:

- Golden prompt fixture changes must remain deterministic and reviewable.
- Prompt-quality regressions should be checked with the existing tutor-quality tooling in `tests/tutor_quality/`.
- Any future telemetry fields should be documented here alongside the fixture usage.
