"""Domain loaders: convert domain-specific representations to ViewState data."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import json

from studyplan.provenance.kernel.types import Artifact, Transformation, ViewState


# --- Base loader interface ---


@dataclass
class ViewStateDataSource:
    """Container for parsed domain data ready to be loaded into a ViewState."""

    artifacts: list[Artifact] = field(default_factory=list)
    transforms: list[Transformation] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def build(self) -> ViewState:
        return ViewState(
            artifact_space=frozenset(self.artifacts),
            transform_space=frozenset(self.transforms),
        )

    def __len__(self) -> int:
        return len(self.artifacts) + len(self.transforms)


# --- JSON-based generic loader ---


def load_json(path: str) -> ViewStateDataSource:
    """Load ViewState data from a JSON file.

    Expected JSON structure:
    {
      "metadata": { ... },
      "artifacts": [
        {"id": "...", "type": "...", "target": "...", "metadata": {...}}
      ],
      "transforms": [
        {
          "id": "...", "input_artifact_id": "...", "output_artifact_id": "...",
          "transformation_type": "...", "rule_spec": "...",
          "constraints": [["key", "val"], ...]
        }
      ]
    }
    """
    with open(path) as f:
        data = json.load(f)

    artifacts = []
    for a in data.get("artifacts", []):
        meta = a.get("metadata", {})
        meta_pairs = tuple(sorted((k, v) for k, v in meta.items()))
        artifacts.append(
            Artifact(
                id=a["id"],
                type=a["type"],
                target=a["target"],
                metadata=meta_pairs,
            )
        )

    transforms = []
    for t in data.get("transforms", []):
        constraints = tuple(tuple(c) for c in t.get("constraints", []))
        transforms.append(
            Transformation(
                id=t["id"],
                input_artifact_id=t["input_artifact_id"],
                output_artifact_id=t["output_artifact_id"],
                transformation_type=t["transformation_type"],
                rule_spec=t["rule_spec"],
                constraints=constraints,
            )
        )

    return ViewStateDataSource(
        artifacts=artifacts,
        transforms=transforms,
        metadata=data.get("metadata", {}),
    )


# --- PostgreSQL query optimizer (PV03 domain) ---


def build_pg_optimizer_data() -> ViewStateDataSource:
    """Build the PostgreSQL query optimizer domain data from PV03 specification."""
    artifacts = [
        Artifact(
            id="standard_planner",
            type="call_graph_region",
            target="src/backend/optimizer/plan/planner.c (standard_planner)",
            metadata=(("role", "top_level_entry"),),
        ),
        Artifact(
            id="hashjoin_node",
            type="ast_node",
            target="HashJoin(MergeSort(a), MergeSort(b))",
            metadata=(
                ("join_type", "hash"),
                ("cost", "100"),
            ),
        ),
        Artifact(
            id="mergejoin_node",
            type="ast_node",
            target="MergeJoin(Sort(a), Sort(b))",
            metadata=(
                ("join_type", "merge"),
                ("cost", "120"),
            ),
        ),
        Artifact(
            id="nestedloop_node",
            type="ast_node",
            target="NestedLoop(SeqScan(a), SeqScan(b))",
            metadata=(
                ("join_type", "nested_loop"),
                ("cost", "80"),
            ),
        ),
        Artifact(
            id="subquery_planner",
            type="call_graph_region",
            target="subquery_planner (entry point for subquery flattening)",
            metadata=(("phase", "subquery_flatten"),),
        ),
        Artifact(
            id="plan_join_queries",
            type="call_graph_region",
            target="plan_join_queries (join planning entry)",
            metadata=(("phase", "join_planning"),),
        ),
        Artifact(
            id="from_clause",
            type="ast_node",
            target="FROM clause (table join set)",
            metadata=(("kind", "from_clause"),),
        ),
        Artifact(
            id="plan_tree_dp",
            type="ast_node",
            target="Plan tree (optimized join order via DP)",
            metadata=(
                ("method", "dp"),
                ("cost", "90"),
            ),
        ),
        Artifact(
            id="plan_tree_geqo",
            type="ast_node",
            target="Plan tree (optimized join order via GEQO)",
            metadata=(
                ("method", "geqo"),
                ("cost", "95"),
            ),
        ),
        Artifact(
            id="joinpath_c",
            type="file_pattern",
            target="src/backend/optimizer/paths/joinpath.c",
            metadata=(("module", "join_paths"),),
        ),
        Artifact(
            id="geqo_main_c",
            type="file_pattern",
            target="src/backend/optimizer/geqo/geqo_main.c",
            metadata=(("module", "geqo"),),
        ),
        Artifact(
            id="planner_c",
            type="file_pattern",
            target="src/backend/optimizer/plan/planner.c",
            metadata=(("module", "planner"),),
        ),
        Artifact(
            id="grouping_planner",
            type="call_graph_region",
            target="grouping_planner (aggregation and grouping)",
            metadata=(("phase", "grouping"),),
        ),
    ]

    transforms = [
        # Structural edges (call graph)
        Transformation(
            id="call_std_sub",
            input_artifact_id="standard_planner",
            output_artifact_id="subquery_planner",
            transformation_type="call",
            rule_spec="standard_planner calls subquery_planner for subquery handling",
        ),
        Transformation(
            id="call_std_group",
            input_artifact_id="standard_planner",
            output_artifact_id="grouping_planner",
            transformation_type="call",
            rule_spec="standard_planner calls grouping_planner for aggregation",
        ),
        Transformation(
            id="call_sub_join",
            input_artifact_id="subquery_planner",
            output_artifact_id="plan_join_queries",
            transformation_type="call",
            rule_spec="subquery_planner calls plan_join_queries after flattening",
        ),
        Transformation(
            id="call_std_joinpath",
            input_artifact_id="standard_planner",
            output_artifact_id="joinpath_c",
            transformation_type="call",
            rule_spec="standard_planner depends on join path generation in joinpath.c",
        ),
        # Equivalence mapping
        Transformation(
            id="eq_hash_merge",
            input_artifact_id="hashjoin_node",
            output_artifact_id="mergejoin_node",
            transformation_type="equivalence_mapping",
            rule_spec="Join commutativity: HashJoin and MergeJoin with same keys are equivalent",
            constraints=(("condition", "join keys identical"),),
        ),
        # Ordering mapping
        Transformation(
            id="order_sub_planjoin",
            input_artifact_id="subquery_planner",
            output_artifact_id="plan_join_queries",
            transformation_type="ordering_mapping",
            rule_spec="Subquery flattening completes before join planning begins",
            constraints=(("ordering", "subquery_planner → plan_join_queries"),),
        ),
        # Decision mapping
        Transformation(
            id="dec_nl",
            input_artifact_id="from_clause",
            output_artifact_id="nestedloop_node",
            transformation_type="decision_mapping",
            rule_spec="Nested loop chosen when inner relation size < threshold",
            constraints=(("condition", "cost(nested_loop) < cost(hash_join)"),),
        ),
        # Generative mappings (DP and GEQO)
        Transformation(
            id="gen_dp",
            input_artifact_id="from_clause",
            output_artifact_id="plan_tree_dp",
            transformation_type="generative_mapping",
            rule_spec="DP search produces optimal Plan tree via dynamic programming",
        ),
        Transformation(
            id="gen_geqo",
            input_artifact_id="from_clause",
            output_artifact_id="plan_tree_geqo",
            transformation_type="generative_mapping",
            rule_spec="Genetic algorithm produces near-optimal Plan tree via randomized search",
            constraints=(("activation", "join_count > 12"),),
        ),
        # Additional structural edges within the optimizer
        Transformation(
            id="call_std_geqo",
            input_artifact_id="standard_planner",
            output_artifact_id="geqo_main_c",
            transformation_type="call",
            rule_spec="standard_planner delegates to GEQO when join count exceeds threshold",
        ),
        # Generative mapping for standard_planner producing a plan tree
        Transformation(
            id="gen_planner_to_plan",
            input_artifact_id="standard_planner",
            output_artifact_id="plan_tree_dp",
            transformation_type="generative_mapping",
            rule_spec="standard_planner produces optimized plan via full optimizer pipeline",
        ),
    ]

    return ViewStateDataSource(
        artifacts=artifacts,
        transforms=transforms,
        metadata={
            "domain": "postgresql_optimizer",
            "source": "PV03 locked predictions",
            "version": "PostgreSQL 17",
            "prediction_ids": ["PV03-OPT-P1", "PV03-OPT-P2", "PV03-OPT-P3", "PV03-OPT-P4", "PV03-OPT-P5"],
        },
    )


# --- LLVM IR basic block domain ---


def build_llvm_ir_data() -> ViewStateDataSource:
    """Build LLVM IR basic block graph with control flow."""
    # Basic blocks
    artifacts = [
        Artifact(
            id="bb_entry", type="control_flow_pattern", target="entry: entry_block", metadata=(("function", "main"),)
        ),
        Artifact(
            id="bb_loop_header",
            type="control_flow_pattern",
            target="loop: loop_header",
            metadata=(("function", "main"), ("loop_depth", "1")),
        ),
        Artifact(
            id="bb_loop_body",
            type="control_flow_pattern",
            target="loop: loop_body",
            metadata=(("function", "main"), ("loop_depth", "2")),
        ),
        Artifact(
            id="bb_loop_latch",
            type="control_flow_pattern",
            target="loop: loop_latch",
            metadata=(("function", "main"), ("loop_depth", "2")),
        ),
        Artifact(
            id="bb_exit", type="control_flow_pattern", target="exit: exit_block", metadata=(("function", "main"),)
        ),
        Artifact(
            id="bb_cond_false",
            type="control_flow_pattern",
            target="branch: cond_false",
            metadata=(("function", "main"),),
        ),
        # Instructions as data_flow_edges
        Artifact(id="inst_add", type="data_flow_edge", target="%sum = add i32 %a, %b", metadata=(("opcode", "add"),)),
        Artifact(id="inst_mul", type="data_flow_edge", target="%prod = mul i32 %a, %b", metadata=(("opcode", "mul"),)),
        Artifact(
            id="inst_icmp", type="data_flow_edge", target="%cmp = icmp slt i32 %a, %b", metadata=(("opcode", "icmp"),)
        ),
        # Function
        Artifact(
            id="func_main",
            type="symbol_table_entry",
            target="main: i32 (i32, i8**)",
            metadata=(("return_type", "i32"),),
        ),
    ]

    transforms = [
        # Control flow edges
        Transformation(
            id="cf_entry_loop",
            input_artifact_id="bb_entry",
            output_artifact_id="bb_loop_header",
            transformation_type="data_flow",
            rule_spec="entry → loop header (always taken)",
        ),
        Transformation(
            id="cf_loop_header_body",
            input_artifact_id="bb_loop_header",
            output_artifact_id="bb_loop_body",
            transformation_type="data_flow",
            rule_spec="loop header → loop body (loop taken)",
        ),
        Transformation(
            id="cf_loop_latch_header",
            input_artifact_id="bb_loop_latch",
            output_artifact_id="bb_loop_header",
            transformation_type="data_flow",
            rule_spec="loop latch → loop header (back edge)",
        ),
        Transformation(
            id="cf_loop_body_latch",
            input_artifact_id="bb_loop_body",
            output_artifact_id="bb_loop_latch",
            transformation_type="data_flow",
            rule_spec="loop body → loop latch",
        ),
        Transformation(
            id="cf_loop_header_exit",
            input_artifact_id="bb_loop_header",
            output_artifact_id="bb_exit",
            transformation_type="data_flow",
            rule_spec="loop header → exit (loop condition false)",
        ),
        Transformation(
            id="cf_entry_false",
            input_artifact_id="bb_entry",
            output_artifact_id="bb_cond_false",
            transformation_type="data_flow",
            rule_spec="entry → cond_false (alternate branch)",
        ),
        # Data flow edges between instructions
        Transformation(
            id="df_add_to_mul",
            input_artifact_id="inst_add",
            output_artifact_id="inst_mul",
            transformation_type="data_flow",
            rule_spec="add result used by mul",
        ),
        Transformation(
            id="df_icmp_use",
            input_artifact_id="inst_icmp",
            output_artifact_id="bb_loop_header",
            transformation_type="data_flow",
            rule_spec="icmp result controls branch in loop header",
        ),
    ]

    return ViewStateDataSource(
        artifacts=artifacts,
        transforms=transforms,
        metadata={
            "domain": "llvm_ir",
            "source": "LLVM IR basic block control flow graph",
            "language": "C",
        },
    )


# --- GUI component tree domain ---


def build_gui_data() -> ViewStateDataSource:
    """Build a GTK4 GUI component hierarchy."""
    artifacts = [
        Artifact(
            id="window",
            type="ast_node",
            target="MainWindow(Gtk.ApplicationWindow)",
            metadata=(("class", "Gtk.ApplicationWindow"),),
        ),
        Artifact(
            id="header_bar", type="ast_node", target="HeaderBar(Gtk.HeaderBar)", metadata=(("class", "Gtk.HeaderBar"),)
        ),
        Artifact(
            id="sidebar",
            type="ast_node",
            target="Sidebar(Gtk.Box)",
            metadata=(("class", "Gtk.Box"), ("orientation", "vertical")),
        ),
        Artifact(
            id="main_content",
            type="ast_node",
            target="MainContent(Gtk.Box)",
            metadata=(("class", "Gtk.Box"), ("orientation", "horizontal")),
        ),
        Artifact(
            id="status_bar",
            type="ast_node",
            target="StatusBar(Gtk.Box)",
            metadata=(("class", "Gtk.Box"), ("orientation", "horizontal")),
        ),
        Artifact(
            id="button_start",
            type="ast_node",
            target="StartButton(Gtk.Button)",
            metadata=(("class", "Gtk.Button"), ("label", "Start")),
        ),
        Artifact(
            id="button_stop",
            type="ast_node",
            target="StopButton(Gtk.Button)",
            metadata=(("class", "Gtk.Button"), ("label", "Stop")),
        ),
        Artifact(
            id="label_status",
            type="ast_node",
            target="StatusLabel(Gtk.Label)",
            metadata=(("class", "Gtk.Label"), ("text", "Ready")),
        ),
        Artifact(
            id="list_view", type="ast_node", target="ItemList(Gtk.ListView)", metadata=(("class", "Gtk.ListView"),)
        ),
        Artifact(
            id="scroll",
            type="ast_node",
            target="ScrollArea(Gtk.ScrolledWindow)",
            metadata=(("class", "Gtk.ScrolledWindow"),),
        ),
        Artifact(id="stack", type="ast_node", target="ViewStack(Gtk.Stack)", metadata=(("class", "Gtk.Stack"),)),
    ]

    transforms = [
        # parent_child structural edges
        Transformation(
            id="pc_window_header",
            input_artifact_id="window",
            output_artifact_id="header_bar",
            transformation_type="parent_child",
            rule_spec="window contains header_bar",
        ),
        Transformation(
            id="pc_window_sidebar",
            input_artifact_id="window",
            output_artifact_id="sidebar",
            transformation_type="parent_child",
            rule_spec="window contains sidebar",
        ),
        Transformation(
            id="pc_window_main",
            input_artifact_id="window",
            output_artifact_id="main_content",
            transformation_type="parent_child",
            rule_spec="window contains main_content",
        ),
        Transformation(
            id="pc_window_status",
            input_artifact_id="window",
            output_artifact_id="status_bar",
            transformation_type="parent_child",
            rule_spec="window contains status_bar",
        ),
        Transformation(
            id="pc_sidebar_list",
            input_artifact_id="sidebar",
            output_artifact_id="scroll",
            transformation_type="parent_child",
            rule_spec="sidebar contains scroll area",
        ),
        Transformation(
            id="pc_scroll_list",
            input_artifact_id="scroll",
            output_artifact_id="list_view",
            transformation_type="parent_child",
            rule_spec="scroll area contains list view",
        ),
        Transformation(
            id="pc_main_stack",
            input_artifact_id="main_content",
            output_artifact_id="stack",
            transformation_type="parent_child",
            rule_spec="main content area contains stack",
        ),
        Transformation(
            id="pc_stack_start",
            input_artifact_id="stack",
            output_artifact_id="button_start",
            transformation_type="parent_child",
            rule_spec="stack contains start button",
        ),
        Transformation(
            id="pc_stack_stop",
            input_artifact_id="stack",
            output_artifact_id="button_stop",
            transformation_type="parent_child",
            rule_spec="stack contains stop button",
        ),
        Transformation(
            id="pc_status_label",
            input_artifact_id="status_bar",
            output_artifact_id="label_status",
            transformation_type="parent_child",
            rule_spec="status bar contains label",
        ),
        # Signal edges (call — event-driven)
        Transformation(
            id="sig_start_click",
            input_artifact_id="button_start",
            output_artifact_id="label_status",
            transformation_type="call",
            rule_spec="clicked signal on start button updates status label",
        ),
    ]

    return ViewStateDataSource(
        artifacts=artifacts,
        transforms=transforms,
        metadata={
            "domain": "gui_gtk4",
            "source": "GTK4 component hierarchy",
            "framework": "GTK4",
        },
    )
