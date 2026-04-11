# GUI Workflow Hardening Plan

This plan is scoped to the repo-root GUI monolith in `studyplan_app.py`.
It focuses on the most fragile workflow seams:

- question generation
- Section C generation / evaluation / rewrite
- classification and presentation drills
- guided practice setup
- AI-assisted quiz scoring and persistence

The goal is not to redesign the app. The goal is to make the existing
workflow safer under async callbacks, live-bank mutation, and memory
pressure.

## Why this matters

The current app already has strong features, but the highest-risk paths all
share the same failure mode:

- a user action starts an async workflow
- the workflow mutates shared state from background callbacks
- the question bank or case changes before the callback finishes
- late results can overwrite newer state or score the wrong row

That makes the GUI monolith fragile in exactly the places that matter most:

- question generation can quarantine or persist stale rows
- Section C can evaluate an outdated case after the dialog has moved on
- practice sessions can score against a moved question row
- presentation/classification drills can save the wrong item if identity is only positional

## Review Signals

The strongest signals from the workflow review were:

1. `dict` state is still used as the transport for long-running flows.
2. Question identity was historically positional in several places.
3. UI callbacks and worker-thread completions both touch the same state.
4. AI outputs are useful, but they must be treated as provisional until the
   current workflow token still matches.
5. Scoring and persistence need to follow the live row, not the original index.

The current hardening work already moved the app in the right direction:

- workflow tokens exist for gap generation and Section C
- generated cases/questions are snapshotted instead of shared by reference
- quiz sessions snapshot the question bank
- quiz scoring resolves a live index by fingerprint before mutating engine state

This plan describes the next slices.

## Design Principles

1. **Token every async turn**
   - Every generation/evaluation workflow gets a monotonic token.
   - A late callback must fail closed if the token is stale.

2. **Snapshot at turn start**
   - Store an isolated copy of the question/case payload that the workflow will use.
   - Never rely on a shared live object after the async turn has begun.

3. **Use stable identity**
   - Prefer fingerprint or durable id over list position.
   - Resolve the live row at the last possible moment before mutation.

4. **Separate presentation from mutation**
   - UI rendering can use snapshots freely.
   - Engine writes should happen only after the workflow is still current.

5. **Fail safe under memory pressure**
   - If prompt size, queue depth, or memory estimate is too high, reject early.
   - Prefer a clean refusal over process thrash or partial state updates.

## Current Status

Implemented in the GUI monolith:

- gap generation token checks
- Section C stale-workflow cancellation
- question snapshot helpers
- quiz-session snapshotting
- resolved-live-index quiz scoring

Still to harden:

- guided practice generation and AI-assisted rubric evaluation
- any other async tutor turn that can outlive the current dialog
- memory-aware admission for concurrent tutor inference
- stale-result suppression for presentation/classification regeneration

## Phase 1: Tokenize Every Async Tutor Turn

Expand the current token pattern to the rest of the tutor workflow:

- guided practice generation
- classification/presentation generation
- Section C evaluation retries
- rewrite-loop re-evaluation

Implementation target:

- every async entry point should capture a workflow token
- every completion handler should verify the token before writing state
- token invalidation should happen when the dialog closes, topic changes, or a new turn starts

Acceptance criteria:

- a stale background completion cannot overwrite newer tutor state
- closing a dialog invalidates all outstanding completions
- re-opening the same workflow starts with a fresh token

## Phase 2: Expand Snapshot Boundaries

The app should snapshot the minimum data it needs for each turn:

- question stem
- options / rubric / model outline
- active chapter/topic
- current feedback state
- any rewrite baseline needed for comparison

The snapshot should be immutable for the lifetime of the turn.

Implementation target:

- use cloned JSON-like payloads for all case/question objects passed into
  background work
- do not let a worker hold a direct reference to the live bank row or dialog state

Acceptance criteria:

- mutating the live bank after session start does not change the active session
- answer evaluation still works when the live bank changes underneath it

## Phase 3: Make Identity Durable

This is the most important correctness improvement after tokenization.

Do not trust position alone for:

- quiz scoring
- SRS updates
- competence updates
- difficulty tracking
- outcome recording

Instead:

- derive a stable fingerprint for the question payload
- resolve the current live row from that fingerprint right before engine mutation
- fall back to the original index only when the live row still matches

Acceptance criteria:

- removing or reordering questions does not shift scoring to the wrong row
- stale rows are skipped rather than mis-scored
- engine-side state changes always point at the intended live row

## Phase 4: Harden Guided Practice and Presentation Drills

The next biggest fragility is generated practice outside the plain MCQ quiz.

Focus areas:

- classification / presentation question generation
- gap-question generation for topic weaknesses
- guided practice sessions that prefetch reasons, hints, or rubric feedback
- any “re-evaluate” loop that reuses the earlier answer

Recommended approach:

- snapshot the prompt inputs before generation starts
- token the generation request
- validate AI output against the current workflow token before save
- store the result only after the current dialog/session still matches

Acceptance criteria:

- a stale generation cannot save into the wrong session
- a late evaluation cannot attach feedback to the wrong prompt
- “rewrite weakest” uses the same baseline case it started with

## Phase 5: Add Memory-Aware Admission

The tutor layer should be conservative when the app is under pressure.

Suggested controls:

- max in-flight tutor requests
- max queued tutor requests
- max prompt/context size
- per-model cooldown after repeated failures
- per-request memory estimate gate

This is a policy layer, not a UI concern.

Implementation target:

- one admission gate in the shared tutor/runtime path
- the GUI asks for work, but the runtime decides whether it can safely run now

Acceptance criteria:

- overlapping tutor requests do not overcommit memory
- the user gets a clean “busy / try again” response instead of a crash
- retries are bounded and do not form a loop

## Phase 6: Make AI Evaluation Safer

AI-assisted scoring and rubric evaluation should be treated as high-risk writes.

Requirements:

- parse and validate output before it touches persistent state
- if the current workflow token is stale, discard the result
- if the bank row moved, resolve the live row before scoring
- if resolution fails, skip engine-side mutation rather than guessing

Acceptance criteria:

- rubric feedback cannot be attached to the wrong case
- generated marks cannot update a stale question row
- a cancelled or closed dialog leaves no partial scoring behind

## Phase 7: Observability and Regression Coverage

The plan should be test-driven and measurable.

Add tests for:

- stale gap-generation cancellation
- stale Section C evaluation rejection
- snapshot cloning of question/case payloads
- quiz scoring on moved rows
- guided practice completion after topic change
- memory-gate rejection under simulated overload
- stale request suppression when a dialog closes mid-turn

Add logging or metrics for:

- workflow token bumps
- stale completion rejections
- resolved live index vs original index
- memory/admission rejections
- evaluation fallback counts

Acceptance criteria:

- every workflow hardening change has at least one regression test
- stale callback behavior is visible in logs when it happens
- the app can explain why a turn was accepted, rejected, or discarded

## Recommended Order

1. Tokenize the remaining async tutor flows.
2. Expand snapshotting for guided practice / presentation generation.
3. Make stable identity the default for all scoring and persistence.
4. Add memory-aware admission.
5. Add observability and regression tests for the new paths.

## Non-Goals

- Do not replace the root GUI with a new framework.
- Do not move the core workflow into a separate app before hardening it.
- Do not optimize backend inference before the GUI workflow is safe.
- Do not rely on positional question indices as durable identity.

## Related Work

- `docs/GUI_MONOLITH_PERFORMANCE_PLAN.md`
- `docs/HARDENING.md`
- `docs/PERFORMANCE_OPTIMIZATION_SLICE.md`
- `docs/DEVELOPER_DOC.md`

