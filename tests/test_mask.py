"""Milestone 4: masking documents and questions, and unmasking for HR."""

import json
import re
from pathlib import Path

import pymupdf
import pytest

from src.extract import extract_document
from src.mask import PLACEHOLDER, canonical_name, mask_document, mask_question, unmask
from src.vault import Vault, new_keys

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "data" / "fake_docs"
KEY = json.loads((ROOT / "data" / "answer_key.json").read_text())
ROSTER = json.loads((ROOT / "data" / "hr_roster.json").read_text())["employees"]


@pytest.fixture(scope="module")
def vault(tmp_path_factory):
    k = new_keys()
    path = tmp_path_factory.mktemp("vault") / "vault.db"
    with Vault(path, k["VAULT_ENCRYPTION_KEY"].encode(), k["VAULT_INDEX_KEY"].encode()) as v:
        yield v


@pytest.fixture(scope="module")
def masked(vault):
    """Mask all 22 documents once into one shared vault (OCR takes a few seconds)."""
    return {d["file"]: mask_document(extract_document(DOCS / d["file"]), vault, ROSTER) for d in KEY["documents"]}


def placeholders_on(page_text: str) -> set[str]:
    return set(PLACEHOLDER.findall(page_text))


# ---------------------------------------------------------------- nothing real is left

@pytest.mark.parametrize("doc", KEY["documents"], ids=lambda d: d["file"])
def test_no_private_value_survives_masking(doc, masked):
    for item in doc["pii"]:
        text = PLACEHOLDER.sub(" ", masked[doc["file"]]["pages"][item["page"] - 1]["text"])
        value = " ".join(item["value"].split())
        digits = re.sub(r"\D", "", value)
        assert value not in " ".join(text.split()), item
        assert len(digits) < 6 or digits not in re.sub(r"\D", "", text), item


def test_no_employee_last_name_is_left_anywhere(masked):
    last_names = {name.split()[-1] for name in ROSTER}
    for file, doc in masked.items():
        for page in doc["pages"]:
            for last in last_names:
                assert not re.search(rf"\b{last}\b", page["text"]), (file, last)


def test_file_names_and_hidden_titles_are_not_kept(masked):
    doc = masked["personnel_file_heath.pdf"]
    assert re.fullmatch(r"DOC_\d+", doc["doc_id"])
    assert "personnel_file_heath" not in json.dumps(doc)
    assert set(doc) == {"doc_id", "pages", "comments", "needs_review"}  # no title, author, ...


# ---------------------------------------------------------------- one person, one placeholder

def test_name_variants_share_the_full_names_placeholder(masked):
    pages = masked["personnel_file_heath.pdf"]["pages"]
    person = re.search(r"Personnel File: (PERSON_\d+)", pages[0]["text"]).group(1)
    # Page 3 says "Rebecca ..." and "Mx. Heath ..."; both must be the same person.
    review = pages[2]["text"]
    assert review.count(person) == 3


def test_same_person_same_placeholder_across_documents(masked):
    payslip = re.search(r"Employee (PERSON_\d+)", masked["payslip_september_2025_johnson.pdf"]["pages"][0]["text"]).group(1)
    directory = masked["employee_directory.pdf"]["pages"][0]["text"]
    assert re.search(rf"^{payslip} Operations Logistics Coordinator", directory, re.M)


def test_scanned_copy_gets_the_same_placeholders_as_the_original(masked):
    original = masked["personnel_file_heath.pdf"]["pages"]
    scan = masked["scan_personnel_file_heath.pdf"]["pages"]
    for o, s in zip(original, scan):
        assert placeholders_on(o["text"]) == placeholders_on(s["text"])


def test_ambiguous_first_name_is_not_guessed():
    names = {"Rebecca Heath", "Rebecca Stone"}
    assert canonical_name("Rebecca", names) == "Rebecca"  # two Rebeccas: don't pick one
    assert canonical_name("Mx. Heath", names) == "Rebecca Heath"


# ---------------------------------------------------------------- comments

def test_comments_are_masked(vault, tmp_path):
    review = tmp_path / "review.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72), "Quarterly review notes for the team.")
        page.add_text_annot((72, 120), "Approved raise for Rebecca Heath, SSN 073-66-3900")
        pdf.save(review)
    doc = mask_document(extract_document(review), vault, ROSTER)
    assert "Rebecca" not in doc["comments"] and "073-66-3900" not in doc["comments"]
    assert re.search(r"Approved raise for PERSON_\d+, SSN SSN_\d+", doc["comments"])


# ---------------------------------------------------------------- questions (step 8)

def test_question_uses_the_documents_placeholders(vault, masked):
    rebecca = re.search(r"Personnel File: (PERSON_\d+)", masked["personnel_file_heath.pdf"]["pages"][0]["text"]).group(1)
    assert mask_question("What is Rebecca Heath's salary?", vault, ROSTER) == f"What is {rebecca}'s salary?"
    assert mask_question("When did Rebecca join?", vault, ROSTER) == f"When did {rebecca} join?"


def test_question_about_an_unknown_person_stores_nothing(vault, masked):
    masked_q = mask_question("What is the salary of Full Name: John Doe?", vault, ROSTER)
    assert "John Doe" not in masked_q and "[UNKNOWN_PERSON]" in masked_q
    assert vault.find_placeholder("John Doe", "PERSON") is None


# ---------------------------------------------------------------- unmasking (step 13)

def test_hr_gets_real_values_back(vault, masked):
    doc = masked["payslip_september_2025_johnson.pdf"]
    line = next(l for l in doc["pages"][0]["text"].splitlines() if l.startswith("Employee "))
    answer = f"{line} [{doc['doc_id']}, page 1]"
    assert unmask(answer, vault, user="priya", role="hr") == (
        "Employee Danielle Johnson Employee ID EMP-1040 [payslip_september_2025_johnson.pdf, page 1]")


def test_non_hr_cannot_unmask(vault, masked):
    with pytest.raises(PermissionError):
        unmask("Employee PERSON_1", vault, user="ravi", role="employee")


def test_made_up_placeholder_is_left_alone(vault, masked):
    assert unmask("PERSON_999 also works there", vault, user="priya", role="hr") == "PERSON_999 also works there"
