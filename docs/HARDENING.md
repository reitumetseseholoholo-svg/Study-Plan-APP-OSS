# App hardening guide

Ways to harden the Study Plan app further, building on the 50-iteration bug hunt and syllabus/UI guards.

## Already in place

- **Engine guards:** Module/syllabus/Tools handlers check `engine` before use; “engine not ready” instead of crash.
- **Input safety:** `_sanitize_module_id` (alphanumeric, `_`, `-` only); file size limits for data/snapshot/import; JSON/YAML/OSError wrapped in module_chapters and script.
- **RAG:** Bytes from PDF decoded with `errors="replace"`; chunk list built only from `isinstance(c, dict)` entries.
- **Index/Key:** `rows_by_bucket.get(0)`, empty topics/overdue handled; empty CHAPTERS guarded in UI.
- **Lifecycle:** GLib sources registered and drained on close; progress dialogs destroyed in try/except in idle_add.
- **File I/O:** `studyplan_file_safety` (size limit, path checks); engine uses `with open` and size limits.

---

## 1. Path and filesystem (high value)

- **User-supplied paths:** Any path coming from file chooser, CLI, or config (e.g. RAG PDFs, export path, `source_pdf`) should be normalized and validated before open/write.
  - Use `os.path.abspath(os.path.normpath(os.path.expanduser(p)))` and ensure the result is under an allowed base (e.g. `CONFIG_HOME`, chosen dir, or a whitelist).
  - Reject paths that escape (e.g. `..` outside allowed tree) or point at directories when a file is expected.
- **Write targets:** Prefer writing under `CONFIG_HOME` or a dedicated app dir; avoid overwriting system or arbitrary user paths; create dirs with `exist_ok=True` and restrictive permissions where appropriate (already done for some paths).
- **Optional:** Add a small `validate_path_under(base, path)` (or use a library) and use it for export, snapshot, and RAG/config paths.

---

## 2. Startup and shutdown (high value)

- **Startup:** If engine init fails (e.g. bad data file), show a clear message and optional “Reset data” / “Open config folder” instead of traceback. Already: snapshot recovery and load error handling; ensure the first window still shows a safe state when load fails.
- **Shutdown:** Ensure `save_preferences` and engine `save_data` complete before process exit (or document that we accept last-write loss). Avoid starting a save then exiting immediately; consider a short “quitting” state that waits for in-flight writes (with timeout).
- **Lock file:** Single-instance lock under `CONFIG_HOME`; on failure to acquire, show “Another instance may be running” and exit cleanly (no crash).

---

## 3. Data and schema (medium value)

- **Loaded JSON:** Keep normalizing and validating in `_apply_loaded_payload` / `_normalize_loaded_data`; add or extend schema checks for critical keys (e.g. `CHAPTERS` list, `QUESTIONS` dict shape) and log or coerce invalid values instead of assuming shape.
- **Version bumps:** When adding migrations (e.g. new schema_version), run them in a defined order and guard with try/except so one bad migration doesn’t break load; document in BUG_HUNT / this doc.
- **Snapshot import:** Already size-limited; consider checksum or basic integrity check (e.g. required keys present) before applying.

---

## 4. UI and GTK (medium value)

- **Widget lifecycle:** Before calling methods on widgets after timeouts or idle_add, check `widget.get_root()` or “is destroyed” if GTK supports it, or wrap in try/except so destroyed widgets don’t crash the main loop.
- **Dialogs:** Prefer one-shot dialogs (create → present → response → destroy) and avoid reusing the same dialog instance after destroy. Already using try/except around progress_d.destroy() in several places; extend pattern where dialogs are closed from workers.
- **Long operations:** Keep “progress dialog + worker thread + idle_add to close” pattern; ensure worker never touches GTK objects and that UI updates only happen on main thread.

---

## 5. External inputs and encoding (medium value)

- **PDF/text:** RAG path already decodes bytes with `errors="replace"`. Apply the same idea anywhere else raw bytes might appear (e.g. other PDF text extraction, pasted text) so non-UTF-8 doesn’t raise.
- **Network/APIs:** If you add HTTP or Ollama calls, use timeouts, size limits, and try/except; don’t trust response shape without validation.
- **Preferences/config:** When reading from env or config files, coerce types and clamp ranges (already done in several places); keep a single place that defines defaults and limits.

---

## 6. Observability and safety nets (lower priority)

- **Structured logging:** Use a single logger (e.g. `studyplan` or per module) and log key events (load/save, module switch, reconfig, errors) with levels so production issues are easier to diagnose.
- **Health endpoint or self-check:** Optional; e.g. a “Data health check” that validates engine state, file presence, and schema without modifying data (already partially there); expose result in UI or log.
- **Graceful degradation:** When optional features fail (e.g. semantic, LLM), disable only that feature and show a short message instead of crashing the app.

---

## 7. Security (basics)

- **Secrets:** No API keys or passwords in repo or logs; use env or keychain if needed. Already using env for flags (e.g. `STUDYPLAN_SMOKE_MODE`).
- **Permissions:** Keep using `secure_path_permissions` for sensitive dirs/files; avoid world-writable paths for data and config.
- **Module ID:** `_sanitize_module_id` already prevents path traversal in module paths; keep using it for any path derived from module_id.

---

## Implemented (recent)

1. **Path validation** – `studyplan_file_safety.validate_path_under(base_dir, path, must_be_file=..., must_exist=...)` ensures the resolved path is under `base_dir` (no `..` escape). Used in `_load_ai_tutor_rag_doc`: RAG PDF paths must be under user home or `Config.CONFIG_HOME`. Export/import already use `studyplan_app_path_utils` (under home, /tmp, or /media).
2. **Startup on load failure** – In `StudyPlanEngine.__init__`, when `load_data()` raises, the engine sets `_load_failed = True` and `_load_error = str(e)`. The app shows a one-time dialog with “Data load failed”, the error message, and buttons: **Open config folder**, **Retry load**, **Continue with empty data**. Retry calls `engine.load_data()` again and clears the flag on success.
3. **Shutdown** – In `on_close_request`, the app now calls `save_preferences()` then `engine.save_data()` (with an engine guard) before scheduling exit, so both writes complete before quit.

## Suggested order of work (remaining)

1. ~~**Path validation**~~ – Done.
2. ~~**Startup/shutdown**~~ – Startup dialog and shutdown save order done; lock file message already present.
3. **Data/schema** – Tighten validation in load and snapshot apply; document migration order (1 day).
4. **UI lifecycle** – Audit timeout/idle_add callbacks that touch widgets; add “is valid” checks or try/except where needed (ongoing).
5. **Encoding and external input** – Apply bytes→str with `errors="replace"` anywhere else raw bytes can appear; add timeouts/size limits for any new network code (as you touch those paths).

---

## References

- Bug hunt: `docs/BUG_HUNT_50_ITERATIONS.md`
- Syllabus/UI: `docs/BUG_HUNT_SYLLABUS_AND_UI_BUTTONS.md`
- File safety: `studyplan_file_safety.py`
- Engine load/save: `studyplan_engine.load_data`, `_apply_loaded_payload`, `_normalize_loaded_data`
