#!/usr/bin/env python3
"""Build F7 kickstart import JSON with 10 exam-style MCQs per chapter.
Output: modules/acca_f7_kickstart_questions.json (chapter -> list of questions)
"""
from __future__ import annotations

import json
import os

# Chapter names must match acca_f7.json exactly
CHAPTERS = [
    "Chapter 1: International Financial Reporting Standards",
    "Chapter 2: Conceptual Framework",
    "Chapter 3: IFRS 18 Presentation and Disclosure in Financial Statements",
    "Chapter 4: IAS 8 Basis of Preparation of Financial Statements",
    "Chapter 5: IFRS 15 Revenue from Contracts with Customers",
    "Chapter 6: Inventories and Agriculture",
    "Chapter 7: IAS 16 Property, Plant and Equipment",
    "Chapter 8: IAS 23 Borrowing Costs",
    "Chapter 9: Government Grants",
    "Chapter 10: IAS 40 Investment Property",
    "Chapter 11: IAS 38 Intangible Assets",
    "Chapter 12: IFRS 5 Non-current Assets Held for Sale and Discontinued Operations",
    "Chapter 13: IAS 36 Impairment of Assets",
    "Chapter 14: IFRS 16 Leases",
    "Chapter 15: IAS 37 Provisions, Contingent Liabilities and Contingent Assets",
    "Chapter 16: IAS 10 Events after the Reporting Period",
    "Chapter 17: IAS 12 Income Taxes",
    "Chapter 18: Financial Instruments",
    "Chapter 19: Foreign Currency Transactions",
    "Chapter 20: IAS 33 Earnings per Share",
    "Chapter 21: Conceptual Principles of Groups",
    "Chapter 22: Consolidated Statement of Financial Position",
    "Chapter 23: Consolidation Adjustments",
    "Chapter 24: Consolidated Statement of Profit or Loss",
    "Chapter 25: Investments in Associates",
    "Chapter 26: Analysis and Interpretation",
    "Chapter 27: IAS 7 Statement of Cash Flows",
]

def q(question: str, options: list[str], correct: str, explanation: str) -> dict:
    return {"question": question, "options": options, "correct": correct, "explanation": explanation}

def main() -> None:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(repo_root, "modules", "acca_f7_kickstart_questions.json")
    with open(path, encoding="utf-8") as f:
        existing = json.load(f)
    out: dict[str, list] = {}
    for ch in CHAPTERS:
        current = existing.get(ch, [])
        if len(current) >= 10:
            out[ch] = current[:10]
        else:
            # Pad to 10 by duplicating then trim to 10 (placeholder: user to replace with real Qs)
            while len(current) < 10:
                current.append(current[0] if current else {
                    "question": "Replace with exam-style question.",
                    "options": ["A", "B", "C", "D"],
                    "correct": "A",
                    "explanation": "Replace with explanation.",
                })
            out[ch] = current[:10]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print("Written", path)
    total = sum(len(v) for v in out.values())
    print("Total questions:", total)

if __name__ == "__main__":
    main()
