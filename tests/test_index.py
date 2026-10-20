"""Milestone 5: chunking masked documents, and searching them."""

import json
import re
from pathlib import Path

import pytest

from scripts.evaluate_search import QUESTIONS
from src.extract import extract_document
from src.index import (MAX_BODY_TOKENS, SearchLibrary, bm25_scores, chunk_document, count_tokens,
                       split_long_line)
from src.mask import mask_document, mask_question
from src.vault import Vault, new_keys

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "data" / "fake_docs"
KEY = json.loads((ROOT / "data" / "answer_key.json").read_text())
ROSTER = json.loads((ROOT / "data" / "hr_roster.json").read_text())["employees"]
MODEL_LIMIT = 256  # MiniLM ignores anything past this


@pytest.fixture(scope="module")
def vault(tmp_path_factory):
    k = new_keys()
    path = tmp_path_factory.mktemp("vault") / "vault.db"
    with Vault(path, k["VAULT_ENCRYPTION_KEY"].encode(), k["VAULT_INDEX_KEY"].encode()) as v:
        yield v


@pytest.fixture(scope="module")
def masked(vault):
    return {d["file"]: mask_document(extract_document(DOCS / d["file"]), vault, ROSTER) for d in KEY["documents"]}


@pytest.fixture(scope="module")
def chunks(masked):
    return {file: chunk_document(doc) for file, doc in masked.items()}


def body(chunk: dict) -> str:
    """The chunk without its [header] line."""
    lines = chunk["text"].splitlines()
    return "\n".join(lines[1:] if lines and lines[0].startswith("[") else lines)


# ---------------------------------------------------------------- size

def test_placeholders_cost_several_tokens():
    # Why we count tokens, not words: one masked "word" can be 5 tokens.
    assert count_tokens("salary") == 1
    assert count_tokens("BANK_ACCOUNT_1") == 5


def test_every_chunk_fits_the_embedding_model(chunks):
    sizes = [c["tokens"] for doc in chunks.values() for c in doc]
    assert max(sizes) <= MODEL_LIMIT


def test_long_pages_are_split(chunks):
    # The W-4 page is ~900 words; unsplit, most of it would never be searchable.
    assert len(chunks["w4_olson.pdf"]) > 5


def test_very_long_line_is_split_at_sentences():
    paragraph = " ".join(f"Sentence number {i} about leave and pay." for i in range(80))
    pieces = split_long_line(paragraph, MAX_BODY_TOKENS)
    assert len(pieces) > 1
    assert all(count_tokens(p) <= MAX_BODY_TOKENS for p in pieces)
    assert all(p.endswith(".") for p in pieces)  # cut between sentences, not inside one


# ---------------------------------------------------------------- nothing lost, nothing cut

@pytest.mark.parametrize("doc", KEY["documents"], ids=lambda d: d["file"])
def test_every_line_is_kept_whole_in_some_chunk(doc, masked, chunks):
    bodies = [body(c) for c in chunks[doc["file"]]]
    for page in masked[doc["file"]]["pages"]:
        for line in filter(str.strip, page["text"].splitlines()):
            if count_tokens(line) <= MAX_BODY_TOKENS:
                assert any(line in b.splitlines() for b in bodies), line


def test_payroll_rows_are_never_cut(chunks):
    rows = [line for c in chunks["payroll_register_q3_2025.pdf"] for line in body(c).splitlines()
            if line.startswith("EMPLOYEE_ID_")]
    # Every row keeps all 9 columns: ID, name, SSN, 5 amounts, bank account.
    assert rows and all(len(r.split()) == 9 for r in rows)


@pytest.mark.parametrize("file", ["w4_olson.pdf", "payroll_register_q3_2025.pdf"])
def test_consecutive_chunks_overlap_when_the_last_line_is_short(file, chunks):
    # A short last line (a table row) is repeated in the next chunk. A long paragraph
    # is not: it would eat the next chunk's budget, and it is already whole in one chunk.
    pages = [c for c in chunks[file] if c["page"] == 1]
    checked = 0
    for a, b in zip(pages, pages[1:]):
        last = body(a).splitlines()[-1]
        if count_tokens(last) <= 40:
            assert last in body(b).splitlines()
            checked += 1
    assert checked


# ---------------------------------------------------------------- headers and citations

def test_mid_table_chunk_says_which_table_and_month(chunks):
    for c in chunks["payroll_register_q3_2025.pdf"]:
        if c["page"] == 3:
            assert "Payroll Register: Q3 2025" in c["text"] or c["chunk_id"].endswith("c1")
            assert "September 2025" in c["text"]


def test_later_pages_carry_the_document_title(chunks):
    for c in chunks["personnel_file_heath.pdf"][1:]:
        assert c["text"].startswith("[Personnel File: PERSON_")


def test_headers_skip_the_company_letterhead(chunks):
    for doc in chunks.values():
        for c in doc:
            if c["text"].startswith("["):
                assert "Brightline Logistics LLC" not in c["text"].splitlines()[0]


def test_every_chunk_knows_its_document_and_page(chunks, masked):
    for file, doc in chunks.items():
        ids = [c["chunk_id"] for c in doc]
        assert len(ids) == len(set(ids))
        for c in doc:
            assert c["doc_id"] == masked[file]["doc_id"]
            assert 1 <= c["page"] <= len(masked[file]["pages"])


def test_only_masked_documents_can_be_chunked():
    raw = extract_document(DOCS / "payslip_september_2025_johnson.pdf")
    with pytest.raises(ValueError, match="masked documents only"):
        chunk_document(raw)


def test_every_chunk_of_a_one_person_form_names_that_person(chunks):
    # The W-2 is split into several chunks; the name and the federal tax box land in
    # different ones. Each chunk must still say whose W-2 it is.
    w2 = chunks["w2_2025_brooks.pdf"]
    subject = re.search(r"PERSON_\d+", " ".join(c["text"] for c in w2)).group()
    assert len(w2) > 1 and all(subject in c["text"] for c in w2)


def test_documents_about_many_people_have_no_single_subject(chunks):
    assert not any(c["text"].startswith("[About") for c in chunks["employee_directory.pdf"])


# ---------------------------------------------------------------- the search library

@pytest.fixture(scope="module")
def library(tmp_path_factory, chunks):
    lib = SearchLibrary(tmp_path_factory.mktemp("index"))
    lib.add([c for doc in chunks.values() for c in doc])
    return lib


def test_keyword_search_values_rare_exact_words():
    texts = ["PERSON_5 earns MONEY_1 per year", "PERSON_7 earns MONEY_9 per year", "the leave policy"]
    scores = bm25_scores("How much PERSON_5 earns", texts)
    assert scores[0] > scores[1] > scores[2]  # both words > only "earns" > nothing shared
    assert bm25_scores("earn", texts)[0] == 0  # exact words only: "earn" is not "earns"


def test_library_holds_every_chunk_once(library, chunks):
    total = sum(len(doc) for doc in chunks.values())
    assert library.count() == total
    library.add(chunks["leave_policy_2025.pdf"])  # adding again replaces, never duplicates
    assert library.count() == total


def test_library_files_contain_no_private_values(library, tmp_path_factory):
    raw = b"".join(p.read_bytes() for p in tmp_path_factory.getbasetemp().rglob("*")
                   if p.is_file() and "index" in str(p))
    values = {i["value"] for d in KEY["documents"] for i in d["pii"] if len(i["value"]) >= 4}
    assert raw and not [v for v in values if v.encode() in raw]


def test_search_results_carry_citations(library):
    results = library.search("How long is paid parental leave?", k=3)
    assert len(results) == 3
    assert all(re.fullmatch(r"DOC_\d+", r["doc_id"]) and r["page"] >= 1 for r in results)


def test_hybrid_search_finds_the_right_page(library, vault):
    hits = 0
    for question, answers in QUESTIONS:
        good = {(vault.find_placeholder(file, "DOC"), page) for file, page in answers}
        results = library.search(mask_question(question, vault, ROSTER), k=5)
        hits += bool({(r["doc_id"], r["page"]) for r in results} & good)
    assert hits == len(QUESTIONS)  # 12/12; meaning-only search gets 9/12
