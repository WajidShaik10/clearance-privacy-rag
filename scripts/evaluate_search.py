"""Milestone 5: does search find the right page? Compares three ways of searching.

    python scripts/ingest.py            # build the library first
    python scripts/evaluate_search.py

Each question is masked exactly as a user's would be, then searched. A hit means
one of the top 5 chunks comes from a page that holds the answer.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.index import SearchLibrary  # noqa: E402
from src.mask import mask_question  # noqa: E402
from src.vault import Vault  # noqa: E402

ROSTER = json.loads((ROOT / "data" / "hr_roster.json").read_text())["employees"]
TOP_K = 5

# (question, pages that answer it: (file, page))
QUESTIONS = [
    ("How many days of paid sick leave do employees get?", [("leave_policy_2025.pdf", 1)]),
    ("How long is paid parental leave?", [("leave_policy_2025.pdf", 1)]),
    ("Will HR ever ask for my Social Security number by email?", [("leave_policy_2025.pdf", 2)]),
    ("What is Rebecca Heath's annual base salary?",
     [("personnel_file_heath.pdf", 2), ("scan_personnel_file_heath.pdf", 2), ("payslip_september_2025_heath.pdf", 1)]),
    ("Which bank account is Danielle Johnson's pay deposited into?",
     [("payslip_september_2025_johnson.pdf", 1), ("personnel_file_johnson.pdf", 1),
      # every monthly page of the register lists her bank account too
      ("payroll_register_q3_2025.pdf", 1), ("payroll_register_q3_2025.pdf", 2), ("payroll_register_q3_2025.pdf", 3)]),
    ("What is Nicole Day's phone number?", [("employee_directory.pdf", 1)]),
    ("Who reviewed Rebecca Heath's performance?",
     [("personnel_file_heath.pdf", 3), ("scan_personnel_file_heath.pdf", 3)]),
    ("How much federal income tax was withheld for James Brooks?",
     [("w2_2025_brooks.pdf", 1), ("payslip_september_2025_brooks.pdf", 1)]),
    ("What is Samantha Hooper's taxpayer identification number?", [("w9_hooper.pdf", 1)]),
    ("Who is Rebecca Heath's emergency contact?",
     [("personnel_file_heath.pdf", 1), ("scan_personnel_file_heath.pdf", 1)]),
    ("What was Andrea Calderon's net pay in September 2025?",
     [("payroll_register_q3_2025.pdf", 3), ("payslip_september_2025_calderon.pdf", 1)]),
    ("What is Richard Olson's home address?",
     [("w4_olson.pdf", 1), ("scan_w4_olson.pdf", 1), ("employee_directory.pdf", 1)]),
]


def evaluate() -> dict:
    library = SearchLibrary()
    results = {"vector": 0, "keyword": 0, "hybrid": 0, "rows": []}
    with Vault.from_env() as vault:
        for question, answers in QUESTIONS:
            masked_q = mask_question(question, vault, ROSTER)
            good = {(vault.find_placeholder(file, "DOC"), page) for file, page in answers}
            hits = {}
            for method, ids in [("vector", library.vector_search(masked_q, TOP_K)),
                                ("keyword", library.keyword_search(masked_q, TOP_K)),
                                ("hybrid", [r["chunk_id"] for r in library.search(masked_q, TOP_K)])]:
                # chunk_id is "DOC_7-p2-c1": its document and page
                found = {(cid.split("-p")[0], int(cid.split("-p")[1].split("-c")[0])) for cid in ids}
                hits[method] = bool(found & good)
                results[method] += hits[method]
            results["rows"].append((masked_q, hits))
    return results


def main() -> None:
    r = evaluate()
    n = len(QUESTIONS)
    print(f"{'masked question':66} vector keyword hybrid")
    for q, hits in r["rows"]:
        print(f"{q[:66]:66} {'yes' if hits['vector'] else '-':>6} {'yes' if hits['keyword'] else '-':>7} "
              f"{'yes' if hits['hybrid'] else '-':>6}")
    print(f"\nRight page in the top {TOP_K}:  vector {r['vector']}/{n}   keyword {r['keyword']}/{n}   "
          f"hybrid {r['hybrid']}/{n}")


if __name__ == "__main__":
    main()
