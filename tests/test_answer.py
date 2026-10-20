"""Milestone 6: the AI answer step, tested with a stand-in for OpenAI.

The stand-in records exactly what would be sent to OpenAI, so we can prove no
real value ever leaves the machine. A live test runs only with an API key.
"""

import json
from types import SimpleNamespace

import pytest

from src.answer import CANNOT_ANSWER, build_prompt, format_answer, generate_answer, has_api_key

CHUNKS = [
    {"doc_id": "DOC_9", "page": 2, "text": "Effective 03/01/2025 PERSON_5 annual salary MONEY_14 Annual merit increase"},
    {"doc_id": "DOC_20", "page": 1, "text": "Employees receive 8 days of paid sick leave per year."},
]


class FakeOpenAI:
    """Pretends to be the OpenAI client: remembers the request, returns a set reply."""

    def __init__(self, reply: dict | None = None, refusal: str | None = None, status: str = "completed"):
        self.reply, self.refusal, self.status, self.requests = reply, refusal, status, []
        self.responses = SimpleNamespace(create=self._create)

    def _create(self, **request):
        self.requests.append(request)
        part = (SimpleNamespace(type="refusal", refusal=self.refusal) if self.refusal
                else SimpleNamespace(type="output_text", text=json.dumps(self.reply)))
        return SimpleNamespace(status=self.status, output_text=json.dumps(self.reply),
                               output=[SimpleNamespace(type="reasoning"), SimpleNamespace(type="message", content=[part])])


def test_answer_with_a_valid_citation():
    llm = FakeOpenAI({"answer": "PERSON_5 earns MONEY_14 a year.", "answerable": True,
                      "citations": [{"doc_id": "DOC_9", "page": 2}]})
    result = generate_answer("What is PERSON_5's salary?", CHUNKS, client=llm)
    assert result["citations"] == [{"doc_id": "DOC_9", "page": 2}]
    assert format_answer(result) == "PERSON_5 earns MONEY_14 a year. [DOC_9, page 2]"


def test_made_up_citation_is_not_presented_as_real():
    llm = FakeOpenAI({"answer": "PERSON_5 earns MONEY_14.", "answerable": True,
                      "citations": [{"doc_id": "DOC_9", "page": 2}, {"doc_id": "DOC_99", "page": 4}]})
    result = generate_answer("What is PERSON_5's salary?", CHUNKS, client=llm)
    assert result["citations"] == [{"doc_id": "DOC_9", "page": 2}]
    assert result["unverified_citations"] == [{"doc_id": "DOC_99", "page": 4}]


def test_refusal_gives_a_safe_answer():
    result = generate_answer("anything", CHUNKS, client=FakeOpenAI(refusal="I can't help with that."))
    assert result["answer"] == CANNOT_ANSWER and not result["answerable"]
    assert result["stop_reason"] == "refusal"


def test_cut_off_answer_gives_a_safe_answer():
    result = generate_answer("anything", CHUNKS, client=FakeOpenAI({"answer": "PERS"}, status="incomplete"))
    assert result["answer"] == CANNOT_ANSWER and result["stop_reason"] == "incomplete"


def test_no_passages_means_no_call_at_all():
    llm = FakeOpenAI()
    assert generate_answer("What is PERSON_5's salary?", [], client=llm)["answer"] == CANNOT_ANSWER
    assert llm.requests == []


def test_request_settings(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    llm = FakeOpenAI({"answer": "8 days.", "answerable": True, "citations": [{"doc_id": "DOC_20", "page": 1}]})
    generate_answer("How many sick days?", CHUNKS, client=llm)
    request = llm.requests[0]
    assert request["model"] == "gpt-6-astra"
    assert request["store"] is False  # nothing kept on OpenAI's servers
    assert request["text"]["format"]["type"] == "json_schema" and request["text"]["format"]["strict"]


def test_model_can_be_changed_in_env(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-6-luna")
    llm = FakeOpenAI({"answer": "8 days.", "answerable": True, "citations": []})
    generate_answer("How many sick days?", CHUNKS, client=llm)
    assert llm.requests[0]["model"] == "gpt-6-luna"


def test_passages_are_labelled_for_citing():
    prompt = build_prompt("What is PERSON_5's salary?", CHUNKS)
    assert '<passage doc_id="DOC_9" page="2">' in prompt
    assert prompt.endswith("Question: What is PERSON_5's salary?")


def test_only_masked_text_is_sent_to_openai():
    # The real pipeline: extract -> mask -> chunk -> search -> answer. Capture what would be sent.
    import tempfile
    from pathlib import Path

    from src.extract import extract_document
    from src.index import SearchLibrary, chunk_document
    from src.mask import mask_document, mask_question
    from src.vault import Vault, new_keys

    root = Path(__file__).resolve().parent.parent
    roster = json.loads((root / "data" / "hr_roster.json").read_text())["employees"]
    k = new_keys()
    tmp = Path(tempfile.mkdtemp())
    with Vault(tmp / "vault.db", k["VAULT_ENCRYPTION_KEY"].encode(), k["VAULT_INDEX_KEY"].encode()) as vault:
        library = SearchLibrary(tmp / "index")
        for name in ["personnel_file_heath.pdf", "payslip_september_2025_heath.pdf"]:
            library.add(chunk_document(mask_document(extract_document(root / "data" / "fake_docs" / name), vault, roster)))
        question = mask_question("What is Rebecca Heath's annual base salary?", vault, roster)
        llm = FakeOpenAI({"answer": "x", "answerable": True, "citations": []})
        generate_answer(question, library.search(question, k=5), client=llm)

    sent = json.dumps(llm.requests[0])
    key = json.loads((root / "data" / "answer_key.json").read_text())
    secrets = {item["value"] for doc in key["documents"] if doc["file"] in (
        "personnel_file_heath.pdf", "payslip_september_2025_heath.pdf") for item in doc["pii"]}
    assert "PERSON_" in sent  # the passages really were sent...
    assert not [s for s in secrets if len(s) >= 4 and s in sent]  # ...without a single real value


@pytest.mark.skipif(not has_api_key(), reason="needs OPENAI_API_KEY in .env")
def test_live_openai_answers_from_the_passages():
    result = generate_answer("How many days of paid sick leave do employees get?", CHUNKS)
    assert result["answerable"] and "8" in result["answer"]
    assert {"doc_id": "DOC_20", "page": 1} in result["citations"]
