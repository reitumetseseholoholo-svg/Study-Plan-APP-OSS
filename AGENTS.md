# AGENTS.md

## Cursor Cloud specific instructions

This is a Python GTK4 desktop application (Study Assistant) — a single-process desktop app, not a web service. No external databases or Docker containers are required.

### Services overview

| Service | Required | Notes |
|---------|----------|-------|
| Python 3.11+ | Yes | Runtime |
| GTK4 + PyGObject (`python3-gi`, `gir1.2-gtk-4.0`) | Yes | System packages, not pip |
| Xvfb | Yes (headless) | Needed for GUI/smoke tests; use `xvfb-run -a` |
| pytest / ruff / pyright | Yes (dev) | pip install; see `pyproject.toml` |
| Ollama | No | Optional local LLM; app degrades gracefully |

### Running commands

Standard commands are documented in `README.md` (Tests section) and `DEVELOPER_DOC.md` (Testing section). Key commands:

- **Unit tests**: `pytest -q`
- **Compile check**: `python -m py_compile studyplan_app.py studyplan_engine.py`
- **Type check**: `pyright studyplan_app.py studyplan_ai_tutor.py studyplan_engine.py studyplan tests`
- **GTK4 lint** (used by linux-ci): `python tools/gtk4_lint.py`
- **Smoke test** (strict): `xvfb-run -a timeout 120s python studyplan_app.py --dialog-smoke-strict`
- **Run the app** (headless): `xvfb-run -a python studyplan_app.py`

### Non-obvious caveats

- **`python` must be available**: The system may only have `python3`; create a symlink with `sudo ln -sf /usr/bin/python3 /usr/bin/python` if needed.
- **ruff config issue**: The `pyproject.toml` `[tool.ruff]` section includes `W503` in the `ignore` list, which is not a valid ruff rule. This causes `ruff check` to fail. The `linux-ci.yml` workflow uses `python tools/gtk4_lint.py` instead of ruff.
- **Lock file**: The app enforces single-instance via `~/.config/studyplan/app_instance.lock`. If a prior run was killed ungracefully, remove this file before re-running: `rm -f ~/.config/studyplan/app_instance.lock`.
- **`~/.local/bin` on PATH**: pip installs dev tools to `~/.local/bin`; ensure it's on PATH (`export PATH="$HOME/.local/bin:$PATH"`).
- **Pre-existing test failure**: `test_semantic_tfidf_assets_reused_on_repeated_queries` fails consistently — this is a pre-existing issue, not caused by environment setup.
