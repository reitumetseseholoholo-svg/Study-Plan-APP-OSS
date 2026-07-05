from types import SimpleNamespace, ModuleType
import sys


# Inject lightweight stubs for heavy provenance modules so tests run in CI
def _make_stub_modules():
    mods = {}
    mods["studyplan.provenance.cir"] = ModuleType("studyplan.provenance.cir")
    mods["studyplan.provenance.cir"].__dict__["CognitiveIR"] = object

    mods["studyplan.provenance.cir.container"] = ModuleType("studyplan.provenance.cir.container")
    mods["studyplan.provenance.cir.container"].__dict__["validate_ir"] = lambda ir: SimpleNamespace(
        valid=True, errors=[], warnings=[]
    )

    mods["studyplan.provenance.cir.passes"] = ModuleType("studyplan.provenance.cir.passes")
    mods["studyplan.provenance.cir.passes"].__dict__["run_passes"] = lambda ir: ir

    # Minimal compilation plugin stubs
    comp_mod = ModuleType("studyplan.provenance.lab.compilation")

    class CIRMerger:
        def merge(self, fragments):
            class IR:
                def __init__(self, fragments):
                    self.identities = []
                    self.artifacts = []
                    self.relations = []
                    self.version = "0"

            self.last_report = {"merged": True}
            return IR(fragments)

    comp_mod.__dict__["CIRMerger"] = CIRMerger
    comp_mod.__dict__["PDFFrontendPlugin"] = lambda: None
    comp_mod.__dict__["NotesFrontendPlugin"] = lambda: None
    comp_mod.__dict__["FMKnowledgeBasePlugin"] = lambda: None
    mods["studyplan.provenance.lab.compilation"] = comp_mod

    # Identity v2 stubs
    id_mod = ModuleType("studyplan.provenance.lab.compilation.identity_v2")

    class GlobalIdentityRegistry:
        def __init__(self, scorer=None):
            self._identities = {}
            self._local_to_canonical = {}
            self._label_to_canonical = {}

        def all_canonical_ids(self):
            return list(self._identities.keys())

        def get_canonical(self, cid):
            return self._identities.get(cid)

        def register(self, *args, **kwargs):
            return None

        def resolve(self, mid):
            return None

    id_mod.__dict__["GlobalIdentityRegistry"] = GlobalIdentityRegistry
    id_mod.__dict__["SemanticEquivalenceScorer"] = lambda: None
    id_mod.__dict__["ProvenanceWeightedIdentity"] = SimpleNamespace
    id_mod.__dict__["make_weighted"] = lambda *a, **k: SimpleNamespace()
    mods["studyplan.provenance.lab.compilation.identity_v2"] = id_mod

    mods["studyplan.provenance.lab.compilation.fragment"] = ModuleType("studyplan.provenance.lab.compilation.fragment")
    mods["studyplan.provenance.lab.compilation.fragment"].__dict__["CIRFragment"] = object

    # Other support stubs
    mods["studyplan.provenance.learning.compiler_bridge"] = ModuleType("studyplan.provenance.learning.compiler_bridge")
    mods["studyplan.provenance.learning.compiler_bridge"].__dict__["get_compiler_bus"] = lambda: SimpleNamespace(history=lambda: [])

    mods["studyplan.provenance.kernel.performance"] = ModuleType("studyplan.provenance.kernel.performance")
    mods["studyplan.provenance.kernel.performance"].__dict__["get_performance_registry"] = lambda: SimpleNamespace()

    mods["studyplan.provenance.learning.events"] = ModuleType("studyplan.provenance.learning.events")
    for name in [
        "source_imported",
        "compilation_started",
        "extraction_completed",
        "ambiguity_detected",
        "merge_candidate",
        "review_decision",
        "publish_completed",
        "review_opened",
        "provenance_viewed",
        "dependency_graph_viewed",
        "candidate_compared",
        "review_abandoned",
    ]:
        mods["studyplan.provenance.learning.events"].__dict__[name] = (lambda *a, **k: None)

    mods["studyplan.provenance.learning.cognitive_projection"] = ModuleType(
        "studyplan.provenance.learning.cognitive_projection"
    )
    mods["studyplan.provenance.learning.cognitive_projection"].__dict__["CognitiveProjectionEngine"] = lambda: SimpleNamespace(
        project=lambda events: SimpleNamespace(event_count=0)
    )
    mods["studyplan.provenance.learning.cognitive_projection"].__dict__["CognitiveProjection"] = SimpleNamespace

    mods["studyplan.provenance.cognition.controller"] = ModuleType("studyplan.provenance.cognition.controller")
    mods["studyplan.provenance.cognition.controller"].__dict__["CognitiveController"] = lambda: SimpleNamespace(
        evaluate=lambda proj, dependency_graph=None: SimpleNamespace(is_empty=True, best=None, interventions=[])
    )
    mods["studyplan.provenance.cognition.controller"].__dict__["ForwardModel"] = lambda *a, **k: SimpleNamespace(
        calibration_confidence={}
    )
    mods["studyplan.provenance.cognition.controller"].__dict__["InterventionRanking"] = SimpleNamespace

    mods["studyplan.provenance.cognition.outcome"] = ModuleType("studyplan.provenance.cognition.outcome")
    mods["studyplan.provenance.cognition.outcome"].__dict__["compute_closed_loop_outcomes"] = lambda events: []

    mods["studyplan.provenance.lab.integration"] = ModuleType("studyplan.provenance.lab.integration")
    mods["studyplan.provenance.lab.integration"].__dict__["push_identity_aliases"] = lambda *a, **k: None

    # Register into sys.modules
    for name, mod in mods.items():
        sys.modules[name] = mod


_make_stub_modules()

from studyplan.provenance.lab.compilation_workspace import CompilationWorkspace  # noqa: E402


def test_gir_persistence_round_trip(tmp_path):
    base = str(tmp_path)
    cw = CompilationWorkspace(app_ref=None)

    # Inject a fake identity into the registry
    cw._registry._identities = {
        "c1": SimpleNamespace(
            id="c1",
            type="concept",
            label="Foo",
            confidence=0.9,
            source_trust=0.8,
            first_seen="2026-01-01",
            lineage=("pdf:doc",),
            metadata={"k": "v"},
        )
    }
    cw._registry._local_to_canonical = {"local1": "c1"}

    cw.persist_gir(base_path=base)

    # Clear and reload
    cw._registry._identities = {}
    cw._registry._local_to_canonical = {}
    cw.load_persisted_gir(base_path=base)

    assert "c1" in cw._registry._identities
    assert cw._registry._local_to_canonical.get("local1") == "c1"


def test_review_decisions_persistence_round_trip(tmp_path):
    base = str(tmp_path)
    cw = CompilationWorkspace(app_ref=None)

    cw._decision_log = [{"local_id": "local1", "decision": "merged"}]
    cw._identity_decisions = {"local1": "merged"}

    cw.persist_review_decisions(base_path=base)

    cw._decision_log = []
    cw._identity_decisions = {}
    cw.load_review_decisions(base_path=base)

    assert cw._decision_log
    assert cw._identity_decisions.get("local1") == "merged"
