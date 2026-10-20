"""Milestone 3: score the PII detector against the answer key.

    python scripts/evaluate_detection.py

Recall = share of the answer key's private values the detector caught.
A miss is a leak, so recall is the number that matters most.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.detect import digits_of, find_pii_in_document  # noqa: E402
from src.extract import extract_document  # noqa: E402

KEY = json.loads((ROOT / "data" / "answer_key.json").read_text())
ROSTER = json.loads((ROOT / "data" / "hr_roster.json").read_text())["employees"]
NUMERIC = {"SSN", "ITIN", "EIN", "PHONE", "BANK_ROUTING", "BANK_ACCOUNT", "SALARY"}


def norm(text: str) -> str:
    return " ".join(text.split())


def is_caught(item: dict, findings: list) -> bool:
    """True if some finding covers the answer-key value."""
    value = norm(item["value"])
    for f in findings:
        found = norm(f.value)
        if value in found:
            return True
        if item["type"] in NUMERIC and digits_of(value) and digits_of(value) == digits_of(found):
            return True
    return False


def evaluate() -> dict:
    caught, total, misses = Counter(), Counter(), defaultdict(list)
    found_types = Counter()
    for doc in KEY["documents"]:
        pages = extract_document(ROOT / "data" / "fake_docs" / doc["file"])["pages"]
        per_page = find_pii_in_document([p["text"] for p in pages], ROSTER)
        findings = {p["page"]: f for p, f in zip(pages, per_page)}
        found_types.update(f.type for fs in findings.values() for f in fs)
        for item in doc["pii"]:
            total[item["type"]] += 1
            if is_caught(item, findings[item["page"]]):
                caught[item["type"]] += 1
            else:
                misses[item["type"]].append(f"{doc['file']} p{item['page']}: {item['value']!r}")
        if doc["kind"] == "Leave policy":
            policy_findings = [f for fs in findings.values() for f in fs]
    return {"caught": caught, "total": total, "misses": misses,
            "policy_findings": policy_findings, "found_types": found_types}


def main() -> None:
    r = evaluate()
    print(f"{'type':14} {'caught':>7} {'total':>6}  recall")
    for t in sorted(r["total"]):
        print(f"{t:14} {r['caught'][t]:7} {r['total'][t]:6}  {r['caught'][t] / r['total'][t]:6.1%}")
    c, t = sum(r["caught"].values()), sum(r["total"].values())
    print(f"{'ALL':14} {c:7} {t:6}  {c / t:6.1%}")
    for kind, items in r["misses"].items():
        print(f"\nMISSED {kind}:")
        for m in items[:10]:
            print("  " + m)
    print(f"\nFalse alarms on the leave policy (has no private data): {len(r['policy_findings'])}")
    for f in r["policy_findings"]:
        print(f"  {f.type}: {f.value!r}")


if __name__ == "__main__":
    main()
