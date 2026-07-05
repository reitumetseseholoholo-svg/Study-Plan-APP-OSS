"""Universal Domain Registry — live concept→ViewState mapping with auto-compile.

Essentialist Question:
    What phenomenon does a domain registry exist to preserve?
Answer:
    Registration-compilation coherence — the property that every declared
    domain concept immediately has a compiled, queryable ViewState without
    any separate compilation step.

Hypothesis H-UDR-01:
    A live registry that auto-compiles FormulaDecl → ViewState on registration
    eliminates the lazy-compilation gap between the DSL formula registry and
    provenance queries. No manual compilation step or separate ALL_TOPICS
    maintenance is needed.

Predictions:
    P1: Every formula registered via declare_formula() is immediately
        queryable via the DomainRegistry without any side band.
    P2: auto_register_fm_domain + FastDomainCompiler compiles all 11+ formulas
        without errors in <2s total.
    P3: registry_to_domainspecs() + DomainRegistry produce identical ViewStates
        (determinism across compilation paths).
    P4: Cross-concept dependency queries work — collect_inherited_constraints
        for a formula that depends on another formula returns constraints
        from both.
    P5: The registry can accept dynamically-registered formulas at runtime
        (not just module-load time).

Falsification conditions:
    F1: A FormulaDecl compiles to a ViewState that fails iR1 connectivity
        (dangling artifact references).
    F2: Two registrations of the same concept_id produce different ViewStates
        (non-determinism).
    F3: collect_inherited_constraints misses a constraint from a dependency
        that was compiled earlier.
    F4: Registry exceed 500ms for 25+ formulas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from studyplan.provenance.kernel import ViewState, collect_inherited_constraints
from studyplan.provenance.fast_compiler import (
    DomainSpec,
    FastDomainCompiler,
)
from studyplan.provenance.formula_bridge import (
    formula_to_domainspec,
    formula_chain_to_domainspec,
    auto_register_fm_domain,
    _try_extract_chain_steps,
    _default_output_id,
)
from studyplan.provenance.execution import ExecutionContext


# ---- Compiled entry ----


@dataclass
class DomainEntry:
    """A compiled domain concept entry — the universal provenance unit.

    Every registered concept produces one DomainEntry containing its
    declarative source (FormulaDecl), its compiler IR (DomainSpec), its
    compiled representation (ViewState), and query metadata.

    Immutable after construction. Used by Tutor, Debugger, Lab, and
    Observatory from the same code path.
    """

    concept_id: str
    viewstate: ViewState
    spec: DomainSpec
    output_artifact_id: str
    compilation_time_ms: float = 0.0
    spec_hash: str = ""
    validation_pass: bool = False

    def query_assumptions(self) -> dict[str, Any]:
        """Quick assumption query via ExecutionContext."""
        ctx = ExecutionContext(self.viewstate)
        return ctx.inherited_assumptions_fast(self.output_artifact_id)

    def inherited_constraints(self) -> set[tuple[str, str]]:
        """All constraints inherited from transitive dependencies."""
        return collect_inherited_constraints(self.viewstate, self.output_artifact_id)


# ---- Live Domain Registry ----


class DomainRegistry:
    """Live registry of compiled domain concepts.

    Maintains concept_id → DomainEntry mapping. Auto-compiles from
    FormulaDecl on registration. Supports batch sync from the formula
    registry and incremental registration at runtime.

    This is the universal provenance gateway: every declared concept
    anywhere in the system is immediately queryable here.
    """

    def __init__(self, compiler: FastDomainCompiler | None = None):
        self._entries: dict[str, DomainEntry] = {}
        self._compiler = compiler or FastDomainCompiler()
        self._execution_cache: dict[str, dict[str, Any]] = {}
        self._assumption_cache: dict[str, set[tuple[str, str]]] = {}

        if "fm" not in self._compiler.registry.known_domains:
            self._compiler.registry = auto_register_fm_domain(self._compiler.registry)

    # ---- Registration ----

    def register(self, concept_id: str, decl: Any) -> DomainEntry:
        """Register and auto-compile a FormulaDecl.

        Compiles FormulaDecl → DomainSpec → ViewState via the
        formula bridge + FastDomainCompiler. Validates the result.
        """
        chain_steps = _try_extract_chain_steps(decl)
        if chain_steps is not None:
            spec = formula_chain_to_domainspec(concept_id, decl, chain_steps)
        else:
            spec = formula_to_domainspec(concept_id, decl)

        vs, record = self._compiler.compile(spec)
        target_id = decl.output_slot or _default_output_id(concept_id)

        entry = DomainEntry(
            concept_id=concept_id,
            viewstate=vs,
            spec=spec,
            output_artifact_id=target_id,
            compilation_time_ms=record.compilation_time_ms,
            spec_hash=record.spec_hash,
            validation_pass=record.validation.get("pass", False),
        )

        self._entries[concept_id] = entry
        self._execution_cache.pop(concept_id, None)
        self._assumption_cache.pop(concept_id, None)
        return entry

    def register_spec(self, spec: DomainSpec) -> DomainEntry:
        """Register a pre-built DomainSpec directly.

        For use when a DomainSpec is constructed outside the formula
        bridge (e.g. from the old ALL_TOPICS or hand-authored specs).
        """
        vs, record = self._compiler.compile(spec)
        concept_id = spec.id
        output_ids = [n.id for n in spec.nodes if n.kind == "output"]
        target_id = output_ids[0] if output_ids else concept_id

        entry = DomainEntry(
            concept_id=concept_id,
            viewstate=vs,
            spec=spec,
            output_artifact_id=target_id,
            compilation_time_ms=record.compilation_time_ms,
            spec_hash=record.spec_hash,
            validation_pass=record.validation.get("pass", False),
        )

        self._entries[concept_id] = entry
        self._execution_cache.pop(concept_id, None)
        self._assumption_cache.pop(concept_id, None)
        return entry

    def sync_from_formula_registry(self) -> int:
        """Batch-compile all formulas from the formula registry.

        Only compiles concepts not already registered. Calling this
        multiple times is safe (idempotent).

        Returns the number of new entries compiled.
        """
        from studyplan.domain_reasoning.formula_registry import get_registry

        registry = get_registry()
        count = 0
        for concept_id, decl in registry.items():
            if concept_id not in self._entries:
                try:
                    self.register(concept_id, decl)
                    count += 1
                except Exception:
                    pass
        return count

    def sync_from_all_topics(self) -> int:
        """Batch-compile the 5 hand-authored ALL_TOPICS specs.

        Returns the number of new entries compiled.
        """
        from studyplan.provenance.compiler_spec import ALL_TOPICS
        from studyplan.provenance.fast_compiler import (
            DomainNode,
            DomainEdge,
        )

        count = 0
        for topic_id, tspec in ALL_TOPICS.items():
            if topic_id in self._entries:
                continue
            nodes = []
            for p in tspec.parameters:
                concept = p.get("metadata", {}).get("semantic_role", "config_value")
                nodes.append(
                    DomainNode(
                        id=p["id"],
                        concept=concept,
                        kind="parameter",
                        target=p.get("target", p["id"]),
                        metadata=p.get("metadata", {}),
                    )
                )
            for o in tspec.outputs:
                concept = o.get("metadata", {}).get("semantic_role", "call_graph_region")
                kind = "intermediate"
                if o["id"] == tspec.outputs[-1]["id"]:
                    kind = "output"
                nodes.append(
                    DomainNode(
                        id=o["id"],
                        concept=concept,
                        kind=kind,
                        target=o.get("target", o["id"]),
                        metadata=o.get("metadata", {}),
                    )
                )
            edges = []
            for c in tspec.computations:
                edges.append(
                    DomainEdge(
                        id=c.id,
                        from_id=c.input_artifact_id,
                        to_id=c.output_artifact_id,
                        rule=c.rule_spec,
                        semantics=c.transformation_type,
                        assumptions=c.assumptions,
                        consumes=c.consumes,
                    )
                )
            spec = DomainSpec(
                id=topic_id,
                title=tspec.title,
                domain="fm",
                nodes=tuple(nodes),
                edges=tuple(edges),
                metadata={"source": "all_topics_rebuild"},
            )
            self.register_spec(spec)
            count += 1
        return count

    # ---- Topic resolution ----

    @staticmethod
    def resolve_topic_key(topic: str) -> str:
        """Normalize app topic name to a provenance key.

        Checks ALL_TOPICS then formula registry. Delegates to the
        unified resolve_topic_key in formula_bridge.
        """
        from studyplan.provenance.formula_bridge import resolve_topic_key

        return resolve_topic_key(topic)

    # ---- Query ----

    def get(self, concept_id: str) -> DomainEntry | None:
        return self._entries.get(concept_id)

    def get_viewstate(self, concept_id: str) -> ViewState | None:
        entry = self._entries.get(concept_id)
        return entry.viewstate if entry else None

    def query_assumptions(self, concept_id: str) -> dict[str, Any] | None:
        """Query inherited assumptions for a compiled concept.

        Returns formatted dict with assumptions, consumes, dependency_path.
        Caches results after first query for performance.
        """
        if concept_id in self._execution_cache:
            return self._execution_cache[concept_id]

        entry = self._entries.get(concept_id)
        if entry is None:
            return None

        ctx = ExecutionContext(entry.viewstate)
        data = ctx.inherited_assumptions_fast(entry.output_artifact_id)
        self._execution_cache[concept_id] = data
        return data

    def query_inherited_constraints(
        self,
        concept_id: str,
    ) -> set[tuple[str, str]] | None:
        """All constraints inherited from transitive dependencies.

        Uses the kernel primitive collect_inherited_constraints.
        """
        if concept_id in self._assumption_cache:
            return self._assumption_cache[concept_id]

        entry = self._entries.get(concept_id)
        if entry is None:
            return None

        constraints = collect_inherited_constraints(entry.viewstate, entry.output_artifact_id)
        self._assumption_cache[concept_id] = constraints
        return constraints

    def query_dependency_path(self, concept_id: str) -> list[str] | None:
        """Dependency path from base parameters to output."""
        data = self.query_assumptions(concept_id)
        if data is None:
            return None
        return list(data.get("dependency_path", []))

    def all_entries(self) -> dict[str, DomainEntry]:
        return dict(self._entries)

    # ---- Registration hook (for FormulaDecl) ----

    @staticmethod
    def install_registration_hook(
        registry: DomainRegistry | None = None,
    ) -> DomainRegistry:
        """Install a hook into the formula registry that auto-compiles
        every new FormulaDecl on registration.

        Returns the DomainRegistry instance (creates one if None).
        """
        from studyplan.domain_reasoning import formula_registry

        dr = registry or DomainRegistry()

        original_declare = formula_registry.declare_formula
        original_chain = formula_registry.declare_formula_chain

        def _hooked_declare(concept_id, **kwargs):
            decl = original_declare(concept_id, **kwargs)
            try:
                dr.register(concept_id, decl)
            except Exception:
                pass
            return decl

        def _hooked_chain(concept_id, **kwargs):
            decl = original_chain(concept_id, **kwargs)
            try:
                dr.register(concept_id, decl)
            except Exception:
                pass
            return decl

        formula_registry.declare_formula = _hooked_declare
        formula_registry.declare_formula_chain = _hooked_chain
        return dr

    # ---- Properties ----

    @property
    def concept_ids(self) -> frozenset[str]:
        return frozenset(self._entries)

    @property
    def count(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        self._entries.clear()
        self._execution_cache.clear()
        self._assumption_cache.clear()


# ---- Global instance for app-wide use ----


_DEFAULT_REGISTRY: DomainRegistry | None = None


def get_default_registry() -> DomainRegistry:
    """Get or create the app-wide default DomainRegistry.

    On first call, syncs from formula registry and ALL_TOPICS.
    Subsequent calls return the cached instance.
    """
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        dr = DomainRegistry()
        dr.sync_from_formula_registry()
        dr.sync_from_all_topics()
        _DEFAULT_REGISTRY = dr
    return _DEFAULT_REGISTRY


def reset_default_registry() -> None:
    """Reset the default registry (for testing)."""
    global _DEFAULT_REGISTRY
    _DEFAULT_REGISTRY = None
