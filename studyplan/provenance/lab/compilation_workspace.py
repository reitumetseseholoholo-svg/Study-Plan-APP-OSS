"""Compilation Workspace — GTK workspace for the CIR compiler platform.

Provides a compiler IDE experience:
  - Source panel with import/status
  - Pipeline view (parse → validate → optimize → merge)
  - Semantic diff (Already Known / New / Modified / Conflicting / Uncertain)
  - Identity review with Merge/Keep decisions
  - Cognitive state panel with intervention recommendations
  - CIR inspector

Follows the pattern established by the Coach and Insights workspace pages.
Built as a standalone module that the Study Workbench loads as a new tab.
"""

from __future__ import annotations

import os
import json
import time
import tempfile
import hashlib
from datetime import datetime, timezone
from collections import defaultdict
from typing import Any, TYPE_CHECKING

from studyplan.provenance.cir import (
    CognitiveIR,
)
from studyplan.provenance.cir.container import validate_ir
from studyplan.provenance.cir.passes import run_passes
from studyplan.provenance.lab.compilation import (
    CIRMerger,
    PDFFrontendPlugin,
    NotesFrontendPlugin,
    FMKnowledgeBasePlugin,
)
from studyplan.provenance.lab.compilation.identity_v2 import (
    GlobalIdentityRegistry,
    SemanticEquivalenceScorer,
    ProvenanceWeightedIdentity,
    make_weighted,
)
from studyplan.provenance.lab.compilation.fragment import CIRFragment
from studyplan.provenance.learning.compiler_bridge import get_compiler_bus
from studyplan.provenance.kernel.performance import get_performance_registry
from studyplan.provenance.learning.events import (
    source_imported,
    compilation_started,
    extraction_completed,
    ambiguity_detected,
    merge_candidate,
    review_decision,
    publish_completed,
    review_opened,
    provenance_viewed,
    dependency_graph_viewed,
    candidate_compared,
    review_abandoned,
)
from studyplan.provenance.learning.cognitive_projection import (
    CognitiveProjectionEngine,
    CognitiveProjection,
)
from studyplan.provenance.cognition.controller import (
    CognitiveController,
    ForwardModel,
    InterventionRanking,
)
from studyplan.provenance.cognition.outcome import (
    compute_closed_loop_outcomes,
)
from studyplan.provenance.lab.integration import push_identity_aliases

try:
    from gi.repository import Gtk, GObject, GLib, Pango, Gdk

    _HAS_GTK = True
except ImportError:
    _HAS_GTK = False
    # Stub for compile-only checks
    Gtk = GObject = GLib = Pango = Gdk = object()

if TYPE_CHECKING:
    # Provide types for static checkers when gi stubs are available in the
    # environment. Use type: ignore to avoid runtime import errors in CI.
    try:  # pragma: no cover - type checking only
        from gi.repository import Gtk as Gtk  # type: ignore
        from gi.repository import GObject as GObject  # type: ignore
        from gi.repository import GLib as GLib  # type: ignore
        from gi.repository import Pango as Pango  # type: ignore
        from gi.repository import Gdk as Gdk  # type: ignore
    except Exception:
        pass


STOPWORDS: frozenset[str] = frozenset(
    {
        "some",
        "different",
        "conflicting",
        "textbook",
        "always",
        "there",
        "examiner",
        "report",
        "june",
        "many",
        "forgetting",
        "discounted",
        "ignored",
        "used",
        "candidates",
        "using",
        "average",
        "book",
        "calculate",
        "answer",
        "accept",
        "payback",
        "reducing",
        "this",
        "limitations",
        "uses",
        "assumes",
        "high",
        "with",
        "value",
        "optimal",
        "both",
        "return",
        "note",
        "total",
        "receivable",
        "payable",
        "offering",
        "managing",
        "question",
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "by",
        "from",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "shall",
        "need",
        "dare",
        "ought",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "whose",
        "why",
        "how",
        "all",
        "each",
        "every",
        "few",
        "more",
        "most",
        "other",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "just",
        "because",
        "if",
        "while",
        "though",
        "although",
        "however",
        "therefore",
        "thus",
        "hence",
        "then",
        "else",
        "otherwise",
        "nevertheless",
        "nonetheless",
        "meanwhile",
        "furthermore",
        "moreover",
        "besides",
        "indeed",
        "perhaps",
        "probably",
        "certainly",
        "definitely",
        "absolutely",
    }
)


class CompilationWorkspace:
    """First-class CIR compiler IDE workspace.

    Manages source compilation, identity review, and decision persistence.
    Produces a GTK page that plugs into the Study Workbench tab system.
    """

    def __init__(self, app_ref: Any = None):
        self._app = app_ref
        self._bus = get_compiler_bus()
        self._sources: dict[str, tuple[str, Any]] = {}  # name -> (kind, data)
        self._source_ids: dict[str, str] = {}
        self._compiled_ir: CognitiveIR | None = None
        self._merge_report: Any = None
        self._decision_log: list[dict[str, Any]] = []
        self._identity_decisions: dict[str, str] = {}  # local_id -> decision
        self._scorer = SemanticEquivalenceScorer()
        self._registry = GlobalIdentityRegistry(scorer=self._scorer)
        # Attempt to load persisted GIR and review decisions (best-effort)
        try:
            self.load_persisted_gir()
            self.load_review_decisions()
        except Exception:
            pass
        self._pipeline_results: dict[str, Any] = {}
        self._ready = False
        self._status_label: Gtk.Label | None = None
        self._cog_event_count: Gtk.Label | None = None
        self._cog_health_dot: Gtk.Label | None = None
        self._cog_next_action: Gtk.Label | None = None
        self._cog_body: Gtk.Box | None = None
        self._diff_box: Gtk.Box | None = None
        self._review_box: Gtk.Box | None = None
        self._pipeline_box: Gtk.Box | None = None
        self._source_box: Gtk.Box | None = None
        self._inspect_view: Gtk.TextView | None = None
        self._review_timestamps: dict[str, float] = {}
        self._viewed_artifacts: dict[str, list[str]] = {}
        self._review_on_deck: str | None = None
        self._forward_model = ForwardModel(learning_rate=0.1)
        self._processed_action_outcome_count: int = 0

    # ── Source management ────────────────────────────────────

    def add_source(self, name: str, kind: str, data: Any, source_id: str | None = None) -> None:
        self._sources[name] = (kind, data)
        self._source_ids[name] = source_id or f"{kind}:{name}"
        chunk_count = len(data) if isinstance(data, list) else 1
        self._bus.emit(
            source_imported(
                self._source_ids[name],
                kind,
                name,
                chunk_count,
            )
        )

    def remove_source(self, name: str) -> None:
        self._sources.pop(name, None)
        self._source_ids.pop(name, None)

    def has_source(self, name: str) -> bool:
        return name in self._sources

    def source_count(self) -> int:
        return len(self._sources)

    @property
    def decision_count(self) -> int:
        return len(self._decision_log)

    @property
    def cognitive_projection(self) -> CognitiveProjection:
        """Ephemeral cognitive state projected from compiler event history.

        Computed on-demand from EventBus history — no stored state,
        no new event types. Uncertainty, stability, familiarity, and
        confusion edges derived from review_decision, candidate_compared,
        and provenance_viewed events.
        """
        events = self._bus.history() if self._bus else []
        return CognitiveProjectionEngine().project(events)

    @property
    def cognitive_projection_event_count(self) -> int:
        return self.cognitive_projection.event_count

    @property
    def cognitive_controller(self) -> CognitiveController:
        return CognitiveController()

    @property
    def cognitive_intervention_ranking(self) -> InterventionRanking:
        """Ranked interventions projected from current cognitive state.

        Pure function — stateless, recomputed every call.
        Uses CIR dependency graph for leverage scoring if available.
        """
        proj = self.cognitive_projection
        deps = self._build_dependency_graph()
        return self.cognitive_controller.evaluate(proj, dependency_graph=deps)

    @property
    def next_best_action(self) -> str:
        """Human-readable best next action string."""
        ranking = self.cognitive_intervention_ranking
        if ranking.best:
            return f"[{ranking.best.score:.2f}] {ranking.best.rationale}"
        return "No intervention needed"

    def _build_dependency_graph(self) -> dict[str, list[str]] | None:
        """Extract 'assumes' dependency graph from compiled CIR.

        Returns {identity_id: [dependent_ids]} or None if no CIR.
        """
        ir = self._compiled_ir
        if ir is None:
            return None
        deps: dict[str, list[str]] = {}
        for r in ir.relations:
            if r.type == "assumes":
                if r.target not in deps:
                    deps[r.target] = []
                deps[r.target].append(r.source)
        return deps

    # ── Compilation pipeline ─────────────────────────────────

    def compile_all(self) -> None:
        """Run the full compilation pipeline."""
        # Emit abandonment for any review groups that were opened but unresolved
        if self._pipeline_results.get("identity_review"):
            now = time.time()
            for group in self._pipeline_results["identity_review"]:
                cid = group["canonical_id"]
                if group.get("decided", False):
                    continue
                if cid not in self._review_timestamps:
                    continue
                if cid in self._identity_decisions:
                    continue
                elapsed = int((now - self._review_timestamps[cid]) * 1000)
                evidence = self._viewed_artifacts.get(cid, [])
                self._bus.emit(
                    review_abandoned(
                        cid,
                        group.get("members", []),
                        list(group.get("member_labels", [])),
                        evidence,
                        elapsed,
                    )
                )

        self._pipeline_results = {}

        if not self._sources:
            self._pipeline_results["status"] = "No sources registered."
            self._bus.emit(compilation_started("none"))
            self._ready = True
            return

        merger = CIRMerger()
        fragments: list[CIRFragment] = []
        per_source_stats: dict[str, dict] = {}

        for name, (kind, data) in self._sources.items():
            plugin = self._get_plugin(kind)
            if plugin is None:
                continue
            sid = self._source_ids.get(name, f"{kind}:{name}")
            self._bus.emit(compilation_started(sid))
            fragment = plugin.compile_to_cir(data, source_id=sid)
            fragments.append(fragment)
            per_source_stats[name] = {
                "identities": len(fragment.identities),
                "artifacts": len(fragment.artifacts),
                "relations": len(fragment.relations),
            }
            self._bus.emit(
                extraction_completed(
                    sid,
                    len(fragment.identities),
                    len(fragment.artifacts),
                    len(fragment.relations),
                )
            )
            for ident in fragment.identities:
                self._registry.register(make_weighted(kind, sid, ident, trust=0.85))

        self._pipeline_results["extraction"] = per_source_stats

        # Stage 2: Merge via CIRMerger
        ir = merger.merge(fragments)
        self._compiled_ir = ir
        self._merge_report = merger.last_report if hasattr(merger, "last_report") else None
        self._pipeline_results["merged"] = {
            "identities": len(ir.identities),
            "artifacts": len(ir.artifacts),
            "relations": len(ir.relations),
            "fragment_count": len(fragments),
        }

        # Stage 3: Validation
        validation_result = validate_ir(ir)
        self._pipeline_results["validation"] = {
            "valid": validation_result.valid,
            "errors": [(e.rule, e.message[:120]) for e in validation_result.errors],
            "warnings": [(w.rule, w.message[:120]) for w in validation_result.warnings],
        }

        # Stage 4: Pass pipeline
        ir_after = run_passes(ir)
        pre_ids = len(ir.identities)
        post_ids = len(ir_after.identities)
        self._pipeline_results["passes"] = {
            "duplicates_removed": max(0, pre_ids - post_ids),
            "pre_identities": pre_ids,
            "post_identities": post_ids,
        }
        self._compiled_ir = ir_after

        # Stage 5: Semantic diff
        self._pipeline_results["semantic_diff"] = self._compute_semantic_diff()

        # Stage 6: Identity review — equivalence detection via scorer
        self._pipeline_results["identity_review"] = self._compute_review_data()

        # Emit ambiguity and merge-candidate events for review groups
        review_data = self._pipeline_results.get("identity_review", [])
        for group in review_data:
            if group.get("decided", False):
                continue
            scores = [1.0] * len(group.get("members", []))
            self._bus.emit(
                ambiguity_detected(
                    list(self._sources.keys())[0] if self._sources else "",
                    group.get("members", []),
                    group.get("member_labels", []),
                    scores,
                )
            )
            for mid in group.get("members", []):
                self._bus.emit(
                    merge_candidate(
                        list(self._sources.keys())[0] if self._sources else "",
                        mid,
                        self._resolve_label(mid),
                        group["canonical_id"],
                        self._resolve_label(group["canonical_id"]),
                        1.0,
                    )
                )

        self._bus.emit(
            publish_completed(
                list(self._source_ids.values())[0] if self._source_ids else "",
                len(ir_after.identities) if ir_after else 0,
                len(ir_after.artifacts) if ir_after else 0,
                len(ir_after.relations) if ir_after else 0,
                len(self._decision_log),
            )
        )
        self._ready = True

    def _get_plugin(self, kind: str) -> Any:
        if kind == "pdf":
            return PDFFrontendPlugin()
        elif kind == "notes":
            return NotesFrontendPlugin()
        elif kind == "fm_knowledge_base":
            return FMKnowledgeBasePlugin()
        return None

    def _compute_semantic_diff(self) -> dict[str, Any]:
        if self._compiled_ir is None:
            return {}
        concepts = set()
        for i in self._compiled_ir.identities:
            concepts.add(i.label.lower().strip())
        return {
            "total_concepts": len(concepts),
        }

    def _compute_review_data(self) -> list[dict[str, Any]]:
        recorded_ids: list[ProvenanceWeightedIdentity] = []
        for cid in self._registry.all_canonical_ids():
            canon = self._registry.get_canonical(cid)
            if canon is not None:
                recorded_ids.append(canon)

        # Build context map: identities that share a source lineage
        context_map: dict[str, frozenset[str]] = {}
        for wid in recorded_ids:
            ctx: set[str] = set()
            for other in recorded_ids:
                if other.id == wid.id:
                    continue
                if set(wid.lineage) & set(other.lineage):
                    ctx.add(other.id)
            context_map[wid.id] = frozenset(ctx)

        eq_classes = self._scorer.equivalence_classes(recorded_ids, context_map)

        review: list[dict[str, Any]] = []
        for eq in eq_classes:
            if len(eq.member_ids) < 2:
                continue
            member_labels = set()
            for mid in eq.member_ids:
                label = self._resolve_label(mid)
                if label and label.lower() not in STOPWORDS:
                    member_labels.add(label)
            if len(member_labels) < 2:
                continue
            decided = any(self._identity_decisions.get(mid, "") for mid in eq.member_ids)
            review.append(
                {
                    "canonical_id": eq.canonical_id,
                    "members": list(eq.member_ids),
                    "member_labels": sorted(member_labels),
                    "decided": decided,
                    "resolution": self._identity_decisions.get(eq.canonical_id, "unresolved"),
                }
            )
        return review

    def _resolve_label(self, ident_id: str) -> str:
        if self._compiled_ir is None:
            return ident_id
        for i in self._compiled_ir.identities:
            if i.id == ident_id:
                return i.label
        return ident_id

    def _get_review_count(self) -> int:
        data = self._pipeline_results.get("identity_review", [])
        return sum(1 for d in data if not d.get("decided", False))

    # ── Decision persistence ─────────────────────────────────

    def record_decision(self, canonical_id: str, decision: str, member_ids: list[str] | None = None) -> None:
        entry = {
            "canonical_id": canonical_id,
            "decision": decision,
            "member_ids": member_ids or [],
        }
        self._decision_log.append(entry)
        for mid in member_ids or []:
            self._identity_decisions[mid] = decision
        self._identity_decisions[canonical_id] = decision

    def export_decision_log(self) -> list[dict[str, Any]]:
        return list(self._decision_log)

    def get_alias_map(self) -> dict[str, str]:
        """Return the GIR's local-to-canonical identity mapping.

        Maps every registered local identity ID to its canonical ID.
        When an identity was merged, the local ID resolves to the
        chosen canonical (RHS).  Unmerged identities still appear
        with a self-map (local → local).

        Used by the ProvenanceIntegrator bridge (CI-B-01) so that
        provenance queries benefit from compiler identity resolution.
        """
        return dict(self._registry._local_to_canonical)

    # ── Demo data loading ────────────────────────────────────

    def load_demo_corpus(self, corpus_dir: str | None = None) -> None:
        """Load the ACCA FM batch validation corpus as demo data."""
        if corpus_dir is None:
            corpus_dir = "/tmp/opencode/batch_validation"
        corpus_module = os.path.join(corpus_dir, "corpus.py")
        if not os.path.exists(corpus_module):
            return
        import importlib.util

        spec = importlib.util.spec_from_file_location("corpus", corpus_module)
        if spec is None or spec.loader is None:
            return
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for key in mod.ALL_SOURCES:
            name = mod.SHORT_NAMES.get(key, key)
            chunks = mod.CORPUS[key]
            self.add_source(name, "pdf", chunks, source_id=f"pdf:{key}")

    # ── GTK page builder ─────────────────────────────────────

    def build_page(self) -> Gtk.Widget:
        if not _HAS_GTK:
            return Gtk.Label(label="GTK not available")

        page_scroll = Gtk.ScrolledWindow()
        page_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        page_scroll.set_hexpand(True)
        page_scroll.set_vexpand(True)
        page_scroll.add_css_class("workbench-page")

        page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page_box.add_css_class("card")
        page_box.add_css_class("workbench-page-card")
        page_box.set_margin_top(6)
        page_box.set_margin_bottom(6)
        page_box.set_margin_start(6)
        page_box.set_margin_end(6)
        page_scroll.set_child(page_box)

        # ── Title ────────────────────────────────────────────
        title = Gtk.Label(label="Compilation Workspace")
        title.set_halign(Gtk.Align.START)
        title.add_css_class("section-title")
        title.add_css_class("workbench-heading")
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.set_max_width_chars(120)
        subtitle = Gtk.Label(
            label="Import sources, compile to CIR, review identity merges, "
            "and publish compiled knowledge. This is the compiler IDE "
            "for the CCI knowledge engineering pipeline."
        )
        subtitle.set_halign(Gtk.Align.START)
        subtitle.set_wrap(True)
        subtitle.add_css_class("muted")
        page_box.append(title)
        page_box.append(subtitle)

        # ── Controls ─────────────────────────────────────────
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        controls.add_css_class("inline-toolbar")

        compile_btn = Gtk.Button(label="Compile All")
        compile_btn.add_css_class("suggested-action")
        compile_btn.connect("clicked", self._on_compile_clicked)
        controls.append(compile_btn)

        demo_btn = Gtk.Button(label="Load Demo Corpus")
        demo_btn.connect("clicked", self._on_load_demo)
        controls.append(demo_btn)

        import_btn = Gtk.Button(label="Import PDF")
        import_btn.add_css_class("flat")
        import_btn.connect("clicked", self._on_import_pdf_clicked)
        controls.append(import_btn)

        export_btn = Gtk.Button(label="Export Decisions")
        export_btn.connect("clicked", self._on_export_decisions)
        controls.append(export_btn)

        inspect_btn = Gtk.Button(label="Inspect CIR")
        inspect_btn.connect("clicked", self._on_inspect_cir)
        controls.append(inspect_btn)

        page_box.append(controls)

        # ── Status ───────────────────────────────────────────
        status_label = Gtk.Label(label="Waiting for compilation...")
        status_label.set_halign(Gtk.Align.START)
        status_label.set_ellipsize(Pango.EllipsizeMode.END)
        status_label.add_css_class("single-line-lock")
        status_label.add_css_class("status-line")
        status_label.add_css_class("muted")
        self._status_label = status_label
        page_box.append(status_label)

        # ── Cognitive State ───────────────────────────────────
        self._build_cognitive_card(page_box)

        # ── Source panel ─────────────────────────────────────
        source_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        source_card.add_css_class("card")
        source_card.set_margin_top(4)

        source_title = Gtk.Label(label="Sources")
        source_title.set_halign(Gtk.Align.START)
        source_title.add_css_class("section-title")
        source_card.append(source_title)

        source_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        source_box.set_margin_start(8)
        source_box.set_margin_end(8)
        source_box.set_margin_top(4)
        source_box.set_margin_bottom(4)
        self._source_box = source_box
        source_card.append(source_box)

        page_box.append(source_card)

        # ── Pipeline view ────────────────────────────────────
        pipeline_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        pipeline_card.add_css_class("card")
        pipeline_card.set_margin_top(4)

        pipeline_title = Gtk.Label(label="Compilation Pipeline")
        pipeline_title.set_halign(Gtk.Align.START)
        pipeline_title.add_css_class("section-title")
        pipeline_card.append(pipeline_title)

        pipeline_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        pipeline_box.set_margin_start(8)
        pipeline_box.set_margin_end(8)
        pipeline_box.set_margin_top(4)
        pipeline_box.set_margin_bottom(4)
        self._pipeline_box = pipeline_box
        pipeline_card.append(pipeline_box)

        page_box.append(pipeline_card)

        # ── Semantic diff ────────────────────────────────────
        diff_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        diff_card.add_css_class("card")
        diff_card.set_margin_top(4)

        diff_title = Gtk.Label(label="Semantic Diff")
        diff_title.set_halign(Gtk.Align.START)
        diff_title.add_css_class("section-title")
        diff_card.append(diff_title)

        diff_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        diff_box.set_margin_start(8)
        diff_box.set_margin_end(8)
        diff_box.set_margin_top(4)
        diff_box.set_margin_bottom(4)
        self._diff_box = diff_box
        diff_card.append(diff_box)

        page_box.append(diff_card)

        # ── Identity review ──────────────────────────────────
        review_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        review_card.add_css_class("card")
        review_card.set_margin_top(4)

        review_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        review_title = Gtk.Label(label="Identity Review")
        review_title.set_halign(Gtk.Align.START)
        review_title.add_css_class("section-title")
        review_header.append(review_title)

        review_count_label = Gtk.Label(label="")
        review_count_label.set_halign(Gtk.Align.START)
        review_count_label.add_css_class("muted")
        review_count_label.add_css_class("monospace")
        self._review_count_label = review_count_label
        review_header.append(review_count_label)

        review_card.append(review_header)

        review_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        review_box.set_margin_start(8)
        review_box.set_margin_end(8)
        review_box.set_margin_top(4)
        review_box.set_margin_bottom(4)
        self._review_box = review_box
        review_card.append(review_box)

        page_box.append(review_card)

        # ── Inspect view (hidden expander) ───────────────────
        inspect_expander = Gtk.Expander(label="CIR Inspector")
        inspect_expander.set_margin_top(4)

        inspect_view = Gtk.TextView()
        inspect_view.set_editable(False)
        inspect_view.set_cursor_visible(False)
        inspect_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        inspect_view.add_css_class("monospace")
        inspect_view.set_size_request(-1, 250)
        self._inspect_view = inspect_view

        inspect_scroll = Gtk.ScrolledWindow()
        inspect_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        inspect_scroll.set_min_content_height(250)
        inspect_scroll.set_hexpand(True)
        inspect_scroll.set_vexpand(True)
        inspect_scroll.set_child(inspect_view)
        inspect_expander.set_child(inspect_scroll)
        page_box.append(inspect_expander)

        self._refresh_page_ui()
        return page_scroll

    # ── Cognitive state panel ────────────────────────────────

    def _build_cognitive_card(self, parent: Gtk.Box) -> None:
        """Build a compact cognitive state card with intervention recommendations.

        Displays projection event count, next best action, and ranked
        interventions — surfaced from CognitiveProjectionEngine and
        CognitiveController, computed on demand with zero stored state.
        """
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.add_css_class("card")
        card.set_margin_top(4)
        card.set_margin_bottom(2)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title = Gtk.Label(label="Cognitive State")
        title.set_halign(Gtk.Align.START)
        title.add_css_class("section-title")
        header.append(title)

        health_dot = Gtk.Label(label="●")
        health_dot.set_halign(Gtk.Align.START)
        health_dot.set_margin_start(4)
        health_dot.add_css_class("monospace")
        self._cog_health_dot = health_dot
        header.append(health_dot)

        event_count_label = Gtk.Label(label="0 events")
        event_count_label.set_halign(Gtk.Align.START)
        event_count_label.add_css_class("muted")
        event_count_label.add_css_class("monospace")
        self._cog_event_count = event_count_label
        header.append(event_count_label)

        header.append(Gtk.Label(label="", hexpand=True))

        next_action_label = Gtk.Label(label="")
        next_action_label.set_halign(Gtk.Align.END)
        next_action_label.add_css_class("monospace")
        next_action_label.set_ellipsize(Pango.EllipsizeMode.END)
        next_action_label.set_max_width_chars(80)
        self._cog_next_action = next_action_label
        header.append(next_action_label)

        card.append(header)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        body.set_margin_start(8)
        body.set_margin_end(8)
        body.set_margin_top(2)
        body.set_margin_bottom(4)
        self._cog_body = body
        card.append(body)

        parent.append(card)

    def _update_cognitive_panel(self) -> None:
        """Refresh cognitive state labels and intervention list."""
        if self._cog_event_count is None:
            return

        # ── Auto-calibrate from unprocessed action outcomes ───
        bus_events = self._bus.history() if self._bus else []
        outcomes = compute_closed_loop_outcomes(bus_events)
        new_outcomes = outcomes[self._processed_action_outcome_count :]
        for outcome in new_outcomes:
            self._forward_model.update_from_outcome(outcome)
        self._processed_action_outcome_count = len(outcomes)

        projection = self.cognitive_projection
        ranking = self.cognitive_intervention_ranking

        self._cog_event_count.set_label(f"{projection.event_count} events")

        has_issues = not ranking.is_empty
        if has_issues:
            top_score = ranking.best.score if ranking.best else 0.0
            if top_score > 0.6:
                self._cog_health_dot.set_markup('<span foreground="#e66100">●</span>')
                self._cog_next_action.set_label(f"→ {ranking.best.rationale}")
            elif top_score > 0.3:
                self._cog_health_dot.set_markup('<span foreground="#d4a017">●</span>')
                self._cog_next_action.set_label(f"→ {ranking.best.rationale}")
            else:
                self._cog_health_dot.set_markup('<span foreground="#2e7d32">●</span>')
                self._cog_next_action.set_label(f"→ {ranking.best.rationale}")
        else:
            self._cog_health_dot.set_markup('<span foreground="#558b2f">●</span>')
            self._cog_next_action.set_label("")

        while True:
            child = self._cog_body.get_first_child()
            if child is None:
                break
            self._cog_body.remove(child)

        if ranking.is_empty:
            empty_lbl = Gtk.Label(label="No interventions needed — stable state.")
            empty_lbl.set_halign(Gtk.Align.START)
            empty_lbl.add_css_class("muted")
            self._cog_body.append(empty_lbl)
            return

        # Show calibration confidence
        conf = self._forward_model.calibration_confidence
        max_conf = max(conf.values())
        if max_conf > 0:
            conf_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            conf_lbl = Gtk.Label(label=f"calibration: {max_conf:.0%}")
            conf_lbl.set_halign(Gtk.Align.START)
            conf_lbl.add_css_class("muted")
            conf_lbl.add_css_class("monospace")
            conf_row.append(conf_lbl)
            conf_row.set_margin_bottom(2)
            self._cog_body.append(conf_row)

        for i, inter in enumerate(ranking.interventions):
            if i >= 3:
                break
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

            score_lbl = Gtk.Label(label=f"{inter.score:.2f}")
            score_lbl.add_css_class("monospace")
            score_lbl.set_size_request(44, -1)
            score_lbl.set_halign(Gtk.Align.END)
            row.append(score_lbl)

            action_lbl = Gtk.Label(label=inter.action_type.value)
            action_lbl.add_css_class("monospace")
            action_lbl.add_css_class("tag")
            action_lbl.set_size_request(100, -1)
            action_lbl.set_halign(Gtk.Align.START)
            row.append(action_lbl)

            rationale_lbl = Gtk.Label(label=inter.rationale)
            rationale_lbl.set_halign(Gtk.Align.START)
            rationale_lbl.set_hexpand(True)
            rationale_lbl.set_ellipsize(Pango.EllipsizeMode.END)
            rationale_lbl.set_max_width_chars(120)
            row.append(rationale_lbl)

            self._cog_body.append(row)

    # ── UI refresh ───────────────────────────────────────────

    def _refresh_page_ui(self) -> None:
        """Refresh all UI panels from current state."""
        self._update_source_panel()
        self._update_pipeline_panel()
        self._update_diff_panel()
        self._update_review_panel()
        self._update_cognitive_panel()
        self._update_status()

    def refresh(self) -> None:
        """Public refresh method called from the app's refresh dispatch.

        Wraps _refresh_page_ui for external callers.
        """
        self._refresh_page_ui()

    def _update_source_panel(self) -> None:
        if self._source_box is None:
            return
        while True:
            child = self._source_box.get_first_child()
            if child is None:
                break
            self._source_box.remove(child)

        if not self._sources:
            empty = Gtk.Label(label="No sources loaded. Click 'Load Demo Corpus' to load the ACCA FM batch.")
            empty.set_halign(Gtk.Align.START)
            empty.add_css_class("muted")
            self._source_box.append(empty)
            return

        for name, (kind, _) in sorted(self._sources.items()):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            status_icon = Gtk.Label(label="✓")
            status_icon.add_css_class("accent")
            status_icon.set_margin_end(4)
            row.append(status_icon)

            name_label = Gtk.Label(label=name)
            name_label.set_halign(Gtk.Align.START)
            name_label.set_hexpand(True)
            name_label.set_ellipsize(Pango.EllipsizeMode.END)
            row.append(name_label)

            kind_label = Gtk.Label(label=f"({kind})")
            kind_label.add_css_class("muted")
            kind_label.add_css_class("monospace")
            row.append(kind_label)

            stats = self._pipeline_results.get("extraction", {}).get(name, {})
            if stats:
                stat_text = f"{stats.get('identities', 0)} id, {stats.get('artifacts', 0)} art"
                stat_label = Gtk.Label(label=stat_text)
                stat_label.add_css_class("muted")
                stat_label.add_css_class("monospace")
                row.append(stat_label)

            self._source_box.append(row)

    def _append_status_row(self, container: Gtk.Box, icon: str, text: str, detail: str = "") -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        icon_label = Gtk.Label(label=icon)
        icon_label.set_margin_end(4)
        row.append(icon_label)

        text_label = Gtk.Label(label=text)
        text_label.set_halign(Gtk.Align.START)
        text_label.set_hexpand(True)
        row.append(text_label)

        if detail:
            detail_label = Gtk.Label(label=detail)
            detail_label.add_css_class("muted")
            detail_label.add_css_class("monospace")
            row.append(detail_label)

        container.append(row)

    def _update_pipeline_panel(self) -> None:
        if self._pipeline_box is None:
            return
        while True:
            child = self._pipeline_box.get_first_child()
            if child is None:
                break
            self._pipeline_box.remove(child)

        if not self._ready:
            empty = Gtk.Label(label="Run Compile All to see pipeline results.")
            empty.set_halign(Gtk.Align.START)
            empty.add_css_class("muted")
            self._pipeline_box.append(empty)
            return

        # Extraction
        ext = self._pipeline_results.get("extraction", {})
        total_id = sum(s.get("identities", 0) for s in ext.values())
        total_art = sum(s.get("artifacts", 0) for s in ext.values())
        self._append_status_row(
            self._pipeline_box,
            "✓",
            "Extraction",
            f"{total_id} identities, {total_art} artifacts across {len(ext)} sources",
        )

        # Validation
        val = self._pipeline_results.get("validation", {})
        if val.get("valid", False):
            self._append_status_row(self._pipeline_box, "✓", "Validation", "All 11 V-rules passed")
        else:
            n = len(val.get("errors", []))
            self._append_status_row(self._pipeline_box, "✗", "Validation", f"{n} rule failures")

        # Pass pipeline
        passes = self._pipeline_results.get("passes", {})
        dups = passes.get("duplicates_removed", 0)
        if dups > 0:
            self._append_status_row(self._pipeline_box, "✓", "Optimization", f"{dups} duplicate identities removed")
        else:
            self._append_status_row(self._pipeline_box, "✓", "Optimization", "No duplicates found")

        # Merge
        merged = self._pipeline_results.get("merged", {})
        if merged:
            self._append_status_row(
                self._pipeline_box,
                "✓",
                "Merge",
                f"{merged.get('identities', 0)} canonical identities, {merged.get('artifacts', 0)} artifacts",
            )

    def _update_diff_panel(self) -> None:
        if self._diff_box is None:
            return
        while True:
            child = self._diff_box.get_first_child()
            if child is None:
                break
            self._diff_box.remove(child)

        if not self._ready or self._compiled_ir is None:
            empty = Gtk.Label(label="Compile to see semantic diff.")
            empty.set_halign(Gtk.Align.START)
            empty.add_css_class("muted")
            self._diff_box.append(empty)
            return

        ir = self._compiled_ir
        id_types = defaultdict(int)
        art_types = defaultdict(int)
        rel_types = defaultdict(int)
        for i in ir.identities:
            id_types[i.type] += 1
        for a in ir.artifacts:
            art_types[a.type] += 1
        for r in ir.relations:
            rel_types[r.type] += 1

        review_count = self._get_review_count()
        diff_sections = [
            ("Knowledge Concepts", f"{len(ir.identities)} canonical identities, {dict(id_types)}"),
            ("Artifact Types", f"{len(ir.artifacts)} total, {dict(art_types)}"),
            ("Relation Types", f"{len(ir.relations)} total, {dict(rel_types)}"),
            (
                "Identity Review",
                f"{review_count} flagged for review " if review_count > 0 else "All identities resolved",
            ),
        ]

        if review_count > 0:
            diff_sections.append(("⚠ Ambiguity", f"{review_count} unresolved identity groups"))

        for label, value in diff_sections:
            self._append_status_row(self._diff_box, "•", label, value)

    def _update_review_panel(self) -> None:
        if self._review_box is None:
            return
        while True:
            child = self._review_box.get_first_child()
            if child is None:
                break
            self._review_box.remove(child)

        review_data = self._pipeline_results.get("identity_review", [])
        unresolved = [d for d in review_data if not d.get("decided", False)]

        if not unresolved:
            done = Gtk.Label(label="All identity groups reviewed.")
            done.set_halign(Gtk.Align.START)
            done.add_css_class("muted")
            self._review_box.append(done)
            if self._review_count_label is not None:
                self._review_count_label.set_label("")
            return

        if self._review_count_label is not None:
            self._review_count_label.set_label(f"{len(unresolved)} flagged")

        for group in unresolved[:10]:
            cid = group["canonical_id"]
            if cid not in self._review_timestamps:
                self._review_timestamps[cid] = time.time()
                self._review_on_deck = cid
            labels = group.get("member_labels", [])
            members = group.get("members", [])
            resolution = group.get("resolution", "unresolved")

            # Emit review_opened on first render of this group
            self._bus.emit(
                review_opened(
                    cid,
                    members,
                    labels,
                    len(unresolved),
                )
            )

            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            card.add_css_class("card")
            card.set_margin_top(2)
            card.set_margin_bottom(2)

            # Header
            header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            icon = Gtk.Label(label="⚠")
            icon.set_margin_end(2)
            header.append(icon)

            cid_label = Gtk.Label(label=cid)
            cid_label.set_halign(Gtk.Align.START)
            cid_label.set_hexpand(True)
            cid_label.add_css_class("monospace")
            header.append(cid_label)

            count_label = Gtk.Label(label=f"{len(labels)} aliases")
            count_label.add_css_class("muted")
            header.append(count_label)

            card.append(header)

            # Member list
            for label in labels[:5]:
                alias_label = Gtk.Label(label=f"  • {label}")
                alias_label.set_halign(Gtk.Align.START)
                alias_label.add_css_class("muted")
                card.append(alias_label)
            if len(labels) > 5:
                more = Gtk.Label(label=f"  ... and {len(labels) - 5} more")
                more.set_halign(Gtk.Align.START)
                more.add_css_class("muted")
                card.append(more)

            # Investigation buttons
            invest_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            invest_row.set_margin_top(2)

            prov_btn = Gtk.Button(label="View Provenance")
            prov_btn.add_css_class("flat")
            prov_btn.connect("clicked", self._on_view_provenance, cid, members, labels)
            invest_row.append(prov_btn)

            dep_btn = Gtk.Button(label="Dependency Graph")
            dep_btn.add_css_class("flat")
            dep_btn.connect("clicked", self._on_view_dependency_graph, cid, labels)
            invest_row.append(dep_btn)

            cmp_btn = Gtk.Button(label="Compare")
            cmp_btn.add_css_class("flat")
            cmp_btn.connect("clicked", self._on_compare_candidates, cid, members, labels)
            invest_row.append(cmp_btn)

            card.append(invest_row)

            # Action buttons
            action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            action_row.set_margin_top(4)

            merge_btn = Gtk.Button(label="Merge")
            merge_btn.add_css_class("suggested-action")
            merge_btn.connect("clicked", self._on_merge_decision, cid, members, labels)
            action_row.append(merge_btn)

            keep_btn = Gtk.Button(label="Keep Separate")
            keep_btn.connect("clicked", self._on_keep_decision, cid, members, labels)
            action_row.append(keep_btn)

            card.append(action_row)

            # Show resolution if already decided
            if resolution != "unresolved":
                res_label = Gtk.Label(
                    label=f"  Decision: {resolution}",
                    halign=Gtk.Align.START,
                )
                res_label.add_css_class("accent")
                card.append(res_label)

            self._review_box.append(card)

    def _update_status(self) -> None:
        if self._status_label is None:
            return
        if not self._ready:
            self._status_label.set_label("Waiting for compilation...")
        else:
            review_count = self._get_review_count()
            n_sources = len(self._sources)
            ir = self._compiled_ir
            n_id = len(ir.identities) if ir else 0
            n_art = len(ir.artifacts) if ir else 0
            status = f"Compiled {n_sources} sources → {n_id} canonical identities, {n_art} artifacts. "
            if review_count > 0:
                status += f"{review_count} identity groups flagged for review."
            else:
                status += "All clear."
            self._status_label.set_label(status)

    # ── Signal handlers ──────────────────────────────────────

    def _on_compile_clicked(self, _btn: Gtk.Button) -> None:
        GLib.idle_add(self._do_compile)

    def _do_compile(self) -> bool:
        self.compile_all()
        self._ready = True
        push_identity_aliases(self.get_alias_map())
        # Persist GIR and review decisions for cross-session resume
        try:
            self.persist_gir()
            self.persist_review_decisions()
        except Exception:
            pass
        self._refresh_page_ui()
        return False

    def persist_gir(self, base_path: str | None = None) -> None:
        """Persist a lightweight GIR snapshot to disk (identities + local→canonical)."""
        try:
            base = base_path or os.path.join(os.path.expanduser("~"), ".local", "share", "studyplan", "gir")
            os.makedirs(base, exist_ok=True)
            out_file = os.path.join(base, "registry.json")

            payload = {
                "identities": {},
                "local_to_canonical": dict(getattr(self._registry, "_local_to_canonical", {})),
                "conflicts": [],
            }
            identities = getattr(self._registry, "_identities", {}) or {}
            for cid, pw in identities.items():
                try:
                    payload["identities"][cid] = {
                        "id": pw.id,
                        "type": pw.type,
                        "label": pw.label,
                        "confidence": float(pw.confidence),
                        "source_trust": float(pw.source_trust),
                        "first_seen": pw.first_seen,
                        "lineage": list(pw.lineage),
                        "metadata": pw.metadata,
                    }
                except Exception:
                    payload["identities"][cid] = {"id": cid, "label": getattr(pw, "label", cid)}

            # Canonical JSON for checksum
            payload_canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            checksum = hashlib.sha256(payload_canonical.encode("utf-8")).hexdigest()
            envelope = {
                "schema_version": 1,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "payload": payload,
                "checksum": checksum,
            }

            # Atomic write using tempfile + os.replace
            fd, tmp = tempfile.mkstemp(dir=base, prefix="registry-", suffix=".json")
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(json.dumps(envelope, indent=2, ensure_ascii=False).encode("utf-8"))
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, out_file)
            finally:
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except Exception:
                    pass
        except Exception:
            pass

    def persist_review_decisions(self, base_path: str | None = None) -> None:
        """Persist the review decision log to disk for resume/apply on next compile."""
        try:
            base = base_path or os.path.join(os.path.expanduser("~"), ".local", "share", "studyplan", "gir")
            os.makedirs(base, exist_ok=True)
            out_file = os.path.join(base, "review_decisions.json")

            payload = list(self._decision_log)
            payload_canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            checksum = hashlib.sha256(payload_canonical.encode("utf-8")).hexdigest()
            envelope = {
                "schema_version": 1,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "payload": payload,
                "checksum": checksum,
            }

            fd, tmp = tempfile.mkstemp(dir=base, prefix="review-", suffix=".json")
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(json.dumps(envelope, indent=2, ensure_ascii=False).encode("utf-8"))
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, out_file)
            finally:
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except Exception:
                    pass
        except Exception:
            pass

    def load_persisted_gir(self, base_path: str | None = None) -> None:
        """Load a previously persisted GIR snapshot (best-effort)."""
        try:
            base = base_path or os.path.join(os.path.expanduser("~"), ".local", "share", "studyplan", "gir")
            in_file = os.path.join(base, "registry.json")
            if not os.path.exists(in_file):
                return
            # Read envelope
            with open(in_file, "r", encoding="utf-8") as f:
                envelope = json.load(f)

            # Basic integrity checks
            schema_v = int(envelope.get("schema_version", 1))
            payload = envelope.get("payload", {}) or {}
            checksum = envelope.get("checksum")
            # Recompute canonical checksum
            payload_canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            recomputed = hashlib.sha256(payload_canonical.encode("utf-8")).hexdigest()
            if checksum != recomputed:
                # Move corrupt file aside
                try:
                    corrupt_name = in_file + f".corrupt.{int(time.time())}"
                    os.replace(in_file, corrupt_name)
                except Exception:
                    pass
                return

            # Migrate payload if needed
            if schema_v != 1:
                try:
                    payload = self._migrate_gir(payload, schema_v)
                except NotImplementedError:
                    return

            identities = payload.get("identities", {}) or {}
            local_map = payload.get("local_to_canonical", {}) or {}
            # Reconstruct identities
            for cid, info in identities.items():
                try:
                    pwi = ProvenanceWeightedIdentity(
                        id=info.get("id", cid),
                        type=info.get("type", "unknown"),
                        label=info.get("label", ""),
                        confidence=float(info.get("confidence", 1.0)),
                        source_trust=float(info.get("source_trust", 1.0)),
                        first_seen=info.get("first_seen", ""),
                        lineage=tuple(info.get("lineage", [])),
                        metadata=info.get("metadata", {}) or {},
                    )
                    self._registry._identities[cid] = pwi
                except Exception:
                    self._registry._identities[cid] = info
            # Restore local->canonical map
            for k, v in local_map.items():
                self._registry._local_to_canonical[k] = v
            # Rebuild label index lightly
            for cid, p in list(self._registry._identities.items()):
                try:
                    key = (p.type, p.label)
                    self._registry._label_to_canonical[key] = cid
                except Exception:
                    continue
        except Exception:
            pass

    def load_review_decisions(self, base_path: str | None = None) -> None:
        """Load persisted review decisions into `_decision_log` and `_identity_decisions`."""
        try:
            base = base_path or os.path.join(os.path.expanduser("~"), ".local", "share", "studyplan", "gir")
            in_file = os.path.join(base, "review_decisions.json")
            if not os.path.exists(in_file):
                return
            with open(in_file, "r", encoding="utf-8") as f:
                envelope = json.load(f)

            schema_v = int(envelope.get("schema_version", 1))
            payload = envelope.get("payload", []) or []
            checksum = envelope.get("checksum")
            payload_canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            recomputed = hashlib.sha256(payload_canonical.encode("utf-8")).hexdigest()
            if checksum != recomputed:
                try:
                    corrupt_name = in_file + f".corrupt.{int(time.time())}"
                    os.replace(in_file, corrupt_name)
                except Exception:
                    pass
                return

            if schema_v != 1:
                try:
                    payload = self._migrate_review_decisions(payload, schema_v)
                except NotImplementedError:
                    return

            if isinstance(payload, list):
                self._decision_log = payload
                for d in payload:
                    lid = d.get("local_id") or d.get("id")
                    decision = d.get("decision")
                    if lid and decision:
                        self._identity_decisions[lid] = decision
        except Exception:
            pass

    def _migrate_gir(self, payload: dict[str, Any], from_version: int) -> dict[str, Any]:
        """Migration stub for GIR payloads. Returns migrated payload.

        Raises NotImplementedError if migration path unknown.
        """
        if from_version == 1:
            return payload
        raise NotImplementedError("GIR migration from version %d not implemented" % from_version)

    def _migrate_review_decisions(self, payload: list[Any], from_version: int) -> list[Any]:
        """Migration stub for review decisions payloads.

        Raises NotImplementedError if migration path unknown.
        """
        if from_version == 1:
            return payload
        raise NotImplementedError("Review decisions migration from version %d not implemented" % from_version)

    def _on_load_demo(self, _btn: Gtk.Button) -> None:
        self.load_demo_corpus()
        self._update_source_panel()
        self._update_status()

    def _on_export_decisions(self, _btn: Gtk.Button) -> None:
        log = self.export_decision_log()
        text = json.dumps(log, indent=2)
        if self._inspect_view is not None:
            buf = self._inspect_view.get_buffer()
            buf.set_text(text)

    def _on_inspect_cir(self, _btn: Gtk.Button) -> None:
        if self._compiled_ir is None:
            if self._inspect_view is not None:
                buf = self._inspect_view.get_buffer()
                buf.set_text("No compiled IR to inspect.")
            return
        ir = self._compiled_ir
        lines = [
            "CIR Inspector",
            f"{'=' * 40}",
            f"Version: {ir.version}",
            "",
            f"Identities ({len(ir.identities)}):",
        ]
        for i in ir.identities:
            lines.append(f"  {i.id:40s} type={i.type:12s} label={i.label}")
        lines.append("")
        lines.append(f"Artifacts ({len(ir.artifacts)}):")
        for a in ir.artifacts:
            lines.append(f"  {a.id:40s} type={a.type:12s} → {a.target_identity}")
        lines.append("")
        lines.append(f"Relations ({len(ir.relations)}):")
        for r in ir.relations:
            lines.append(f"  {r.source:40s} {r.type:15s} → {r.target}")

        text = "\n".join(lines)
        if self._inspect_view is not None:
            buf = self._inspect_view.get_buffer()
            buf.set_text(text)

    def _on_import_pdf_clicked(self, _btn: Gtk.Button) -> None:
        """Open file chooser, extract PDF chunks via app helper, and import as source."""
        if not _HAS_GTK:
            return

        dialog = Gtk.FileChooserDialog(
            title="Import PDF",
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.ACCEPT)
        dialog.set_select_multiple(False)
        filter_pdf = Gtk.FileFilter()
        filter_pdf.set_name("PDF files")
        filter_pdf.add_pattern("*.pdf")
        dialog.add_filter(filter_pdf)

        def _on_response(dlg: Gtk.FileChooserDialog, response: Gtk.ResponseType) -> None:
            try:
                if response != Gtk.ResponseType.ACCEPT:
                    dlg.destroy()
                    return
                file_path = dlg.get_filename()
                dlg.destroy()
                if not file_path:
                    return

                # Prefer app-level rag loader if available (returns {'chunks': [...]})
                chunks = None
                if getattr(self, "_app", None) is not None and hasattr(self._app, "_load_ai_tutor_rag_doc"):
                    try:
                        payload, err = self._app._load_ai_tutor_rag_doc(file_path)
                        if err:
                            # show minimal error via app dialog if possible
                            if hasattr(self._app, "_new_message_dialog"):
                                dlg_msg = self._app._new_message_dialog(
                                    transient_for=self._app,
                                    modal=True,
                                    message_type=Gtk.MessageType.ERROR,
                                    buttons=Gtk.ButtonsType.OK,
                                    text=str(err),
                                )
                                dlg_msg.connect("response", lambda d, r: d.destroy())
                                dlg_msg.present()
                            return
                        if isinstance(payload, dict) and isinstance(payload.get("chunks"), list):
                            chunks = payload.get("chunks")
                    except Exception:
                        chunks = None

                # Fallback: try app-level simple text extractor -> turn into single chunk
                if (
                    chunks is None
                    and getattr(self, "_app", None) is not None
                    and hasattr(self._app, "_extract_pdf_text_for_syllabus")
                ):
                    try:
                        txt, meta = self._app._extract_pdf_text_for_syllabus(file_path)
                        if isinstance(txt, str) and txt.strip():
                            chunks = [{"chunk_index": 0, "text": txt}]
                    except Exception:
                        chunks = None

                if not chunks:
                    # show error
                    if getattr(self, "_app", None) is not None and hasattr(self._app, "_new_message_dialog"):
                        dlg_msg = self._app._new_message_dialog(
                            transient_for=self._app,
                            modal=True,
                            message_type=Gtk.MessageType.ERROR,
                            buttons=Gtk.ButtonsType.OK,
                            text="Unable to extract text from the selected PDF.",
                        )
                        dlg_msg.connect("response", lambda d, r: d.destroy())
                        dlg_msg.present()
                    return

                # Import as source and compile
                name = os.path.basename(file_path)
                self.add_source(name, "pdf", chunks, source_id=f"pdf:{name}")
                GLib.idle_add(self._do_compile)
                GLib.idle_add(self._refresh_page_ui)
            finally:
                try:
                    dlg.destroy()
                except Exception:
                    pass

        dialog.connect("response", _on_response)
        dialog.present()

    def _on_merge_decision(self, btn: Gtk.Button, cid: str, members: list[str], labels: list[str]) -> None:
        now = time.time()
        latency = 0
        if cid in self._review_timestamps:
            latency = int((now - self._review_timestamps[cid]) * 1000)
        evidence = self._viewed_artifacts.get(cid, [])
        self.record_decision(cid, "merged", member_ids=members)
        self._bus.emit(
            review_decision(
                candidate_ids=members,
                candidate_labels=labels,
                chosen_id=cid,
                alternatives=[],
                decision="merged",
                confidence=0.8,
                decision_latency_ms=latency,
                evidence_viewed=evidence,
                manual_notes="",
            )
        )
        btn.set_sensitive(False)
        for mid in members:
            self._registry.resolve(mid)
        self._pipeline_results["identity_review"] = self._compute_review_data()
        self._update_review_panel()
        self._update_status()

    def _on_keep_decision(self, btn: Gtk.Button, cid: str, members: list[str], labels: list[str]) -> None:
        now = time.time()
        latency = 0
        if cid in self._review_timestamps:
            latency = int((now - self._review_timestamps[cid]) * 1000)
        evidence = self._viewed_artifacts.get(cid, [])
        self.record_decision(cid, "kept_separate", member_ids=members)
        self._bus.emit(
            review_decision(
                candidate_ids=members,
                candidate_labels=labels,
                chosen_id=cid,
                alternatives=[],
                decision="kept_separate",
                confidence=0.8,
                decision_latency_ms=latency,
                evidence_viewed=evidence,
                manual_notes="",
            )
        )
        btn.set_sensitive(False)
        self._pipeline_results["identity_review"] = self._compute_review_data()
        self._update_review_panel()
        self._update_status()

    def _on_view_provenance(self, btn: Gtk.Button, cid: str, members: list[str], labels: list[str]) -> None:
        """Open provenance viewer for this identity group."""
        evidence_key = cid
        if evidence_key not in self._viewed_artifacts:
            self._viewed_artifacts[evidence_key] = []
        self._viewed_artifacts[evidence_key].append("provenance")
        for mid in members:
            self._bus.emit(
                provenance_viewed(
                    mid,
                    self._resolve_label(mid),
                    "workspace",
                    "compilation",
                )
            )
        if self._inspect_view is not None:
            lines = [f"Provenance for group: {cid}"]
            lines.append("=" * 40)
            for mid in members:
                label = self._resolve_label(mid)
                lines.append(f"  {mid:40s} label={label}")
            lines.append(f"\nPending decisions: {len(self._decision_log)}")
            buf = self._inspect_view.get_buffer()
            buf.set_text("\n".join(lines))

    def _on_view_dependency_graph(self, btn: Gtk.Button, cid: str, labels: list[str]) -> None:
        """Open dependency graph view for this identity group."""
        evidence_key = cid
        if evidence_key not in self._viewed_artifacts:
            self._viewed_artifacts[evidence_key] = []
        self._viewed_artifacts[evidence_key].append("dependency_graph")
        edge_count = 0
        if self._compiled_ir is not None:
            for r in self._compiled_ir.relations:
                if r.source == cid or r.target == cid:
                    edge_count += 1
        self._bus.emit(dependency_graph_viewed(cid, "|".join(labels), edge_count))
        if self._inspect_view is not None:
            lines = [f"Dependency graph for: {cid}"]
            lines.append("=" * 40)
            if self._compiled_ir is not None:
                for r in self._compiled_ir.relations:
                    if r.source == cid:
                        lines.append(f"  {cid} ──{r.type}──> {r.target}")
                    elif r.target == cid:
                        lines.append(f"  {r.source} ──{r.type}──> {cid}")
            if edge_count == 0:
                lines.append("  (no relations)")
            buf = self._inspect_view.get_buffer()
            buf.set_text("\n".join(lines))

    def _on_compare_candidates(self, btn: Gtk.Button, cid: str, members: list[str], labels: list[str]) -> None:
        """Open side-by-side comparison of candidates."""
        evidence_key = cid
        if evidence_key not in self._viewed_artifacts:
            self._viewed_artifacts[evidence_key] = []
        self._viewed_artifacts[evidence_key].append("comparison")
        self._bus.emit(
            candidate_compared(
                cid,
                members[0] if members else "",
                members,
                labels,
                opened_side_by_side=True,
            )
        )
        if self._inspect_view is not None:
            lines = [f"Candidate Comparison: {cid}"]
            lines.append("=" * 50)
            for i, (mid, label) in enumerate(zip(members, labels, strict=False)):
                lines.append(f"\n--- Candidate {i + 1}: {label} ({mid}) ---")
                if self._compiled_ir is not None:
                    for a in self._compiled_ir.artifacts:
                        if a.target_identity == mid:
                            lines.append(f"  [{a.type}] {a.content_preview[:120]}")
            buf = self._inspect_view.get_buffer()
            buf.set_text("\n".join(lines))


# ====================================================================
# Kernel Observatory — live performance metrics page
# ====================================================================


def build_kernel_observatory_page() -> Gtk.Widget:
    """Build a GTK page showing live timing metrics from PerformanceRegistry.

    Auto-refreshes every 2 seconds. Displays top consumers and per-category
    breakdown with calls, total/avg/max ms.
    """
    if not _HAS_GTK:
        return Gtk.Label(label="GTK not available")

    page_scroll = Gtk.ScrolledWindow()
    page_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    page_scroll.set_hexpand(True)
    page_scroll.set_vexpand(True)
    page_scroll.add_css_class("workbench-page")

    page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    page_box.add_css_class("card")
    page_box.add_css_class("workbench-page-card")
    page_box.set_margin_top(6)
    page_box.set_margin_bottom(6)
    page_box.set_margin_start(6)
    page_box.set_margin_end(6)
    page_scroll.set_child(page_box)

    # ── Title ────────────────────────────────────────────────
    title = Gtk.Label(label="Kernel Observatory")
    title.set_halign(Gtk.Align.START)
    title.add_css_class("section-title")
    title.add_css_class("workbench-heading")
    title.set_ellipsize(Pango.EllipsizeMode.END)
    title.set_max_width_chars(120)
    subtitle = Gtk.Label(
        label="Live high-resolution timing metrics from all kernel subsystems. Auto-refreshes every 2s."
    )
    subtitle.set_halign(Gtk.Align.START)
    subtitle.set_wrap(True)
    subtitle.add_css_class("muted")
    page_box.append(title)
    page_box.append(subtitle)

    # ── Controls ─────────────────────────────────────────────
    controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    controls.add_css_class("inline-toolbar")

    reset_btn = Gtk.Button(label="Reset Stats")
    reset_btn.add_css_class("destructive-action")
    controls.append(reset_btn)

    refresh_btn = Gtk.Button(label="Refresh Now")
    refresh_btn.add_css_class("suggested-action")
    controls.append(refresh_btn)

    page_box.append(controls)

    # ── Summary bar ──────────────────────────────────────────
    summary_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
    summary_bar.set_margin_top(4)
    summary_bar.set_margin_bottom(4)
    summary_bar.add_css_class("card")
    summary_bar.add_css_class("card-tight")

    total_calls_label = Gtk.Label(label="Total calls: 0")
    total_calls_label.set_halign(Gtk.Align.START)
    total_calls_label.add_css_class("monospace")
    summary_bar.append(total_calls_label)

    total_time_label = Gtk.Label(label="Total time: 0 ms")
    total_time_label.set_halign(Gtk.Align.START)
    total_time_label.add_css_class("monospace")
    summary_bar.append(total_time_label)

    page_box.append(summary_bar)

    # ── Top consumers table ──────────────────────────────────
    top_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    top_card.add_css_class("card")
    top_card.set_margin_top(4)

    top_title = Gtk.Label(label="Top Consumers")
    top_title.set_halign(Gtk.Align.START)
    top_title.add_css_class("section-title")
    top_card.append(top_title)

    top_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    top_box.set_margin_start(8)
    top_box.set_margin_end(8)
    top_box.set_margin_top(4)
    top_box.set_margin_bottom(4)
    top_card.append(top_box)

    page_box.append(top_card)

    # ── Per-category breakdown (expanders) ───────────────────
    cat_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    cat_box.set_margin_top(4)
    page_box.append(cat_box)

    # ── Refresh logic ────────────────────────────────────────

    def _build_top_table(reg: PerformanceRegistry) -> Gtk.Widget:
        table_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        consumers = reg.top_consumers(8)
        if not consumers:
            table_box.append(Gtk.Label(label="(no data yet)", halign=Gtk.Align.START))
            return table_box
        for cat, op, total in consumers:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            cat_lbl = Gtk.Label(label=cat, halign=Gtk.Align.START)
            cat_lbl.add_css_class("monospace")
            cat_lbl.set_size_request(140, -1)
            row.append(cat_lbl)
            op_lbl = Gtk.Label(label=op, halign=Gtk.Align.START)
            op_lbl.add_css_class("monospace")
            op_lbl.set_hexpand(True)
            op_lbl.set_halign(Gtk.Align.START)
            row.append(op_lbl)
            time_lbl = Gtk.Label(
                label=f"{total:.1f} ms",
                halign=Gtk.Align.END,
            )
            time_lbl.add_css_class("monospace")
            time_lbl.set_size_request(100, -1)
            row.append(time_lbl)
            table_box.append(row)
        return table_box

    def _build_category_row(
        reg: PerformanceRegistry,
        cat: str,
        summary: dict[str, float],
    ) -> Gtk.Widget:
        cat_calls = sum(int(v) for k, v in summary.items() if k.endswith("_calls"))
        expander = Gtk.Expander(label=f"{cat}  ({cat_calls} calls)")
        expander.set_margin_start(4)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        inner.set_margin_top(4)
        inner.set_margin_start(12)

        ops = reg.stats(cat)
        for op_name, vals in sorted(ops.items()):
            calls = len(vals)
            total_ms = sum(vals)
            avg_ms = total_ms / max(calls, 1)
            max_ms = max(vals) if vals else 0.0
            op_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            op_lbl = Gtk.Label(label=op_name, halign=Gtk.Align.START)
            op_lbl.add_css_class("monospace")
            op_lbl.set_size_request(160, -1)
            op_row.append(op_lbl)

            calls_lbl = Gtk.Label(label=str(calls), halign=Gtk.Align.END)
            calls_lbl.add_css_class("monospace")
            calls_lbl.set_size_request(60, -1)
            op_row.append(calls_lbl)

            total_lbl = Gtk.Label(label=f"{total_ms:.1f}", halign=Gtk.Align.END)
            total_lbl.add_css_class("monospace")
            total_lbl.set_size_request(70, -1)
            op_row.append(total_lbl)

            avg_lbl = Gtk.Label(label=f"{avg_ms:.2f}", halign=Gtk.Align.END)
            avg_lbl.add_css_class("monospace")
            avg_lbl.set_size_request(70, -1)
            op_row.append(avg_lbl)

            max_lbl = Gtk.Label(label=f"{max_ms:.2f}", halign=Gtk.Align.END)
            max_lbl.add_css_class("monospace")
            max_lbl.set_size_request(70, -1)
            op_row.append(max_lbl)

            inner.append(op_row)

        expander.set_child(inner)
        return expander

    def _refresh_observatory() -> None:
        reg = get_performance_registry()

        # Update summary bar
        total_calls_label.set_label(f"Total calls: {reg.total_calls}")
        total_time_label.set_label(f"Total time: {reg.total_time_ms:.1f} ms")

        # Rebuild top consumers
        while True:
            child = top_box.get_first_child()
            if child is None:
                break
            top_box.remove(child)
        top_box.append(_build_top_table(reg))

        # Rebuild category expanders
        while True:
            child = cat_box.get_first_child()
            if child is None:
                break
            cat_box.remove(child)
        for cat in reg.categories:
            summary = reg.summary(cat).get(cat, {})
            cat_box.append(_build_category_row(reg, cat, summary))
        if not reg.categories:
            empty_label = Gtk.Label(
                label="No timing data yet — run a compilation or study session.",
                halign=Gtk.Align.START,
            )
            empty_label.add_css_class("muted")
            cat_box.append(empty_label)

    refresh_btn.connect("clicked", lambda b: _refresh_observatory())

    def _on_reset(_b: Any) -> None:
        get_performance_registry().reset()
        _refresh_observatory()

    reset_btn.connect("clicked", _on_reset)

    # Auto-refresh timer (2s)
    _refresh_observatory()

    def _timer_tick() -> bool:
        _refresh_observatory()
        return True

    GLib.timeout_add(2000, _timer_tick)

    return page_scroll
