"""Milestone 3: score the PII detector on documents it was NOT built from.

Uses English rows from Gretel's synthetic financial PII dataset (Apache-2.0),
downloaded to data/external/gretel/. Rows from the first 300 are "dev" (we may
look at misses and improve the detector); rows 300-499 are "test" (never looked
at while improving, so their score is the honest one).

    python scripts/evaluate_unseen.py            # dev split
    python scripts/evaluate_unseen.py test       # held-out test split
    python scripts/evaluate_unseen.py dev show   # also print missed examples
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.detect import find_pii  # noqa: E402

DATA = ROOT / "data" / "external" / "gretel"

# Gretel label -> our type. Only these are scored for recall.
IN_SCOPE = {
    "name": "PERSON", "first_name": "PERSON", "last_name": "PERSON",
    "street_address": "ADDRESS", "email": "EMAIL", "phone_number": "PHONE",
    "ssn": "SSN", "date_of_birth": "DOB", "bban": "BANK_ACCOUNT", "iban": "BANK_ACCOUNT",
    "bank_routing_number": "BANK_ROUTING", "employee_id": "EMPLOYEE_ID",
}
# Sensitive, but not something our detector looks for (reported as a gap).
OUT_OF_SCOPE = {
    "credit_card_number", "credit_card_security_code", "passport_number", "driver_license_number",
    "account_pin", "password", "api_key", "swift_bic_code", "customer_id", "user_name",
    "ipv4", "ipv6", "local_latlng",
}
# Everything else (date, time, company, ...) is not personal data for this project.


def load_rows(split: str) -> list[dict]:
    files = sorted(DATA.glob("rows_*.json"), key=lambda f: int(f.stem.split("_")[1]))
    wanted = range(0, 300) if split == "dev" else range(300, 500)
    rows = []
    for f in files:
        offset = int(f.stem.split("_")[1])
        for i, item in enumerate(json.loads(f.read_text())["rows"]):
            if offset + i in wanted and item["row"]["language"] == "English":
                rows.append(item["row"])
    return rows


def coverage(span: dict, findings: list) -> float:
    """Share of the labelled value's characters that some finding covers."""
    chars = set(range(span["start"], span["end"]))
    covered = {i for f in findings for i in range(f.start, f.end)} & chars
    return len(covered) / len(chars) if chars else 1.0


def evaluate(split: str) -> dict:
    total, caught, partly = Counter(), Counter(), Counter()
    misses = defaultdict(list)
    for row in load_rows(split):
        text = row["generated_text"]
        findings = find_pii(text)
        for span in json.loads(row["pii_spans"]):
            label = span["label"]
            if label not in IN_SCOPE and label not in OUT_OF_SCOPE:
                continue
            total[label] += 1
            share = coverage(span, findings)
            if share >= 0.9:
                caught[label] += 1
            elif share > 0:
                partly[label] += 1
                misses[label].append(f"PARTLY {text[span['start']:span['end']]!r}")
            else:
                misses[label].append(repr(text[span["start"]:span["end"]]))
    return {"total": total, "caught": caught, "partly": partly, "misses": misses}


def report(r: dict, labels: set, title: str, show: bool) -> None:
    print(f"\n{title}")
    print(f"  {'label':26} {'caught':>6} {'partly':>6} {'total':>6}  recall")
    tc = tt = 0
    for label in sorted(labels & set(r["total"]), key=lambda l: -r["total"][l]):
        c, p, t = r["caught"][label], r["partly"][label], r["total"][label]
        tc, tt = tc + c, tt + t
        print(f"  {label:26} {c:6} {p:6} {t:6}  {c / t:6.1%}")
    if tt:
        print(f"  {'ALL':26} {tc:6} {'':6} {tt:6}  {tc / tt:6.1%}")
    if show:
        for label in sorted(labels & set(r["misses"])):
            print(f"\n  missed {label}: " + " | ".join(r["misses"][label][:8]))


def main() -> None:
    split = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in ("dev", "test") else "dev"
    show = "show" in sys.argv
    r = evaluate(split)
    print(f"Split: {split} ({len(load_rows(split))} English documents)")
    report(r, set(IN_SCOPE), "IN SCOPE (what the detector is built to find)", show)
    report(r, OUT_OF_SCOPE, "OUT OF SCOPE (sensitive, not covered yet)", False)


if __name__ == "__main__":
    main()
