# AGENTS.md

## Cursor Cloud specific instructions

This is a Python GTK4 desktop application (Study Workbench) — a single-process desktop app, not a web service. No external databases or Docker containers are required. It is module-agnostic (load any professional syllabus) and combines SRS, coach, AI tutor, Pomodoro, and semi-autonomous autopilot into a tabbed workbench UI.

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
- **Smoke test** (strict): `xvfb-run -a timeout 300s python studyplan_app.py --dialog-smoke-strict`
- **Run the app** (headless): `xvfb-run -a python studyplan_app.py`

### Troubleshooting: commands fail silently

When any command (smoke test, compile check, etc.) fails:
1. **Always check `cat ~/.config/studyplan/app.log | tail -60` first** — most startup crashes (AttributeError, import failures, GTK errors) are logged here with full traceback.
2. **Check `cat ~/.config/studyplan/smoke_last.json | python -m json.tool`** — smoke test failures include startup_error reason, step info, and KPI thresholds.
3. **Delete stale lock file** before re-running: `rm -f ~/.config/studyplan/app_instance.lock`
4. **Clear stale bytecache** if source edits don't take effect: `find . -type d -name "__pycache__" -exec rm -rf {} +`
5. **Check exit code**: `timeout` returns 124 if the command exceeded its budget (increase timeout).
6. **Check stderr** with `2>&1` — some errors (GTK assertions, GLib warnings) only appear on stderr.

### Non-obvious caveats

- **`python` must be available**: The system may only have `python3`; create a symlink with `sudo ln -sf /usr/bin/python3 /usr/bin/python` if needed.
- **Smoke test is slow (~3.5 min)**: On this hardware the smoke test takes ~210s. Use `timeout 300s` or the `--smoke-fast` flag if available.
- **ruff config issue**: The `pyproject.toml` `[tool.ruff]` section includes `W503` in the `ignore` list, which is not a valid ruff rule. This causes `ruff check` to fail. The `linux-ci.yml` workflow uses `python tools/gtk4_lint.py` instead of ruff.
- **Lock file**: The app enforces single-instance via `~/.config/studyplan/app_instance.lock`. If a prior run was killed ungracefully, remove this file before re-running: `rm -f ~/.config/studyplan/app_instance.lock`.
- **`~/.local/bin` on PATH**: pip installs dev tools to `~/.local/bin`; ensure it's on PATH (`export PATH="$HOME/.local/bin:$PATH"`).
- **Pre-existing test failure**: `test_semantic_tfidf_assets_reused_on_repeated_queries` fails consistently — this is a pre-existing issue, not caused by environment setup.

## Architecture & Key Conventions

### File roles

| File | Role | Key size |
|------|------|----------|
| `studyplan_app.py` | Main GTK UI (~54.5k lines) — all windows, panels, dialogs, dashboard, charts | ~54.5k lines |
| `studyplan_engine.py` | Data layer — SRS, pomodoro, quiz logic, schedule, mastery | ~20k lines |
| `studyplan_ai_tutor.py` | AI tutor — recall, evaluation, domain reasoning | ~10k lines |
| `studyplan/domain_reasoning/` | Step matcher, evaluator, reasoning engine for Section C | ~1k lines |
| `studyplan/ai/llama_runtime.py` | LLM orchestrator — tries Ollama → managed llama-server → cloud API | ~600 lines |
| `studyplan/ai/llama_server.py` | llama-server subprocess lifecycle manager | ~500 lines |
| `studyplan/ai/circuit_breaker.py` | Per-backend failure tracking with auto-reset | ~100 lines |
| `studyplan/ai/model_selector.py` | Task-aware model ranking and filtering | ~300 lines |
| `tools/gtk4_lint.py` | Custom lint for GTK4 patterns | — |

### Dashboard rendering (`_render_dashboard` at line ~51397)

- Clears and rebuilds all dashboard children **every refresh** (triggered by timer or manual refresh).
- `chart_style` dict is defined at line ~52160 with color palette (`fig_bg`, `ax_bg`, `text`, `muted`, `grid`, `accent_a`/`b`/`c`/`d`, `legend_bg`). Two variants: dark and system-theme-aware dark.
- Chart **caching** via `_cached_*_sig` + `_cached_*_widget` pairs prevents Cairo redraw when data unchanged. Signature is a tuple (typically the data values). If sig matches and cached widget exists, re-append the cached widget; otherwise build, cache, append.
- **Performance helper**: `_chart_rgb_cache` dict (class-level) avoids redundant hex→RGB parsing (~80-120 saves per refresh).
- **Local variable caching** (at line ~51582): Engine references (`_eng`, `_chapters`, `_competence`, `_progress_log`, `_srs_data`) are cached as locals. Additional single-pass derived caches:
  - `_parsed_progress` (line ~51591): `list[(date, mastery, minutes)]` sorted — replaces 4× redundant dict→tuple parsing across Coach Briefing, Coach Recap, Progress Over Time chart, and Weekly Summary.
  - `_sorted_competence` (line ~51612): `list[(chapter, score)]` sorted ascending — replaces 2× sort in Weak vs Strong.
  - `_srs_overdue_by_ch`, `_srs_due_soon_by_ch`, `_srs_due_week_by_ch`, `_srs_next_due` (line ~51626): Per-chapter SRS summary computed once — replaces 2× nested loop in Pie Chart and Reviews & Pace sections.
- Dashboard order: Coach briefing → Confidence Drift bar → Progress Over Time line → Per-Topic Snapshot grouped_bar → Separator → Study Snapshot stats → Weekly Summary → Plan View → Mastery Snapshot → Weak vs Strong → Reviews & Pace → Reviews Due Today → Leech Alerts → Study Hub → Data Health → Activity chart (on-demand button).

### Chart system (`_build_gtk_chart_widget` at line ~50380)

- **All Cairo-based** (no matplotlib). Uses `Gtk.DrawingArea` with `set_draw_func(_draw)`.
- Canvas gets `set_size_request(min_width, height)` + `set_hexpand(True)` — charts fill container width.
- Chart kinds: `"bar"`, `"line"`, `"grouped_bar"`, `"hbar"` (horizontal bar).
- `"hbar"` kind (line ~50565): Takes `items: [{"label": str, "value": float, "color": str}]`. Draws horizontal bars proportional to `value/max_val`. Label on left (14px), bar from `bar_x` (86px), value text at bar end.
- `content_height` is fixed (180-260px), width is flexible via hexpand.
- Helper methods: `_chart_set_color(ctx, hex_str)`, `_chart_text(ctx, text, x, y, size, weight)`, `_rounded_top_bar_rect(ctx, x, y, w, h, r)`, `_chart_rgb(hex_str) -> (r,g,b)`.

### On-demand chart pattern (for new charts)

- Add cache vars in `__init__`: `self._cached_activity_chart_sig` and `self._cached_activity_chart_widget`.
- In `_render_dashboard`, at the very end (before `_finalize_perf()`):
  1. If cached chart exists → append it directly.
  2. Otherwise → show a `Gtk.Button(label="Show ...")` with `add_css_class("flat")`.
  3. On click: compute a data signature → if cached, use cached widget; else call `_build_*_chart(chart_style)` → store in cache → replace button with chart.
- Wrap the entire section in `try/except Exception: pass`.

### UI text conventions

- **Default pattern**: `wrap=False`, `ellipsize=END`, + tooltip via `_sync_single_line_label_tooltip()`.
- **Wrapping labels**: `wrap=True`, `ellipsize=NONE`, `allow-wrap` CSS class, `max_width_chars` only when container forces a limit. Never use `max_width_chars` for single-line labels.
- **Coach briefing labels**: labeled with `"allow-wrap"` or `"single-line-lock"` CSS classes. `_enforce_coach_label_wrap()` sets max_width_chars=180 for wrapping labels.
- `_ellipsize_labels(container, max_chars=N)` walks all direct labels — safe to call on dashboard with `max_chars=200`. Avoid calling on study room wrapping labels (redundant).
- No CSS hyphenation; word-wrap via `Pango.WrapMode.WORD_CHAR`.

### GTK4 nuances & common pitfalls

This app targets **GTK4** (PyGObject / `python3-gi`). GTK3 APIs will fail at runtime. Key differences:

| GTK3 pattern (WRONG) | GTK4 pattern (RIGHT) | Why |
|---|---|---|
| `.set_keep_above(True)` | **Removed.** Use compositor (Hyprland) window rules instead. | GTK4 dropped `GtkWindow.set_keep_above()` |
| `.set_accessible_name("...")` | **Not available** on `Gtk.Button` / most widgets before GTK 4.10. Use `.set_tooltip_text()` or wrap in `try/except AttributeError`. | GTK4 accessiblity uses `Gtk.Accessible` interface |
| `dialog.run()` (modal) | `dialog.present()` + `dialog.connect("response", handler)` | `run()` blocks the main loop; removed in GTK4 |
| `.set_wrap(True)` on `Gtk.CheckButton` | `try: btn.set_wrap(True); except AttributeError: pass` | Only available in GTK ≥ 4.10 |
| `.set_height_request(N)` | `.set_size_request(-1, N)` | `set_height_request()` doesn't exist in GTK4 |
| `.set_width_request(N)` | `.set_size_request(N, -1)` | Same as above |
| `.set_pulse_step(0.1)` | **Removed.** Omit or wrap in try/except. | GTK4 progress bar removed pulse_step |
| `Gtk.Alignment` | **Removed.** Use `.set_halign()` / `.set_valign()` on the widget itself. | Alignment is a property, not a container |
| `Gtk.Table` | Use `Gtk.Grid` with `.attach()` | Table was removed in GTK4 |
| `Gtk.EventBox` | **Removed.** Add `Gtk.GestureClick` directly to the widget. | EventBox was a GTK3 workaround |
| `Gtk.ComboBoxText` | Prefer `Gtk.DropDown` | ComboBoxText is deprecated |
| `Gtk.ListStore` + `Gtk.TreeView` | Prefer `Gtk.ColumnView` + `Gtk.NoSelection`/`Gtk.SingleSelection` | TreeView is legacy (still works but no new features) |
| `.modify_bg()`, `.modify_fg()` | **Removed.** Use CSS classes + `Gtk.CssProvider`. | All styling is CSS-only in GTK4 |
| `Gtk.Box(homogeneous, spacing)` positional args | Use keyword: `Gtk.Box(orientation=..., spacing=N)` | Positional args deprecated |
| `.set_resize_mode()` / `.set_fixed_height_mode()` | **Removed.** No replacement needed. | These were GTK3 internal hints |
| `Gtk.HBox` / `Gtk.VBox` | Use `Gtk.Box(orientation=HORIZONTAL / VERTICAL)` | HBox/VBox removed in GTK4 |
| `Gtk.Arrow` | **Removed.** Use Unicode arrows or CSS. | No replacement |
| `Gtk.Menu` / `Gtk.MenuBar` (old API) | Use `Gtk.PopoverMenu` + `Gtk.MenuButton`. The app's menu bar uses the legacy `Gtk.MenuBar` path (still works but frozen). | New code should use popovers |
| `widget.get_allocation().width` | Use `widget.get_width()` / `widget.get_allocated_width()` | `get_allocation()` not available |
| `Gtk.Window.set_wmclass()` | **Removed.** No replacement. | WM class detection is compositor-level |

**Defensive pattern**: When in doubt about a GTK3-ism, wrap in `try/except AttributeError: pass` and leave a comment. The app supports PyGObject 3.46+ (GTK 4.6–4.14), so some 4.10+ APIs may be unavailable.

### Block duration & timer routing

- Block minutes: read from `next_block.get("minutes", 25)` — schedule is authoritative, not hardcoded.
- Quiz block → `start_quiz_session(topic, kind="quiz")` → `_start_quiz_block_timer()` (countdown with 2min/1min notifications, nudges but does NOT auto-submit).
- Review block → `start_quiz_session(topic, kind="review")` + countdown.
- Recall block → block's minutes → `_prompt_recall_checkin()` → mini-quiz (3 questions).
- Timer tick (`_quiz_block_timer_tick` at line ~44490) handles the 2min/1min/expiry notifications.

### Engine deferred loading (`studyplan_engine.py` line ~3550)

- `__init__` accepts `defer_data_load=True` → skips `load_data()`, model loading, `load_questions()`, `save_data()`.
- Engine initializes with empty defaults (<50ms fast path). Public API works with defaults.
- `_do_deferred_data_load()` called via `GLib.idle_add` from `_run_initial_refresh()`.
- `_ensure_deferred_data_loaded()` used as guard before data-dependent operations.

### Data model (key dicts accessed from `self.engine` or `self`)

| Dict | Source | Structure |
|------|--------|-----------|
| `action_time_log` | `self` (app) | `{kind: {"seconds": float, "sessions": int}}` — kinds: pomodoro_focus, pomodoro_recall, quiz, drill, review |
| `progress_log` | `self.engine` | `[{date, overall_mastery, total_minutes}, ...]` |
| `srs_data` | `self.engine` | `{chapter: [{box, last_review, interval, ease}, ...]}` |
| `pomodoro_log` | `self.engine` | `{"total_minutes": int, "by_chapter": {...}}` |
| `competence` | `self.engine` | `{chapter: score (0-100)}` |
| `quiz_results` | `self.engine` | `{chapter: score (0-100)}` |
| `question_stats` | `self.engine` | `{chapter: {question_id: correct/total, ...}}` |
| `study_hub_stats` | `self.engine` | `{"total_questions": int, "questions_taken": int, ...}` |

### Important method locations

| Method | Line | Purpose |
|--------|------|---------|
| `_render_dashboard` | ~52120 | Main dashboard rebuild |
| `_build_gtk_chart_widget` | ~50380 | Cairo chart factory |
| `_build_mastery_bar` | ~50640 | Segmented mastery bar |
| `_build_activity_time_chart` | ~50605 | On-demand activity hbar |
| `_compute_activity_chart_sig` | ~50635 | Activity chart cache sig |
| `_on_pomodoro_start` | ~43940 | Block routing logic |
| `_start_quiz_block_timer` | ~44490 | Quiz countdown timer |
| `_run_initial_refresh` | ~2610 | Deferred data load trigger |
| `_enforce_coach_label_wrap` | ~51050 | Coach label width limit |
| `_ellipsize_labels` | ~40470 | Global ellipsize pass |
| `_chart_set_color` | ~50380 | Cairo color setter |
| `_chart_text` | ~50385 | Cairo text renderer |
| `_refresh_workbench_shell_status` | ~3956 | Status bar (page • topic • model • autopilot • connectivity) |
| `_compute_workbench_model_readiness` | ~4123 | Model readiness states (disabled → ready + cloud health) |
| `_compute_workbench_app_health` | ~4240 | App health states (sync • offline • circuit • ready) |
| `_has_internet_connectivity` | ~19215 | TCP-based connectivity probe (cache 30s/5s) |
| `_cloud_connectivity_policy_mode` | ~19213 | Resolves policy: instance attr → env var → auto |

### Status bar / Workbench shell

Three labels refresh every 2s via `_start_workbench_status_timer()`:

| Label | States | Includes |
|-------|--------|----------|
| `workbench_status_label` | Page • Topic • Model • AP • RAGemb • SB • **Net on/off** | Connectivity indicator |
| `workbench_model_label` | disabled • unavailable • recovering • not_loaded • syncing • **ready** (+ cloud health) | Model source + circuit breaker state |
| `workbench_health_label` | sync_issue • model_unavailable • recovery_mode • **offline** • circuit_open • **ready** | Internet status + circuit breaker |

### LLM Pipeline (fallback chain)

`LlamaRuntime.ensure_ready()` (studyplan/ai/llama_runtime.py) tries in order:
1. **Cloud API** gateway (if enabled + circuit closed + online)
2. **Managed llama-server** (auto-started from ranked GGUF models)
3. **Ollama** (auto-discovered at localhost:11434)

Each backend has independent failure tracking. The cloud endpoint uses a `CircuitBreaker` (threshold=3, cooldown=30s). When tripped, requests skip directly to managed llama-server.

Connectivity is probed via `_has_internet_connectivity()` (TCP to 1.1.1.1:443, 8.8.8.8:53, plus cloud endpoint host). Cache: 30s online, 5s offline. Policy can be overridden via Preferences (auto/online/offline) or env var `STUDYPLAN_CLOUD_CONNECTIVITY_POLICY`.

### Testing

- Unit tests in `tests/`: `test_step_matcher.py` (35), `test_domain_reasoning.py` (88).
- 1796 tests total (1 skipped pre-existing).
- Smoke test: `xvfb-run -a timeout 120s python studyplan_app.py --dialog-smoke-strict`
- No flaky async tests — everything runs in the main thread.

### GTK patterns to follow

- Cards: `Gtk.Box(orientation=VERTICAL, spacing=4)` + `add_css_class("card")` + `add_css_class("card-tight")` + optionally `"chart-card"` / `"insight-card"`.
- Expanders: `_wrap_expander_card(title_text, child_widget, expanded=False)` — wraps content in a collapsible card.
- Separator: `Gtk.Separator(orientation=HORIZONTAL)` + `add_css_class("rule")`.
- Section titles: `self._ui.section_title("text")` — returns a styled `Gtk.Label`.
- Tooltips on single-line labels: `self._sync_single_line_label_tooltip(label, full_text)`.
- Buttons: `Gtk.Button(label="...")` + `add_css_class("flat")` + `set_halign(START)`. On-demand buttons should show at the bottom of the dashboard.
- All GTK operations happen in the main thread. No thread safety concerns.

### Rust/PyO3 crate (`studyplan/rs/`)

| Item | Detail |
|------|--------|
| Location | `studyplan/rs/` — Cargo.toml, pyproject.toml, `src/lib.rs` |
| Python wrapper | `studyplan/rs/srs_select.py` — tries `from studyplan_rs import ...`, falls back to `_select_srs_from_scored_py()` |
| Build | `cd studyplan/rs && maturin build --release` (requires Rust toolchain + maturin). Output wheel → `pip install target/wheels/studyplan_rs-*.whl` |
| CI | `.github/workflows/linux-ci.yml` → `build-rust` job (non-gating, `continue-on-error: true`) |
| First function | `select_srs_from_scored()` — Phases 1-4 of `select_srs_questions` in `studyplan_engine.py:11140`. Pure-data pipeline: scored tuples → selected indices. |
| Caveats | Python ≥3.14 requires `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` until PyO3 releases a new version. CI uses Python 3.12 so this doesn't apply there.
