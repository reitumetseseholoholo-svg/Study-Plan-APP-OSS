import datetime
from typing import Any, Dict, List

from studyplan_ai_tutor import build_rag_concept_graph


def test_build_rag_concept_graph_empty_input() -> None:
    graph = build_rag_concept_graph([])
    assert isinstance(graph, dict)
    meta = graph.get("meta", {})
    assert meta.get("term_count") == 0
    assert meta.get("snippet_count") == 0
    assert meta.get("edge_count") == 0


def test_build_rag_concept_graph_basic_terms_and_edges() -> None:
    snippets: List[Dict[str, Any]] = [
        {
            "id": "S1",
            "text": "WACC combines equity and debt costs after tax for investment appraisal.",
        },
        {
            "id": "S2",
            "text": "NPV discounts future cash flows using a discount rate such as WACC.",
        },
    ]
    graph = build_rag_concept_graph(snippets, max_terms=10, min_term_freq=1)
    terms = graph.get("terms", [])
    snippets_nodes = graph.get("snippets", [])
    edges = graph.get("edges", [])

    assert isinstance(terms, list) and terms
    assert isinstance(snippets_nodes, list) and len(snippets_nodes) == 2
    assert isinstance(edges, list) and edges

    term_ids = {t.get("id") for t in terms}
    assert any(str(tid or "").startswith("term:") for tid in term_ids)

    snippet_ids = {s.get("id") for s in snippets_nodes}
    assert "snip:S1" in snippet_ids
    assert "snip:S2" in snippet_ids

    edge_pairs = {(e.get("term_id"), e.get("snippet_id")) for e in edges}
    assert any(pair[1] == "snip:S1" for pair in edge_pairs)
    assert any(pair[1] == "snip:S2" for pair in edge_pairs)

