# AGENTS.md

## CCI Research Protocol — binding instructions

When asked to do any task, I MUST follow the CCI Research Protocol
(`docs/specification/RESEARCH_PROTOCOL.md`) word for word:
- Start with the Essentialist Question: "What phenomenon does this code exist to preserve?"
- Collect observations across ALL six orthogonal scans before abstracting
- Generalize before falsifying (Rule 4 — most important)
- Every abstraction must be earned, never invented
- Classify findings into evidence classes, assign to correct architectural layer
- Add predictions, compression scores, and falsification conditions
- Never optimize for fewer lines; optimize for fewer architectural concepts
- The protocol is frozen — no amendments until 3+ independent domains analyzed

## Session tracking (Jul 2026)

### Done
- Step 2: Provenance wired into Intelligent Tutor — `build_provenance_context()` in `studyplan_ai_tutor.py:1195`, provenance data reaches LLM prompt via `_generate()` at `studyplan_app.py:8589`
- Step 6: CCI-provenance trace bridge — `studyplan/trace_bridge.py` (embed, extract, correlate, unified_trace_view); 26 tests
- Step 4: FastDomainCompiler pattern expansion — `ParametricSpec` with `{i}` template substitution in `fast_compiler.py`; 20 tests
- Step 1: Interactive Debugger (Layer 6) — `DebugExecutor` with `ExecutionSnapshot`, `Breakpoint`, `StepController`, `step_through()` generator; 28 tests in `studyplan/provenance/lab/debugger.py`
- **Formula Bridge** (`studyplan/provenance/formula_bridge.py`): Auto-compiles `FormulaDecl` from DSL registry into provenance `DomainSpecs` for `FastDomainCompiler`. 22 tests.
- **DomainRegistry — Universal Domain Compiler** (`studyplan/provenance/domain_registry.py`): Live concept→ViewState map with auto-compile on registration. 30 tests.
- **Music Theory Domain (18 tests)** — 5th domain (humanities), validates universality.
- **Identity System v2** (`studyplan/provenance/lab/compilation/identity_v2.py`): ProvenanceWeightedIdentity, SemanticEquivalenceScorer, GlobalIdentityRegistry, ConflictAwareMerger. 27 tests.
- **PDF Frontend** (`studyplan/provenance/lab/compilation/pdf_plugin.py`): Third frontend on the RAG pipeline. 28 tests.
- **RuntimeIndex** (`studyplan/provenance/runtime_index.py`): Immutable, shareable execution image. Construction Experiment H-RT-01 — 5 predictions confirmed.
- **Compilation Workspace** (`studyplan/provenance/lab/compilation_workspace.py`): GTK compiler IDE — source panel, pipeline view, semantic diff, identity review with Merge/Keep/Compare/Provenance/Dependency buttons. Wired into `studyplan_app.py` as "Compiler" tab (`_build_compiler_workspace_page`, `_refresh_compiler_workspace_page`). Instrumented with investigation events and review decision emission.
- **`compiler.*` event taxonomy** added to EventBus (`studyplan/provenance/learning/events.py`): 10 event types across three categories:
  - **Lifecycle**: `source_imported`, `compilation_started`, `extraction_completed`, `ambiguity_detected`, `publish_completed`
  - **Investigation**: `review_opened`, `provenance_viewed`, `dependency_graph_viewed`, `candidate_compared`
  - **Decision**: `merge_candidate`, `review_decision` (with latency, evidence, confidence), `review_abandoned`
- **Compiler Bridge** (`studyplan/provenance/learning/compiler_bridge.py`): `get_compiler_bus()` / `set_compiler_bus()` singleton — mirrors `LearningIntegrator` pattern.
- **Stopword filtering** in workspace: `STOPWORDS` frozenset filters noise concepts from review panel.
- **Class E — Epistemic Evidence** added to `RESEARCH_PROTOCOL.md`: Evidence about *how justified belief changes during knowledge engineering* — decision latency, evidence consulted, confidence delta. Justified under Constitutional Amendment I condition 1 (existing protocol cannot explain this evidence). Distinguishes investigation events from decision events.
- **T-PC-01 confidence propagation** (Jul 2026): `build_provenance_context()` accepts optional `assumption_confidence` dict → renders `name [score]`. LLM experiment confirmed: WITH confidence → model calibrates response (mentions "confidence" 6×, uses bracket notation, adds badges like ✅ Well-established); WITHOUT confidence → generic table, no calibration. Principle promoted to Supported.
- **CI-B-01 Compiler→Integrator Bridge**: `CompilationWorkspace.get_alias_map()` exposes GIR's `_local_to_canonical`, pushed to `ProvenanceIntegrator` after every `compile_all()`. Normalizes artifact names in `capture_trace()` and `tutor_context()`. 8 tests pass.
- **Default confidence in tutor prompts** (Jul 2026): `ProvenanceIntegrator.tutor_context()` auto-computes per-assumption confidence from ViewState transform depth via BFS. Direct assumptions = 0.95, decay 0.10 per backward hop, floor 0.50. Both app call sites (`_generate()`, `_build_ai_tutor_context_prompt()`). Dead `_confidence_map` wiring removed.
- **H-OP-01 Optimization Protocol** (Jul 2026): Protocol analysis of 13 observations across 6 orthogonal scans. Corrected root cause: **no stable computation identity boundary** — work units lack content-addressed keys. Three predictions: P-CP-01 (label index + persist GIR, 8:1 compression), P-CP-02 (equivalence class index, adjunct to P-CP-01), P-CP-03 (subgraph invalidation tracking, 4:1, deferred). Pass fusion rejected as premature (< 2× at current CIR sizes). Documented in `docs/architecture.md§Optimization Protocol`.

### Key Decisions
- **Investigation ≠ Decision**: `compiler.*` events separate *how* knowledge engineers investigate (provenance_viewed, dependency_graph_viewed, candidate_compared) from *what* they decide (review_decision, review_abandoned). Two reviewers with identical decisions but different investigation paths produce different event histories.
- **Class E is not UX telemetry**: Measures "what evidence caused uncertainty to decrease," not engagement/clicks/retention.
- **Falsifiable test of observability**: After a month of FM study through the Workbench, do `compiler.*` events produce engineering decisions that couldn't exist without them? If events are ignored, the taxonomy is too fine-grained.
- **Protocol amendment justified**: Class E added under Constitutional Amendment I condition 1 — human confidence/hesitation data cannot be classified by existing evidence classes A–D.
- **Root cause depth (H-OP-01)**: The optimization problem is not "no cache" — it's "no stable computation identity boundary." Content-addressed identity keys (type, label) enable amortized O(1) resolution over time, eliminating both global recomputation and O(N) linear scans at the root. This is why P-CP-01 alone compresses 8/13 observations and why pass fusion is premature at current graph sizes.
- **Weights driven by experiment (not intuition)**: Default policy weights are now (0.55, 0.30, 0.10, 0.05) — derived from sensitivity analysis. Confusion dominates (0.2475 mean influence), leverage is strong (0.0750), collapse and stability are weak in marginal value but retained for edge cases. The sensitivity analysis itself confirmed the protocol is working: it identified dead weight, and the reweighting is a falsifiable improvement.

### Cognitive Control Layer — Phase 3 (Jul 2026)
- **Four-layer architecture complete**: CIR (truth) → Event Bus (observation) → Projection (inference) → Controller (control)
- Every layer is a *pure function* over the layers below it — the entire stack is replayable and falsifiable
- **Key files**:
  - `studyplan/provenance/cognition/controller.py` — `CognitivePolicyEngine`, `CognitiveController`, `ForwardModel`, `Intervention`, `ActionType` (6 action types)
  - `studyplan/provenance/cognition/experiment.py` — `CognitiveExperiment` with sensitivity analysis, ablation study, counterfactual experiment
  - `studyplan/provenance/cognition/outcome.py` — `PredictionOutcome`, `PredictionOutcomeComparator`, `compute_closed_loop_outcomes`
  - `tools/run_cognition_experiments.py` — interactive experiment runner (run `python tools/run_cognition_experiments.py --verbose`)
- **86 tests** covering controller (30), outcome/comparator (32), experiment (24) — all pass
- **Default weights** (evidence-based): confusion=0.55, leverage=0.30, collapse=0.10, stability=0.05
  - Derived from sensitivity analysis: confusion dominates (0.2475 mean influence), leverage is strong (0.0750), collapse/stability are weak in marginal value but retained for edge cases of isolated uncertainty and decaying familiarity
  - Ablation study confirms ALL signals are alive when isolated (each changes ranking on removal)
- **Closed-loop action outcomes**: `action_taken`/`action_outcome` events (cognition.*), `PredictionOutcomeComparator` compares ForwardModel predictions vs observed deltas, `compute_closed_loop_outcomes()` re-projects bus before/after each action
- **UI polish**: Cognitive State card added to Compiler tab — health dot (color-coded by score severity), event count, next best action, top-3 intervention rankings with rationale, calibration confidence display

### Learning System — Phase 3.5 (Jul 2026)
- **ForwardModel is now calibratable**: `update_from_outcome()` adjusts delta estimates toward empirically observed values using signed-error delta rule: `delta[k] += lr × (observed[k] − predicted[k])`
- **Per-action-type confidence**: Tracks update count per ActionType → `calibration_confidence` property (min(1.0, count/10))
- **Auto-calibration in workspace**: `_update_cognitive_panel()` processes unprocessed `action_outcome` events from `compute_closed_loop_outcomes()` and feeds them to ForwardModel — zero manual intervention needed
- **Convergence proven**: Repeated outcomes with lr=0.5 converge to <0.01 error within 10 iterations
- **12 calibration tests** covering: delta adjustment, convergence, signed errors, action isolation, confidence tracking, reset, unknown type, modulation independence, end-to-end comparator integration

### Test status
- **3810 pass / 0 failures / 1 skip** = 3811 total
- 118 compilation tests, 35 event bus tests, 98 cognition tests (54 base + 32 outcome + 12 calibration) — all pass
- 2 new event types: `cognition.action_taken`, `cognition.action_outcome`
- ForwardModel `update_from_outcome()` — 12 tests proving convergence, calibration confidence, modulation independence

### Critical Context
- **Compilation Workspace** at `studyplan/provenance/lab/compilation_workspace.py` — standalone module with GTK page builder, full pipeline (extract → validate → passes → merge → review), identity review with 3 investigation buttons (Provenance/Dependency/Compare) + 2 decision buttons (Merge/Keep). Now includes Cognitive State card with health indicator and intervention recommendations.
- **Wired into app**: Compiler tab registered in `_build_workbench_shell`, `_workbench_aliases`, `_refresh_workbench_page` dispatch map, and stability repair path.
- **Event bus pattern**: `get_compiler_bus()` returns singleton `EventBus`; workspace calls `self._bus.emit(...)` at each stage; bus gracefully degrades if None.
- **PredictionOutcome closes the loop**: `PredictionOutcomeComparator.compare()` takes intervention + pre/post projections → produces observed deltas, prediction error, success flag. `compute_closed_loop_outcomes()` scans bus history for action_taken events and auto-computes outcomes.
- **ForwardModel now learns**: `update_from_outcome()` adjusts deltas via signed-error delta rule. Auto-calibrated in workspace from action_outcome bus events. Convergence proven in 12 tests.
- **Architecture milestone**: System has crossed from "self-evaluating" to "self-improving" — a deterministic cognitive system with a closed-loop evaluation signal plus a parameter update rule over its own policy decisions.

## Critical Context (Phase 4+)

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

## Algebra Ontology (Phase 4, frozen Jul 2026)

### Four-layer architecture

```
Level 0: Execution protocol  (initialize → step → finished → result)
Level 1: Ontology            (S, M, I, C, Φ)
Level 2: Metric              (similarity over ontology coordinates)
Level 3: Estimator           (trace → ontology coordinates)
```

### A = (S, M, I, C, Φ)

- **S** = State space (topology, dimensionality, admissible values, locality)
- **M** = Operator algebra (admissible transformations S→S, characterized by intrinsic algebraic properties — reversibility, locality, monotonicity, topology/value/branching mutation — not operator names)
- **I** = Logical invariants (predicates that hold at every reachable state)
- **C** = Conserved quantities (scalars/structures preserved by every M)
- **Φ** = Completion semantics (semantic fixed point of computation)

**Status**: S, I, C, Φ are frozen. M is provisional — can be refined within the operator property space, but new coordinates require the evolution rule.

### Ontology evolution rule

A new coordinate may be introduced only if: (1) unexplained residual persists across multiple algebras, (2) cannot be eliminated by refining existing coordinate, (3) is independently observable, (4) improves held-out predictions.

### Validation

Ontology predicts human similarity rankings with ρ = 0.774 (p = 0.0007, n=15 pairs). The CSP–GG residual was resolved by refining M's internal property space rather than adding a coordinate.

### Phase 4C-E1: Residual clustering (Jul 2026)

**Script**: `tools/algebra_residual_analysis.py e1`

**Question**: Are residuals systematic (missing coordinate) or concentrated (M refinement)?

**Result**: Not systematic. All large residuals involve Justification (J) but with **opposite polarity** — J is simultaneously undersimilar to GG (+0.17) and oversimilar to CSP (−0.13). This polarity mismatch rules out a missing coordinate and implicates M's operator property space for support/retract. Non-J pairs have mean |R| = 0.026 (essentially noise).

**Recommendation**: Proceed to E2 (property augmentation) — test whether adding an inferential or semantic-domain property to the operator vectors resolves both residuals simultaneously.

### Phase 4C-E2: Property augmentation (Jul 2026)

**Script**: `tools/algebra_residual_analysis.py e2`

**Question**: Does adding a candidate property to the operator vectors resolve both GG-J and CSP-J simultaneously?

**Result**: Marginal improvement only. The best candidate (`inferential`) reduces total |R| by 5.5% (0.298 → 0.281). GG-J improves from +0.173 to +0.148, but CSP-J worsens from −0.125 to −0.133. The improvement is too small to justify modifying the operator property space.

**Implication**: The residual does NOT reside in M alone. Operators inherit semantic properties from their S context (expand on goal-graph vs support on belief-graph), which a fixed 10-dimensional operator vector cannot capture. This supports the "semantic domain = metadata on S" hypothesis.

### Key files

| File | Role |
|------|------|
| `docs/algebra_atlas.md` | Full ontology specification (551 lines, 30 sections) |
| `tools/algebra_experiments.py` | Experiment harness — 9 Phase 2 experiments |
| `tools/algebra_observatory.py` | Observatory v2 — confidence distributions, coherence metric, blind trace API |
- **Lock file**: The app enforces single-instance via `~/.config/studyplan/app_instance.lock`. If a prior run was killed ungracefully, remove this file before re-running: `rm -f ~/.config/studyplan/app_instance.lock`.
- **`~/.local/bin` on PATH**: pip installs dev tools to `~/.local/bin`; ensure it's on PATH (`export PATH="$HOME/.local/bin:$PATH"`).
- ~~**Pre-existing test failure**: `test_semantic_tfidf_assets_reused_on_repeated_queries` fails consistently — this is a pre-existing issue, not caused by environment setup.~~ **FIXED** (test passes 1926/1926).

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
- 1942 tests total (1 skipped pre-existing).
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

## Coach Pick Consistency & CPU

### Anti-pattern found & fixed (Jun 2026)

Two locations had `_queue_coach_sync_if_mismatch()` called **before** `_ensure_coach_pick_consistency()`, guaranteeing a false-positive mismatch every time because `_coach_pick_topic` (left panel) was never yet updated:

1. **`_render_dashboard`** at `studyplan_app.py:51865` — moved after `_ensure_coach_pick_consistency()`
2. **`_update_study_room_card_impl_inner`** at line `43399` — moved after the consistency sync block

**Why this matters for CPU**: Each false-positive mismatch scheduled `_run_coach_sync_after_mismatch` via idle_add, which called `update_dashboard()` back → producing a guaranteed **2x multiplier** on every dashboard render. Combined with the 7+ expensive engine queries in the coach card update (`get_chapter_difficulty_ratio`, `get_interval_release_confidence`, `get_chapter_recall_risk`, `get_syllabus_chapter_intelligence`, `get_undercovered_capability_chapters`, `get_topic_due_count` + SRS iteration per item, `_get_pace_info`, `_get_weak_chapter`), a single dashboard render could trigger **14+ engine queries** in one burst.

This doesn't cause 100% CPU at pure idle (no repeating timers fire these), but does cause cluster bursts on any event-driven dashboard refresh.

### Remaining CPU concern: `_compose_coach_reasons` cost

`_update_coach_pick_card_inner()` calls `_compose_coach_reasons(topic)` on every coach card update (cached 30s). This runs 7 expensive engine queries including `get_chapter_recall_risk` (samples 40 questions, may call `predict_recall_prob` ML). If triggered frequently, consider extending cache TTL or adding a skip-timer.

## Semantic warmup CPU burst

### What runs at startup (4s after launch)

`_semantic_warmup_tick` (`studyplan_app.py:41148`) fires once via timeout (default 4s delay). It spawns a background thread via `_warmup_semantic_engine_async` which calls:

1. **`_semantic_get_model()`** (`studyplan_engine.py:6049`) — Loads SentenceTransformer (PyTorch) + optionally CrossEncoder. One-time, CPU-heavy model load.
2. **`_semantic_prefetch_chapter_assets()`** (`studyplan_engine.py:6222`) — Builds TF-IDF vectorizers for the top N chapters (`SEMANTIC_WARMUP_PREFETCH_CHAPTER_LIMIT=6`).

### The TF-IDF storm (fixed Jun 2026)

`_semantic_prefetch_chapter_assets` used `max_workers = min(len(work_items), max(1, os.cpu_count() or 4))` — spawning a **ThreadPoolExecutor per chapter** equal to CPU core count. Each worker called `TfidfVectorizer.fit_transform()` on hundreds of outcome texts (tokenization + IDF compute + matrix build). On an 8-core machine with 6 prefetch chapters, 6 worker threads saturated all cores in a CPU-bound computation storm.

**Fix** (`studyplan_engine.py:6285`): Cap workers to max 2 — TF-IDF `fit_transform` is CPU-bound; >2 threads adds OS scheduler overhead without throughput gain.

### Post-warmup dash update

After the background thread completes, `GLib.idle_add(_finish)` fires which calls `update_study_room_card()` + `update_dashboard()`. This triggers the full coach-pick cache-miss cascade (2x multiplier) for the first interactive render. The coach sync fix prevents further cascades on subsequent renders.

## Dashboard section reconciliation (Phase 4c, Jun 2026)

### What changed

`_render_dashboard` previously **unconditionally removed all children** from `self.dashboard` (lines ~51590–51594) and rebuilt every section from scratch on every refresh. The `_reconcile_sections()` function and section-tracking infrastructure (`_ds_id`, `_ds_mark`, `_dashboard_section_seen`) existed but were dead code — `_ds_id` was never assigned to any widget.

**Fix**: Removed the full-clear loop. All ~35 dashboard sections now get tagged with `_ds_id` via `_ds_mark()` at build time. Before appending, `_ds_mark()` auto-removes any existing widget with the same `_ds_id` to prevent duplicates. At the end of every render cycle, `_reconcile_sections()` removes orphan widgets whose `_ds_id` is no longer in `_dashboard_section_seen`.

### New helpers (nested inside `_render_dashboard`)

| Helper | Purpose |
|--------|---------|
| `_ds_check(sid, digest)` | Returns True if section exists with matching digest → cache hit, marks as seen, skip rebuild |
| `_ds_remove(sid)` | Removes existing widget with given sid (used before digest-checked rebuilds) |
| `_ds_mark(sid, widget, digest)` | Sets `_ds_id` + `_ds_digest`, removes stale duplicates, appends, marks as seen |
| `_reconcile_sections()` | Removes all widgets whose `_ds_id` is not in `_dashboard_section_seen` |

### Digest-checked sections (expensive, skip rebuild when data unchanged)

- **coach_briefing**: digest = `(readiness_score, pace_status, recommended_topic, pick_source)` — skips 7+ engine queries on cache hit
- **onboarding**: digest = `("onboarding",)` — shown only on first run
- **exam_countdown**: digest includes `days_remaining`
- **empty_module**: digest = `(True,)` — shown only when no chapters loaded
- **no_syllabus_warning**: digest = `("no_syllabus_warning",)` — shown only when syllabus missing

### Always-rebuilt sections (still benefit from `_ds_id` tracking)

All other sections (time_analytics, quiz_insights, leaderboards, daily_summary, drift_chart, progress_chart, topic_chart, next_action, recap cards, mastery section, pie chart, study_snapshot, weekly_summary, plan_view, weak_vs_strong, reviews_pace, etc.) always rebuild but use `_ds_mark` for proper orphan cleanup and future digest integration.

### Conditional section cleanup

Sections that are conditionally hidden (based on `focus_mode`, `tile_mode`, data availability) are automatically removed by `_reconcile_sections()` when the condition becomes false — the section simply isn't marked as seen that cycle.

### Early return paths

`_reconcile_sections()` is called before the two early returns:
1. `empty_module` (no chapters loaded) — at line ~51821
2. `focus_mode` (short circuit after coach section) — at line ~53281

### Performance characteristics

- **GTK parenting ops**: Changed from `N removes + N appends` (full clear + rebuild) to `N removes + N appends` (per-section rebuild) — same count, but widgets are now tagged and trackable.
- **Digest-checked sections**: Avoid GTK rebuild entirely when data unchanged. The coach_briefing section (most expensive at 7+ engine queries) is the primary beneficiary.
- **Conditional sections**: Previously required careful conditional logic to avoid stale widgets. Now handled automatically by reconcile.
- **No visible flash**: Widgets that don't change stay in place visually; only updated widgets flash.

## Build artifacts & .gitignore

The following build artifacts are untracked and gitignored:

| Pattern | Reason |
|---------|--------|
| `studyplan/rs/target/` | Rust build output (`.rlib`, `.so`, `.d`, `.whl`) — regenerated by `maturin build --release` |
| `studyplan/cython/*.c` | Generated C source from `.pyx` files (still tracked) — regenerated by `cythonize` |
| `studyplan/cython/*.so` | Compiled shared objects from `.pyx` — regenerated by build |

The `.gitignore` entries were added in commit `dddcaf4` to prevent these from being re-added after untracking.

## Ruff check

Run `ruff check .` from repo root (not `ruff .` or `ruff check`).

## detect_concepts variable redeclaration

`detect_concepts` in `studyplan/domain_reasoning/concepts.py` has two code paths (domain and ACCA FM fallback) that both declare `seen`/`result`. The domain path uses `_dseen`/`_dres` to avoid redeclaration warnings from static analysis tools.

## P0 — Provenance Completeness (Jul 2026)

**Experiment**: Does constraint inheritance reduce to provenance traversal?

**Result**: **Confirmed.** `collect_inherited_constraints()` (`studyplan/provenance/kernel/primitives.py:10`) is a generic BFS that follows output→input edges and unions constraints. It contains zero domain-specific knowledge. It works identically for FM and PostgreSQL:

- `collect_inherited_constraints(WACC_posttax)` → CAPM's `market_efficiency`, `diversified_investor`, WACC's `constant_capital_structure`, and 4+ inherited consumption constraints
- `collect_inherited_constraints(plan_tree_geqo)` → `("activation", "join_count > 12")` from the GEQO generator
- `collect_inherited_constraints(nestedloop_node)` → `("condition", "cost(nested_loop) < cost(hash_join)")` from the decision mapping
- `collect_inherited_constraints(Rf)` → empty (base artifact, no ancestors)

**Headline**: The failures occurred at the composition layer, not the ontology layer. All three FM gaps reclassified:

| Gap | Initial classification | After protocol | Action |
|-----|----------------------|----------------|--------|
| Multi-input T (WACC needs 4 inputs) | Ontology failure | Encoding failure (composition API, not ontology) | Deferred — wait for >1 FM example pushing same pressure |
| Closed EvaluationContext | Ontology failure | Implementation debt | Fixed (regimes open-ended) |
| Assumption propagation | Possible new primitive | Provenance query | **Provenance completeness** pattern promoted to kernel |

**Implication**: Tutor("What assumptions did I just make?") = Kernel(`collect_inherited_constraints(current_artifact)`) — no new ontology needed. The same code path serves Tutor, Debugger, and Lab.

**Two kinds of provenance discovered**: Execution provenance (graph reachability — "what does this depend on?") and validity provenance (constraint collection — "what must be true for this to be valid?"). Both are query strategies over one graph.

**Key files**: `studyplan/provenance/kernel/primitives.py` (collect_inherited_constraints), `studyplan/provenance/kernel/test_p0_provenance_completeness.py` (10 tests).

**Test status**: 10/10 pass on standalone, 2880/2880 full suite.

## P1 — ArtifactStore Protocol (Phase II, Jul 2026)

**Hypothesis**: ViewState is a complete snapshot — serialization captures all algebra-relevant state. A persistent store can be a pure IO layer with zero kernel changes.

**Predictions**: ViewState immutable, algebra APIs unchanged, cross-session queries work, no ontology changes, tutor code becomes simpler.

**Experiment**: Implement the smallest ArtifactStore — directory of JSON files, keyed by content_hash, zero in-memory cache, zero indexing, zero schema versioning.

**Results**: All 5 predictions **confirmed**. Zero falsifications (no domain-specific workarounds, no kernel imports beyond types, no schema migration).

**Key evidence**:
- `save(pg_vs) → load(key) → projection/loaded_vs` produces identical results to original
- `content_hash` preserved across serialization
- Same store works for PG optimizer and FM WACC domains
- Recursive serialization is purely structural (dataclass fields → dict, frozenset → list). Only one type of impedance: JSON converts tuples to lists, requiring list→tuple conversion on reconstruction for hashable fields (metadata, constraints). This is JSON's limitation, not ViewState's.

**Unexpected discovery**: Python's `dataclasses.asdict` does not recurse into `frozenset` members. Had to write `_to_json_compat()` — a structural recursive converter with zero domain knowledge.

**Implication**: The kernel has a clean architectural boundary. Storage is a decorator, not an intrinsic capability. The same store pattern can back Tutor, Debugger, Lab from a single code path.

**Key files**: `studyplan/provenance/experiments/experiment_artifact_store.py` (experiment protocol + store implementation), `studyplan/provenance/kernel/test_p1_artifact_store.py` (12 tests).

**Test status**: 12/12 pass on standalone, 2892/2892 full suite.

### Phase II protocol (Construction experiments)

The research protocol has graduated from discovery to construction. Every implementation decision is now a hypothesis:

| Phase | Question | Output |
|-------|----------|--------|
| Discovery (Phase I) | What architecture exists? | PV phase diagram, frozen schema v3 |
| Construction (Phase II) | What is the minimal implementation that satisfies the architecture? | Auditable code with research lineage |

Every new component requires: hypothesis → predictions → experiment → evidence → decision. Nothing bypasses evidence — not even implementation.

**Construction experiment types**:
- **Discovery**: What is true? (Output: architecture)
- **Construction**: Is this implementation minimal? (Output: code)

**Next candidate**: Multi-input composition. Hypothesis: unary transformations compress all observed domains (LLVM, PostgreSQL, GUI, FM WACC). Deferred until second FM example (NPV) pushes the same pressure.

## Identity System v2 — Semantic Normalization Layer (Jul 2026)

**Problem**: Identity resolution was per-build (transient DSU). Cross-source merging (FM+Notes) worked via string equality, but would break when PDF textbooks, exam marking schemes, or multi-author corpora are added.

**Solution**: Four-component identity system mirroring LLVM's global value numbering + canonicalization:

| Component | File | Role |
|-----------|------|------|
| `ProvenanceWeightedIdentity` | `identity_v2.py:25` | Identity with confidence, source_trust, lineage, effective_confidence |
| `SemanticEquivalenceScorer` | `identity_v2.py:95` | Weighted similarity (label 0.40 + type 0.25 + context 0.20 + provenance 0.15) |
| `GlobalIdentityRegistry` | `identity_v2.py:265` | Persistent identity graph across compilations — register/resolve/get_equivalence_class |
| `ConflictAwareMerger` | `identity_v2.py:340` | Wraps CIRMerger with GIR for principled identity resolution |

**Scoring calibration** (threshold=0.6):
- Same label + same type → 0.65 → merge ✓ (no context needed)
- Same label + compatible type → 0.575 → no merge (needs context)
- Same label + compatible type + context overlap → 0.775 → merge ✓

**Key design decisions**:
- Cross-type identities (formula vs concept) do NOT merge without contextual overlap — prevents over-merging
- `GlobalIdentityRegistry._find_best_match()` uses scorer.equivalence_threshold — no hardcoded cutoffs
- `register()` uses `_resolve_type_conflict()` with priority order: formula > principle > method > theorem > concept
- `ConflictAwareMerger._rewrite_fragments()` rewrites all fragment IDs to canonical before structural merge

**Test status**: 90 compilation tests pass (63 old + 27 new). 3658 total / 1 skip.
