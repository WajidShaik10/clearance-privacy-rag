"""Milestone 1: the fake documents and the answer key agree with each other."""

import json
from pathlib import Path

import pymupdf
import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "data" / "fake_docs"
KEY = json.loads((ROOT / "data" / "answer_key.json").read_text())


def test_every_document_in_the_key_exists():
    for doc in KEY["documents"]:
        assert (DOCS / doc["file"]).exists(), doc["file"]


def test_every_pdf_is_in_the_key():
    listed = {d["file"] for d in KEY["documents"]}
    assert {p.name for p in DOCS.glob("*.pdf")} == listed


@pytest.mark.parametrize("doc", [d for d in KEY["documents"] if not d["scanned"]], ids=lambda d: d["file"])
def test_key_values_appear_on_their_pages(doc):
    with pymupdf.open(DOCS / doc["file"]) as pdf:
        texts = [" ".join(page.get_text().split()) for page in pdf]
        digits = ["".join(c for c in t if c.isdigit()) for t in texts]
    for item in doc["pii"]:
        value = " ".join(item["value"].split())
        value_digits = "".join(c for c in value if c.isdigit())
        page = item["page"] - 1
        assert value in texts[page] or (value_digits and value_digits in digits[page]), item


def test_scanned_documents_have_no_text_layer():
    for doc in (d for d in KEY["documents"] if d["scanned"]):
        with pymupdf.open(DOCS / doc["file"]) as pdf:
            assert all(not page.get_text().strip() for page in pdf), doc["file"]


def test_policy_document_has_no_private_data():
    policy = next(d for d in KEY["documents"] if d["kind"] == "Leave policy")
    assert policy["pii"] == []
