# Bug hunt: Syllabus intelligence & UI buttons

Focused scan on syllabus-related flows and button handlers. Run these iterations after the general 50-iteration list.

## Syllabus intelligence (targets)

1. **Refresh syllabus intelligence**
   - Entry: `on_refresh_syllabus_intelligence` (menu + Tools → Module).
   - Guard: `engine` may be `None` when RAG paths are empty; guard before `engine._load_module_config` / `engine.import_syllabus_from_pdf_text` / `engine._apply_module_config`.
   - RAG path: delegates to `on_reconfigure_from_rag` (ensure that path also guards engine).
   - PDF re-parse: `_extract_pdf_text_for_syllabus(path)` and `engine.import_syllabus_from_pdf_text`; encoding errors, missing file already checked; worker→`idle_add` and progress dialog destroy in try/except.

2. **Reconfigure from RAG**
   - Entry: `on_reconfigure_from_rag` (menu, Insights button, auto-reconfig).
   - Guard: `engine` may be `None`; guard before `engine._load_module_config` and before any use of `engine` in apply path.
   - RAG load: `_load_ai_tutor_rag_doc(path)`; chunk `text` coerced to `str`; non-UTF-8 in chunk text can still raise in retrieval/LLM input.
   - Apply path: `engine._apply_module_config(merged)`; ensure engine is valid before apply.
   - Auto-reconfig: `_maybe_auto_reconfigure_from_rag` uses same flow; same engine guard.

3. **View Module Metadata**
   - Entry: `on_menu_view_module_metadata` / `_activate_view_module_metadata` (Insights “View Module Metadata” button, app action).
   - Already guards: `if engine is None: self._show_engine_not_ready(...)`.
   - `get_outcome_coverage_counts()` wrapped in try/except; `syllabus_meta` / `last_parse_empty_sections` accessed safely.

4. **Outcome coverage & suggestions**
   - `get_outcome_coverage_counts()` (engine): handles missing `outcome_stats`, `syllabus_structure`; division by zero guarded with `max(1, ...)`.
   - Metadata dialog “Suggestions”: hints when `syllabus_k` low, `linked_l ≪ syllabus_k`, or `last_parse_empty_sections`; no direct index/key assumed.

5. **Import Syllabus PDF**
   - Sets `syllabus_meta.source_pdf`; re-parse and apply flow similar to refresh; ensure engine and config paths guarded.

6. **Reconfig core (`studyplan.module_reconfig.reconfig`)**
   - `reconfigure_from_rag`: `config`/`chapters`/`chunks_by_path` assumed valid by caller; `syllabus_structure` defaulted; no bare index into empty lists in scanned paths.
   - Chunk text: `str(c.get("text", "") or "").strip()`; if chunk is not dict, `.get` could raise—callers build chunks from `doc["chunks"]` with dict check.

## UI buttons (targets)

1. **Syllabus/Module buttons**
   - “View Module Metadata”: `_activate_view_module_metadata` → `on_menu_view_module_metadata` (engine guarded).
   - “Reconfigure from RAG…”: `on_reconfigure_from_rag` (add engine guard).
   - “Refresh syllabus intelligence…”: `on_refresh_syllabus_intelligence` (add engine guard when no RAG path).
   - “Reload module configuration”: `on_menu_reload_module_config` (check for engine guard).
   - “Import Syllabus PDF”: locate handler and guard engine/config.

2. **Tools / Insights buttons**
   - “View Module Metadata” (Insights card): same as above.
   - “View Syllabus Cache Stats”, “Clear Syllabus Cache”: ensure they guard engine or handle missing engine without crash.
   - “Run Data Health Check”, “View Health Log”, “Import/Export”, “Reset Data”: ensure handlers catch or guard so a missing engine doesn’t raise.

3. **Study room / coach buttons**
   - “Focus now”, “Take quiz”, “Drill”, “AI coach”, etc.: many already use `_has_chapters()` or engine in try/except; confirm no unguarded `self.engine` before use in handlers that can run before engine is ready.

4. **Button handler pattern**
   - Prefer: at start of handler, `engine = getattr(self, "engine", None)` then `if engine is None: self._show_engine_not_ready("…"); return` (or equivalent) for any handler that calls `engine.*`.
   - Ensure `connect("clicked", ...)` callbacks don’t assume widget still valid if dialog/window can be destroyed (use try/except or check `widget.get_root()` if needed).

## Checklist (run order)

- [x] Refresh syllabus intelligence: engine `None` guard when no RAG path.
- [x] Reconfigure from RAG: engine `None` guard before load/apply.
- [x] View Module Metadata: already guarded; no change.
- [x] Reload module config: already has engine guard.
- [x] Import Syllabus PDF handler: engine guard at start of `on_import_syllabus_pdf`.
- [x] Syllabus cache / Health / Import–Export / Reset: engine guard added to `on_view_syllabus_cache_stats`, `on_clear_syllabus_cache`, `on_run_health_check`, `on_export_data`, `on_reset_data`, and `on_reset_confirm`.
- [x] Study room / coach buttons: spot-checked; `on_focus_now`, `on_quick_quiz`, `on_take_quiz`, `on_leitner_drill` use `_ensure_chapters_ready` / `_has_chapters()` (which catches when engine is None). No change needed.
- [x] Reconfig chunk building: only include `c` when `isinstance(c, dict)` before `c.get("text")`.

## Fixes applied (this pass)

- **Refresh syllabus intelligence:** Guard when RAG paths are empty: `engine = getattr(self, "engine", None)` then `if engine is None: self._show_engine_not_ready("Refresh syllabus intelligence"); return`.
- **Reconfigure from RAG:** Same engine guard at start of handler before `engine._load_module_config`.
- **Import Syllabus PDF:** Engine guard at start of `on_import_syllabus_pdf` so the file dialog is not shown if engine is not ready.
- **Reconfig chunk building:** In the RAG worker, only include items where `isinstance(c, dict)` when building `chunks_by_path[path]` from `doc["chunks"]`, so non-dict entries don’t cause `.get("text")` to raise.
- **Tools/Insights:** Engine guard at start of `on_view_syllabus_cache_stats`, `on_clear_syllabus_cache`, `on_run_health_check`, `on_export_data`, `on_reset_data`; guard in `on_reset_confirm` before `engine.reset_data()`.

## Tests added

- **tests/test_rag_and_reconfig_safety.py:** `test_reconfig_chunk_building_filters_non_dict`, `test_reconfig_chunk_building_empty_list`, `test_rag_bytes_coercion_to_str`.
- **tests/test_studyplan_app_ollama.py:** `test_load_ai_tutor_rag_doc_handles_bytes_from_extraction` (patch `_extract_pdf_text_for_syllabus` to return bytes; assert doc with chunks returned).

## Manual smoke checklist

Run the app, then quickly verify these (no crash, sensible message or dialog):

**Module menu**
- [ ] **View Module Metadata** – Opens metadata dialog; shows chapters, outcome coverage, paths, suggestions.
- [ ] **Reconfigure from RAG** – With no RAG PDFs: warning “No RAG PDFs available…”. With RAG: progress then apply/review flow.
- [ ] **Refresh syllabus intelligence** – With no RAG and no source PDF: warning “No RAG PDFs and no source PDF set…”. With source PDF: re-parse and apply flow.
- [ ] **Import Syllabus PDF** – File dialog opens; cancel is safe.
- [ ] **Reload module configuration** – Reloads current module or shows “No configuration file found” if none.

**Tools (left panel or overflow)**
- [ ] **View Syllabus Cache Stats** – Dialog with cache stats, or “engine not ready” if app started without module.
- [ ] **Clear Syllabus Cache** – Clears and shows before/after, or “engine not ready”.
- [ ] **Run Data Health Check** – Runs check and shows summary, or “engine not ready”.
- [ ] **Export data (CSV)** – Save dialog opens, or “engine not ready”.
- [ ] **Reset Data** – Confirm dialog; Yes runs reset or “engine not ready”.

**Insights (if using modern UI)**
- [ ] **View Module Metadata** button – Same as Module → View Module Metadata.

**Study room**
- [ ] **Focus now** / **Quiz 8** / **Drill weak** – With no module: “No study content loaded yet…”. With module: normal flow.

*Optional:* Close and reopen with no module loaded, then hit Tools buttons above; each should show “engine not ready” (or equivalent) instead of crashing.

## Test status

- Unit tests: `pytest -q` (including test_rag_and_reconfig_safety, test_load_ai_tutor_rag_doc_handles_bytes_from_extraction).
- Automated GUI: `xvfb-run -a timeout 180s python studyplan_app.py --dialog-smoke-strict` (CI or when xvfb installed).
- Manual: use the checklist above after fixes.
