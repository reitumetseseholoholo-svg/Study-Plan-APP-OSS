#!/usr/bin/env python3
"""Run all cognitive control experiments and print structured results.

Usage:
    python tools/run_cognition_experiments.py
    python tools/run_cognition_experiments.py --verbose
    python tools/run_cognition_experiments.py --json
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from studyplan.provenance.cognition.experiment import CognitiveExperiment


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run cognitive control experiments",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print full experiment summaries",
    )
    parser.add_argument(
        "--json",
        "-j",
        action="store_true",
        help="Output results as JSON",
    )
    args = parser.parse_args()

    engine = CognitiveExperiment()
    results = engine.run_suite()

    from studyplan.provenance.learning.cognitive_projection import (
        CognitiveProjection,
        NodeProjection,
        ConfusionEdge,
    )

    fm_proj = CognitiveProjection(
        nodes={
            "fm:WACC": NodeProjection(
                "fm:WACC",
                "WACC",
                uncertainty_score=0.75,
                stability_score=0.60,
                interaction_count=8,
                last_seen=1000.0,
            ),
            "fm:CAPM": NodeProjection(
                "fm:CAPM",
                "CAPM",
                uncertainty_score=0.35,
                stability_score=0.85,
                interaction_count=12,
                last_seen=800.0,
            ),
            "fm:NPV": NodeProjection(
                "fm:NPV",
                "NPV",
                uncertainty_score=0.25,
                stability_score=0.90,
                interaction_count=15,
                last_seen=500.0,
            ),
        },
        confusion_edges=[
            ConfusionEdge("fm:WACC", "fm:CAPM", weight=0.7),
        ],
    )

    cf = engine.run_counterfactual(
        projection=fm_proj,
        target_id="fm:WACC",
        deltas={"uncertainty_score": -0.4},
    )
    results.append(cf)

    if args.json:
        data = []
        for r in results:
            data.append(
                {
                    "name": r.name,
                    "hypothesis": r.hypothesis,
                    "all_confirmed": r.all_confirmed,
                    "findings": [
                        {
                            "claim": f.claim,
                            "measurement": f.measurement,
                            "threshold": f.threshold,
                            "confirmed": f.confirmed,
                        }
                        for f in r.findings
                    ],
                    "implications": r.implications,
                    "signals_ranked": [{"signal": s, "influence": v} for s, v in r.signals_ranked],
                }
            )
        json.dump(data, sys.stdout, indent=2)
        print()
        return 0

    print("=" * 60)
    print("Cognitive Control Experiment Suite")
    print("=" * 60)
    print()
    for r in results:
        print(r.summary)
        print()

    print("=" * 60)
    all_ok = all(r.all_confirmed for r in results)
    print(f"OVERALL: {'ALL EXPERIMENTS CONFIRMED' if all_ok else 'SOME FINDINGS FALSIFIED'}")
    print("=" * 60)

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
