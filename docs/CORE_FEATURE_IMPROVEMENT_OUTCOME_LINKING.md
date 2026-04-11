# Core feature improvement: Outcome–question linking and coverage

This document plans a **core feature improvement** focused on making syllabus outcomes the backbone of quiz coverage, coaching, and insights. Accurate outcome–question links improve Outcome Mastery, Coach Pick (weak areas), and Tutor context.

---

## 1. Goals

| Goal | Success criteria |
|------|------------------|
| **Accurate coverage** | Outcome Mastery and per-chapter/per-capability stats reflect only questions that resolve to at least one syllabus outcome; unlinked questions are visible and fixable. |
| **Explicit tagging** | Users (or import/AI) can assign outcome ids to questions; tagged questions drive coverage without relying on semantic fallback. |
| **Visibility** | Per-chapter and global “questions with outcome links: N / M” plus a way to see and fix unmapped questions. |
| **Stable resolution** | Resolution order (explicit → semantic → deterministic) is documented; schema and validation support `outcome_ids` / `outcomes` so exports and imports preserve links. |

---

## 2. Current state

- **Engine**: `resolve_question_outcomes(chapter, idx)` returns `outcome_ids` using: (1) `question.outcome_ids`, (2) `question.outcomes` (id or text match), (3) capability + semantic match, (4) deterministic bucket. Coverage (`outcome_stats`) updates only when at least one outcome_id is resolved.
- **Schema**: `module_schema.json` does not yet document per-question `outcome_ids` / `outcomes`. Question banks live in `questions.json` (per module), not in module config.
- **Reconfig**: Module → Reconfigure from RAG now fills `syllabus_structure`, `syllabus_meta`, `capabilities`, `unmapped_chapters`; it does not touch question banks.
- **Gap**: Many questions have no explicit tags; coverage depends on semantic/deterministic resolution, which can be wrong. No UI to assign or review outcome links.

---

## 3. Phases

### Phase 1: Schema and documentation (low risk)

- **Schema**
  - In `module_schema.json` or a dedicated question-bank schema note: document that each question object may include:
    - `outcome_ids`: array of strings (exact outcome ids from `syllabus_structure.<chapter>.learning_outcomes[].id`).
    - `outcomes`: array of objects `{ "id": "...", "text": "..." }` for backward compatibility and semantic matching.
  - Keep both optional so existing banks remain valid.
- **Docs**
  - In `USER_GUIDE.md` or `DEVELOPER_DOC.md`: add a short section “Outcome coverage” explaining that only questions linked to syllabus outcomes (by `outcome_ids` or resolved via `outcomes`/semantic/fallback) count toward covered outcomes; unlinked questions do not affect coverage.
- **Persistence**
  - Ensure `add_question` / save path for `questions.json` preserves `outcome_ids` and `outcomes` when present (no strip on save).

**Deliverables**: Schema description or comment; doc section; quick test that saving a question with `outcome_ids` round-trips.

---

### Phase 2: Resolution quality and diagnostics (medium risk)

- **Stability**
  - Keep current resolution order; optionally add a small “resolution source” flag in engine (e.g. `explicit` | `semantic` | `capability` | `deterministic`) so UI or exports can show “tagged vs inferred”.
- **Diagnostics**
  - Engine or app: compute per-chapter and global counts:
    - “Questions with at least one resolved outcome”: N.
    - “Total questions”: M.
    - Optional: “Questions with explicit outcome_ids”: K (subset of N).
  - Expose in a lightweight way: e.g. Module Editor footer, or Tools → “Outcome coverage summary”, or Insights tab.

**Deliverables**: Counts available (engine method or app panel); no change to existing resolution behaviour unless we add the “source” flag.

---

### Phase 3: Assign outcome tags in the UI (medium effort)

- **Where**
  - Best fit: **Module Editor** when editing a module (already has access to `syllabus_structure` and question bank), or a dedicated “Question bank” / “Edit questions” flow that shows questions per chapter.
  - Alternative: from **Quiz** or **Insights** via “Edit question” that opens a small dialog with chapter’s learning outcomes.
- **Behaviour**
  - For a selected question, show the chapter’s `learning_outcomes` (id + short text or full text).
  - Multi-select or dropdown to assign one or more outcome ids → write to `question.outcome_ids` (and optionally sync `outcome.outcomes` for backward compatibility).
  - Save updates `questions.json` (and optionally trigger a lightweight refresh of `outcome_stats` / coverage).
- **Scope**
  - Start with “assign outcome tags when editing a question” in one place (e.g. Module Editor question list, or Section C / question-stats export flow that links to “Edit question”). Expand to “bulk assign by chapter” later if needed.

**Deliverables**: One UI path to assign `outcome_ids` to a question and persist to `questions.json`; coverage reflects new tags after next answer or refresh.

---

### Phase 4 (optional): AI-assisted outcome tagging

- **Idea**
  - For questions that have no `outcome_ids`, run a single LLM call (or batch) with question text + chapter’s learning outcomes → suggest outcome ids; user confirms or edits before save.
- **Place**
  - “Suggest outcomes” button next to the outcome multi-select in the same UI as Phase 3; or a batch “Suggest links for unmapped questions” in Module Editor / Tools.
- **Guardrails**
  - Schema-bound output (list of outcome ids); validate ids against `syllabus_structure`; do not auto-save without user confirmation.

**Deliverables**: Optional “Suggest outcomes” that proposes links; user applies or discards.

---

## 4. Implementation order

1. **Phase 1** — Schema + docs + persistence check. Unblocks clear contract and safe save.
2. **Phase 2** — Diagnostics (N/M counts, optional resolution source). Unblocks visibility without new UI for editing.
3. **Phase 3** — Assign outcome tags in UI. High impact for accuracy.
4. **Phase 4** — Optional AI-assisted suggestions. Nice-to-have.

---

## 5. Dependencies and risks

| Item | Mitigation |
|------|------------|
| Question bank lives in `questions.json`, not in module config | All assignment UI reads/writes `questions.json` via engine (e.g. `add_question` or a dedicated “update question outcome_ids” path). Module Editor already has engine and module_id. |
| Large question banks | Phase 3 can start with “one question at a time”; bulk suggest (Phase 4) can be limited to a chapter or first N unmapped. |
| Resolution order change | Phase 2 keeps current order; only add optional “source” for diagnostics. No behaviour change for coverage calculation. |
| Backward compatibility | Schema and engine already accept missing `outcome_ids`/`outcomes`; resolution falls back to semantic/deterministic. No breaking change. |

---

## 6. References

- **MODULE_RECONFIG_PLAN.md** — §3 Question–outcome linking (point 3); §4 schema.
- **studyplan_engine.py** — `resolve_question_outcomes`, `outcome_stats`, `_chapter_outcome_lookup`, `_semantic_best_outcome_match`.
- **module_schema.json** — `syllabus_structure`, `learning_outcomes` (id, text, level).
- **RAG_AND_MODULE_IMPROVEMENTS.md** — Canonical structure mapping (outcome id stability, chapter alignment).
