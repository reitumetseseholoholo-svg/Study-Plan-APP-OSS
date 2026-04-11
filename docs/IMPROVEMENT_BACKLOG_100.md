# 100 improvements (backlog)

Prioritized list of small-to-medium improvements. Implemented items are marked [done]. Order is by category then impact.

## Code quality & consistency

1. [ ] Replace bare `except Exception` with `except Exception as e` and log in engine (non-critical paths)
2. [ ] Add type hints to all public functions in `studyplan/module_reconfig/reconfig.py`
3. [done] Extract magic numbers (e.g. 900, 1200 chunk sizes) to named constants in RAG chunking
4. [ ] Use `None` checks via `is None` / `is not None` consistently (audit)
5. [done] Add docstrings to all exported functions in `action_registry.py`
6. [ ] Normalize string quotes (single vs double) in new code to project style
7. [ ] Remove redundant `.strip().strip()` or double strips if any
8. [done] Add module-level docstring to `studyplan_engine.py` (one-line purpose)
9. [done] Consolidate duplicate "Engine not ready" / "No module" dialog copy into helpers
10. [done] Add `__all__` to `studyplan/module_reconfig/__init__.py`

## UX & copy

11. [done] QUICK_START: add Outcome coverage / View Module Metadata hint
12. [done] USER_GUIDE: add "Outcome coverage" subsection under Module/syllabus
13. [ ] Standardize dialog titles (e.g. "Reconfigure from RAG" vs "Module" for success)
14. [ ] Add tooltip to "View Module Metadata" button/menu: "See module config, paths, and outcome–question linking stats"
15. [ ] Add tooltip to "Import Syllabus (JSON)": "Seed syllabus_meta from a JSON file to reduce AI work in Reconfigure from RAG"
16. [done] Empty state when no RAG PDFs: suggest "Add PDFs in Preferences → AI Tutor → Tutor RAG PDFs"
17. [done] Coach Pick empty state: more specific "Set exam date and load questions" when both missing
18. [done] Replace "(none)" with "(not set)" in metadata views for consistency
19. [ ] Notification title consistency: "Module" vs "Syllabus" vs "Reconfigure" for related actions
20. [ ] Add "What's this?" or help link next to Exam Readiness Index in Briefing

## Accessibility & shortcuts

21. [ ] Ensure all icon-only buttons have accessible names (Gtk.Accessible)
22. [done] Add mnemonic to "Import Syllabus (JSON)…" (e.g. Import Syllab**u**s (JSON))
23. [ ] Verify focus order in Module Editor (tab through fields logically)
24. [ ] Add Ctrl+Shift+M or similar for "View Module Metadata" if high value
25. [ ] Ensure Pomodoro timer has live region for screen readers

## Documentation

26. [done] DEVELOPER_DOC: Outcome coverage and question bank schema
27. [done] README: add one line linking to outcome-linking improvement plan
28. [done] FEATURES: add "Outcome coverage diagnostics (Module → View Module Metadata)"
29. [done] module_schema.json: document `syllabus_meta.unmapped_chapters`
30. [done] Add docstring to `get_outcome_coverage_counts()` (already has one; verify)
31. [done] USER_GUIDE: add "Module → Import Syllabus (JSON)" to module section
32. [done] DEVELOPER_DOC: add "Outcome coverage" to Data and paths subsection index
33. [done] QUICK_START: add "Module → View Module Metadata" under Data locations
34. [done] In-code comment at `resolve_question_outcomes` summarizing resolution order
35. [done] RAG_AND_MODULE_IMPROVEMENTS: mark completed items

## Performance & resources

36. [ ] Cap RAG chunk cache size (LRU) when over N chunks or M MB
37. [ ] Defer loading question quality meta until first quarantine check
38. [ ] Lazy-load syllabus_structure in engine only when outcome lookup needed
39. [ ] Consider caching `get_outcome_coverage_counts()` for same session (invalidate on question load)
40. [ ] Batch outcome resolution in coverage counts if engine supports (already single-pass; keep)

## Tests & robustness

41. [done] test_sanitize_question_bank_row_preserves_outcome_ids_and_outcomes
42. [done] test_get_outcome_coverage_counts_returns_shape
43. [done] Test that add_question round-trips outcome_ids to JSON
44. [done] Test reconfigure_from_rag sets unmapped_chapters
45. [done] Test import_syllabus_meta_from_json with only syllabus_meta
46. [done] Add test for _extract_syllabus_meta returning empty when no LLM
47. [done] Test validate_syllabus_structure with invalid level (e.g. 4)
48. [ ] Engine: test load_questions with chapter key alias (e.g. raw key → CHAPTERS key)
49. [done] Test get_outcome_coverage_counts with mix of explicit and resolved
50. [done] Test that save_questions does not drop outcome_ids

## Module & syllabus

51. [done] Validate outcome_ids in question bank against syllabus_structure on load (warn only; health check reports invalid count)
52. [done] Module Editor: show "Unmapped chapters" from syllabus_meta when present (View Module Metadata)
53. [done] Reconfigure from RAG: show unmapped_chapters in success dialog
54. [ ] Allow syllabus_meta.reference_pdfs to be editable in Module Editor (read-only display first)
55. [ ] Export module config to include unmapped_chapters in JSON
56. [ ] Import Syllabus JSON: option to "Merge with current" vs "Replace" for syllabus_meta
57. [done] Document expected shape of Import Syllabus JSON (one example in USER_GUIDE)
58. [done] Reconfig: log confidence and outcome count to app log when below threshold
59. [done] Add "Copy module path" button in View Module Metadata
60. [done] Module list: show question count per module in Manage Modules

## Tutor & AI

61. [done] Tutor: when no model selected, show "Choose a model in Preferences → AI Tutor"
62. [ ] Gap questions: show "0 questions" reason when quarantine or limit hit
63. [done] Section C: add tooltip to "Use in prompt" explaining what gets pasted
64. [done] Coach: if no recommendation, show "Complete a quiz or set exam date to get recommendations"
65. [ ] RAG diagnostics: show "Chunks from syllabus vs other" split
66. [ ] Tutor chat: persist "concise mode" in session or preferences
67. [ ] Assessment judge: surface "low confidence" in UI when score &lt; 0.6
68. [ ] Add retry button to failed LLM calls in reconfig
69. [done] Tutor: suggest "Add RAG PDFs for better context" when RAG list empty
70. [ ] Parse and show LLM token usage in debug or Insights when available

## Data & recovery

71. [ ] Snapshot export: include outcome_coverage summary in metadata
72. [done] Health check: report questions with invalid outcome_ids (not in syllabus)
73. [done] Backup: add questions.json to backup list if not already
74. [done] Recovery: show "Last snapshot: <date>" in Recover dialog
75. [done] Data locations in About: add "Outcome coverage: Module → View Module Metadata"
76. [ ] Validate preferences.json schema on load (optional strict mode)
77. [done] Import template: add optional column "outcome_ids" with hint
78. [done] Export CSV: add outcome_ids column when present (question stats export)
79. [done] Weekly report: add line "Questions with outcome links: N/M"
80. [ ] Clear syllabus cache: also clear reconfig confidence cache if any

## UI polish

81. [ ] Reduce flicker when switching Dashboard/Insights tabs
82. [done] Study Room: align "Focus now" and "Quick quiz" button widths
83. [ ] Module metadata dialog: make "Outcome coverage" section collapsible if long
84. [done] Add subtle border or spacing between Mission checklist items
85. [done] Pomodoro: show "Paused" in title when paused
86. [done] Preferences: group "AI Tutor" and "Tutor RAG PDFs" under one heading
87. [done] Insights: add "Outcome coverage" card linking to View Module Metadata
88. [ ] Status bar: truncate long module title with ellipsis
89. [done] Dialog default sizes: set min width for View Module Metadata
90. [ ] High contrast: ensure outcome coverage section is readable

## Security & safety

91. [done] Sanitize file paths in "Import from file" to prevent path traversal
92. [done] Limit size of pasted content in tutor prompt (e.g. 50k chars)
93. [done] Validate module_id format before writing to disk (alphanumeric + underscore)
94. [ ] Do not log full RAG PDF paths in production log level
95. [ ] Snapshot import: reject files over N MB without confirmation

## Internationalization & locale

96. [ ] Extract all user-facing strings to a messages module (future i18n)
97. [ ] Use locale-aware number formatting for percentages (e.g. 75% vs 75 %)
98. [ ] Date format in dialogs: respect system locale
99. [ ] Ensure no hardcoded "AM/PM" where 24h is preferred in locale
100. [done] Add LANGUAGE or LOCALE note to DEVELOPER_DOC for contributors

---

*Implement in batches; mark items [done] when completed. Prioritize UX and docs for user impact.*
