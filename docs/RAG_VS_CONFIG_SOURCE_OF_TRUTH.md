# RAG vs module config as source of truth

## The question

What if we **build semantic / lexical maps directly from RAG** (syllabus + study guide chunks), **without touching module configs**? And which is better as source of truth: **module config** or the **RAG system**?

## Current architecture (short)

| Concern | Today’s source | Used for |
|--------|----------------|----------|
| Chapters, order, flow | Module config (`chapters`, `chapter_flow`) | Quiz routing, coach, UI, question bank keys |
| Syllabus structure (outcome IDs, text, level per chapter) | Module config (`syllabus_structure`) | Concept graph, outcome clusters, semantic matching, reporting |
| Semantic aliases (e.g. “ifrs 15” → chapter) | Module config (`semantic_aliases`) | Topic matching, coach, tutor context |
| Concept graph / outcome cluster graphs | Built **from** `syllabus_structure` (or loaded from config) | Semantic routing, drift, diagnostics |
| Tutor context at query time | **RAG** (chunks retrieved by query) | What the tutor “reads” from PDFs |

So today: **config is the source of truth for structure and for the graphs**; **RAG is the source of truth only for “what text to show the tutor”** when answering a question.

## Option A: Module config remains source of truth (status quo + small tweaks)

- **Chapters, outcomes, weights, aliases** live in module config (and F7 is “known by heart” from built-in).
- Concept graph and outcome clusters are **derived from** `syllabus_structure` (outcome IDs and text).
- RAG is used for: (1) tutor retrieval, (2) “Reconfigure from RAG” which **proposes** config updates (user applies → config is still truth).

**Pros:** Stable, exam-aligned structure (outcome IDs, levels); clear ownership of “canonical” chapters; works offline once config is loaded.  
**Cons:** Config can drift from what’s actually in the PDFs; any new provider (BPP, Kaplan, Study Hub) requires either manual config or a reconfig run that writes config.

---

## Option B: RAG as source of truth (build semantic/lexical maps from RAG only)

- **No** syllabus_structure / chapters in config for “RAG-driven” mode; or config is only a thin override.
- **Semantic/lexical maps** (concept graph, outcome clusters, term→topic maps) are built **directly from RAG chunks** (and optionally from chunk metadata if we add it).
- Chapters / sections could be **derived** from RAG (as we already do when config has no chapters) and not persisted to config; tutor and coach use RAG-derived structure and maps.

**Pros:** Single source of truth (the PDFs you added); works for any provider without maintaining JSON; always in sync with what’s in the docs.  
**Cons:** Chunk boundaries are arbitrary (may split topics); no stable outcome IDs unless we generate or attach them; harder to align to exam syllabus wording and levels; question bank and reporting are keyed by chapter/outcome today — we’d need another keying strategy or a “virtual” structure.

---

## Option C (recommended): Hybrid — config for structure, RAG for semantic/lexical maps

Keep **module config as source of truth for**:

- **Chapters** (order, flow) and **syllabus_structure** (outcome IDs, text, level) for exam alignment, reporting, question mapping, and stable coach/quiz behaviour.

Add **RAG-derived maps that do not touch config**:

- Build **semantic/lexical maps from RAG directly** (e.g. term graph, topic clusters, or embedding index over chunks) and use them **only** for:
  - **Retrieval**: better expansion and similarity (e.g. “WACC” → related terms from RAG).
  - **Tutor**: richer context and “explain like the study guide” without changing config.
  - **Optional**: suggest aliases or outcome text that the user can accept and then **write into config** (so config stays the canonical structure, but RAG informs it).

So:

- **Config** = source of truth for **structure** (chapters, outcomes, weights, aliases).
- **RAG** = source of truth for **lexical/semantic expansion and retrieval**; we build maps from it in memory (or in a separate cache/index), and we **do not** overwrite module config with those maps.

That way:

- We can build **semantic/lexical maps from RAG without touching module configs** — better retrieval and tutor behaviour.
- We avoid “which is source of truth?” by making them **complementary**: config = structure; RAG = content and similarity.

## Concretely: what “build maps from RAG directly” could look like

1. **Term / keyphrase extraction** from RAG chunks (e.g. noun phrases, exam terms); build a **term→chunk** or **term→topic** index. Use it for query expansion and tutor retrieval only (no config writes).
2. **Topic or “concept” clusters** from chunk embeddings or co-occurrence; use for “related topics” and tutor context, without replacing the concept graph built from `syllabus_structure`.
3. **Lexical map**: same as today’s retrieval (e.g. `retrieve_from_chunks_by_path`) but with an extra layer — e.g. expand query with RAG-derived terms before scoring chunks. Still read-only on config.
4. **Optional**: “Suggest outcomes/aliases from RAG” that **proposes** config changes (like Reconfigure from RAG) and only updates config when the user applies.

## Summary

| Approach | Structure (chapters, outcomes) | Semantic/lexical maps | Best when |
|----------|--------------------------------|------------------------|-----------|
| **Config only** (current) | Config | Built from config (syllabus_structure) | You want one canonical exam-aligned structure and minimal moving parts. |
| **RAG only** | Derived from RAG | Built from RAG | You want “whatever is in the PDFs” to drive everything; you accept less stable outcome IDs and reporting. |
| **Hybrid (recommended)** | **Config** (source of truth) | **Built from RAG** (read-only; no config writes) | You want stable structure and reporting **and** better retrieval/tutor behaviour from RAG, without config drift. |

So: **module config is better as source of truth for structure**; **RAG is better as source of truth for “what words and concepts appear in the materials”**. Building semantic/lexical maps from RAG directly, without touching module configs, fits the hybrid and can be strictly additive.
