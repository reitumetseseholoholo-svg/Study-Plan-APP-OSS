# Chapters derived from syllabus RAG

When the module config has **no chapters** (or empty), "Reconfigure from RAG" derives a chapter/section list from the **text already loaded in RAG** from your PDFs. The app does not fetch or parse Study Hub, BPP, or Kaplan separately — it uses whatever text came from the PDFs you added (e.g. in Preferences → AI Tutor → Tutor RAG PDFs, or from Import Syllabus PDF).

## What we actually derive

- **Source of text**: Concatenation of all RAG chunk text from those PDFs. So the "syllabus" RAG is whatever you added: ACCA official syllabus PDF, BPP study text, Kaplan, Study Hub, or a mix.
- **How we get chapter titles**:
  1. **Regex (no LLM)**  
     - **ACCA-style**: After a line like "4. The syllabus", we take single-letter section headings and short titles (e.g. `A. Financial management function`, `B. Financial management environment`) and numbered lines like `1. The nature and purpose of financial management`. We skip long "capability" lines from section 2 (e.g. `A. Discuss the role and purpose of the financial management function`).  
     - **Chapter/Part style**: Lines like `Chapter 1: Title` or `Part 1: Title` (common in BPP/Kaplan books).  
     - **Numbered sections**: `1. Title`, `2. Title` (with sensible length so we don’t treat outcome lines like `a) Explain...` as chapters).
  2. **LLM fallback**: If regex finds nothing (e.g. unusual layout or provider-specific headings), we ask the LLM to list the main section/chapter titles from the excerpt and use that list.

So the **chapters we drive from syllabus RAG** are exactly those we can detect with the above rules (or the LLM) in the **text extracted from your RAG PDFs**. We do not have separate logic for "Study Hub" vs "BPP" vs "Kaplan"; their structure only affects what headings appear in the extracted text and whether our regex or LLM can turn them into a clean list.

## Summary

| Source of RAG text | What typically gets derived |
|-------------------|-----------------------------|
| ACCA official syllabus PDF | Section 4 "The syllabus" headings (A. …, B. …, …) and numbered subsections (1. …, 2. …, …); sometimes also meta lines like "2. Main capabilities" if they match the patterns. |
| BPP / Kaplan / Study Hub PDFs | Whatever matches "Chapter N: Title", "Part N: Title", or short "A. Title" / "1. Title" in the extracted text; otherwise the LLM fallback can return their section list. |

So: **we don’t drive chapters from Study Hub / BPP / Kaplan as distinct sources** — we derive them from the **syllabus RAG text** that came from whatever PDFs you added (which may be ACCA, Study Hub, BPP, Kaplan, or a mix).
