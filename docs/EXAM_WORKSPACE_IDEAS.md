# Exam-style workspace & academic enhancements

Ideas for improving tutor–student interaction with spreadsheet and word-processing, and for making the app stronger in the academic scene. Nothing here is implemented yet; this is a design and prioritization note.

---

## 1. What you asked for: Gnumeric & AbiWord

### 1.1 Embedding vs launching

- **Embedding** (Gnumeric/AbiWord as widgets inside the app):
  - **AbiWord**: Old PyAbiWord (GTK 2) allowed embedding a Canvas; bindings are likely unmaintained and not GTK4.
  - **Gnumeric**: Python API is for *extending* Gnumeric (plugins), not embedding a sheet in another window.
  - **Verdict**: True embedding is fragile or not feasible with current stacks. Not recommended as first step.

- **Launching** (open Gnumeric/AbiWord in a separate window with a temp file):
  - Create a temp `.gnumeric` / `.abw` (or CSV for spreadsheet, RTF for word).
  - Launch `gnumeric /path/to/file` and `abiword /path/to/file` via `subprocess` (or `Gio.AppInfo.launch_default_for_uri`).
  - Optionally: “Import from file” to read back and paste into the in-app answer area.
  - **Verdict**: Easy to add, no extra UI complexity, uses real exam-like tools. Good first slice.

### 1.2 What we can implement (recommended order)

1. **“Open in spreadsheet” / “Open in word processor”**
   - In **Section C practice** and/or **Practice Loop**: add buttons (e.g. “Open in Gnumeric”, “Open in AbiWord”).
   - Create a temp file (empty or pre-filled with question text / template), launch the app, optionally show a short hint: “When done, copy back into the answer box or use Import from file.”
   - **Import from file**: “Import from spreadsheet” (e.g. read CSV/plain text) and “Import from document” (e.g. read .abw/.txt/RTF) and paste into the current answer `Gtk.TextView` (or future workspace).

2. **Lightweight in-app “exam workspace” (no Gnumeric/AbiWord dependency)**
   - **Spreadsheet pane**: Simple grid (e.g. `Gtk.Grid` of `Gtk.Entry` or `Gtk.GridView`) with copy/paste and optional basic formulas (e.g. `=SUM(A1:A5)`) via a small expression evaluator.
   - **Document pane**: Rich(er) text in-app: existing `Gtk.TextView` + toolbar (bold, italic, list, heading) and tags; optional “Copy as RTF” or “Export as RTF”.
   - **Persistence**: Save workspace state per question (e.g. grid as JSON + text buffer) so revisiting a question restores the student’s draft.
   - This gives a single-window, exam-like experience without requiring Gnumeric/AbiWord installed.

3. **Hybrid**
   - In-app minimal grid + rich text (as above) for quick use and per-question persistence.
   - Plus “Open in Gnumeric” / “Open in AbiWord” that export current in-app state to a temp file, launch the external app, and “Import from file” to bring content back.

---

## 2. Where to plug it in

- **Section C practice dialog** (`_open_section_c_practice_dialog`): main place for constructed response. Add:
  - Optional “Exam workspace” (tabs or split: **Document** | **Spreadsheet**), or a single answer area with “Open in spreadsheet” / “Open in word” buttons.
  - Per-question (or per-case) save/restore of workspace content.
- **Practice Loop** (Tutor tab): the “Practice Loop” answer box could get:
  - Same “Open in Gnumeric/AbiWord” actions and, later, an optional embedded grid + rich-text workspace.
- **Quiz flow**: if we add longer constructed responses in quiz, the same workspace or “Open in…” actions could be reused.

---

## 3. Other academic enhancements (beyond workspace)

- **Exam-style templates**
  - Spreadsheet: pre-loaded layouts (e.g. income statement, ratio table, cash flow skeleton) for Section C.
  - Document: report structure (heading/subheadings) or “answer (a)/(b)/(c)” template.
- **Timed practice**
  - Optional timer for Section C (e.g. 20–30 min) with workspace available; optional auto-submit or warning when time is low.
- **Export for marking / self-review**
  - Export question + model answer + student’s spreadsheet + student’s document (e.g. PDF or ZIP) for offline review or tutor feedback.
- **Tutor awareness of workspace**
  - When giving hints, tutor could reference “your spreadsheet” or “your document” (e.g. “You have three points in your document; try adding a comparison with the standard”) if we pass a short summary or key figures into the tutor context.
- **Calculation scratchpad**
  - Dedicated numeric scratchpad (could be the same spreadsheet pane or a small calculator-style panel) for workings.
- **Word count / spell-check**
  - For the document pane: word count and optional spell-check (e.g. GtkSpell or Enchant) to mirror exam software.
- **Accessibility**
  - Keyboard navigation and screen-reader friendly labels for workspace and “Open in…” actions.

---

## 4. Suggested implementation order

| Priority | Item | Effort | Notes |
|----------|------|--------|--------|
| 1 | “Open in Gnumeric” / “Open in AbiWord” in Section C (and optionally Practice Loop) with temp file + “Import from file” | Low | Reuses existing `subprocess`/Gio patterns; no new UI widgets. |
| 2 | Per-question (or per-case) save/restore of Section C answer text (and later workspace) | Low–Medium | Persist to module dir or user data; restore when reopening same question. |
| 3 | In-app minimal spreadsheet (grid + optional formulas) + optional “Document” tab in Section C | Medium | No external deps; single-window exam feel. |
| 4 | Exam-style templates (spreadsheet + document) | Medium | Templates as static files or built-in defaults. |
| 5 | Timed practice mode for Section C | Low–Medium | Timer + optional auto-submit/warning. |
| 6 | Export for marking (question + model answer + student doc/sheet) | Medium | PDF or ZIP generation. |
| 7 | Tutor context: “your document/spreadsheet” summary in hints | Medium | Requires passing workspace summary into tutor prompt. |

---

## 5. Summary

- **Gnumeric/AbiWord**: Best approach is **launch** with temp files + **Import from file**, not embedding. We can add “Open in Gnumeric” and “Open in AbiWord” in Section C (and Practice Loop) and optionally pre-fill/import from file.
- **In-app exam workspace**: A **minimal spreadsheet grid** and **rich-text document** pane, with per-question persistence, would improve the academic feel without depending on external apps; can be added after or alongside the “Open in…” actions.
- **Academic scene**: Templates, timed practice, export for marking, tutor awareness of workspace, scratchpad, and word count/spell-check are all implementable and would strengthen the app for exam prep and tutor–student interaction.
