"""Milestone 7: one question through every step, with a stand-in for OpenAI."""

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.extract import extract_document
from src.index import SearchLibrary, chunk_document
from src.mask import mask_document
from src.pipeline import BLOCKED_MESSAGE, Assistant
from src.vault import Vault, new_keys

ROOT = Path(__file__).resolve().parent.parent
ROSTER = json.loads((ROOT / "data" / "hr_roster.json").read_text())["employees"]
KEY = json.loads((ROOT / "data" / "answer_key.json").read_text())
HEATH_SALARY = "$111,500.00"


class FakeLLM:
    """Stands in for OpenAI. `reply(passages_text)` decides what it answers."""

    def __init__(self, reply):
        self.reply, self.calls = reply, 0
        self.responses = SimpleNamespace(create=self._create)

    def _create(self, **request):
        self.calls += 1
        body = json.dumps(self.reply(request["input"]))
        part = SimpleNamespace(type="output_text", text=body)
        return SimpleNamespace(status="completed", output_text=body,
                               output=[SimpleNamespace(type="message", content=[part])])


def honest_salary_answer(passages: str) -> dict:
    """Answers like a well-behaved model: uses the passage that has the salary history."""
    # "PERSON_1's current base salary of MONEY_3 was approved by ..." inside one passage
    match = re.search(r'<passage doc_id="(DOC_\d+)" page="(\d+)">(?:(?!</passage>).)*?'
                      r"(PERSON_\d+)'s current base salary of (MONEY_\d+)", passages, re.S)
    doc, page, person, money = match.groups()
    return {"answer": f"{person}'s current annual base salary is {money}.", "answerable": True,
            "citations": [{"doc_id": doc, "page": int(page)}]}


def honest_policy_answer(passages: str) -> dict:
    doc, page = re.search(r'<passage doc_id="(DOC_\d+)" page="(\d+)">\n[^<]*sick leave', passages).groups()
    return {"answer": "Employees receive 8 days of paid sick leave per year.", "answerable": True,
            "citations": [{"doc_id": doc, "page": int(page)}]}


@pytest.fixture(scope="module")
def stores(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("pipeline")
    k = new_keys()
    vault = Vault(tmp / "vault.db", k["VAULT_ENCRYPTION_KEY"].encode(), k["VAULT_INDEX_KEY"].encode())
    library = SearchLibrary(tmp / "index")
    for name in ["personnel_file_heath.pdf", "payslip_september_2025_heath.pdf", "leave_policy_2025.pdf"]:
        library.add(chunk_document(mask_document(extract_document(ROOT / "data" / "fake_docs" / name), vault, ROSTER)))
    yield vault, library
    vault.close()


def assistant(stores, reply) -> Assistant:
    vault, library = stores
    return Assistant(vault=vault, library=library, llm_client=FakeLLM(reply), known_names=ROSTER)


# ---------------------------------------------------------------- the happy paths

def test_employee_gets_a_policy_answer(stores):
    result = assistant(stores, honest_policy_answer).ask("How many days of paid sick leave do employees get?",
                                                          user="ravi", role="employee")
    assert result["status"] == "answered"
    assert re.fullmatch(r"Employees receive 8 days of paid sick leave per year\. \[DOC_\d+, page 1\]", result["answer"])


def test_hr_gets_real_values_and_the_reveal_is_logged(stores):
    vault, _ = stores
    result = assistant(stores, honest_salary_answer).ask("What is Rebecca Heath's annual base salary?",
                                                          user="priya", role="hr")
    assert result == {"status": "answered", "answer":
                      f"Rebecca Heath's current annual base salary is {HEATH_SALARY}. "
                      "[personnel_file_heath.pdf, page 2]"}
    reveals = [e for e in vault.audit_log() if e["user"] == "priya" and e["allowed"]]
    assert {e["placeholder"].split("_")[0] for e in reveals} >= {"PERSON", "MONEY", "DOC"}


def test_employee_never_sees_real_values_even_if_asked_cleverly(stores):
    # Gets past the word rules (no name, no "who"), but the answer stays masked.
    result = assistant(stores, honest_salary_answer).ask("What is the current annual base salary in the personnel file?",
                                                          user="ravi", role="employee")
    assert HEATH_SALARY not in result["answer"] and "Rebecca" not in result["answer"]
    assert re.search(r"PERSON_\d+'s current annual base salary is MONEY_\d+", result["answer"])


# ---------------------------------------------------------------- step 7: refused up front

def test_personal_question_from_employee_is_refused_before_the_ai_is_called(stores):
    a = assistant(stores, honest_salary_answer)
    result = a.ask("What is Rebecca Heath's annual base salary?", user="ravi", role="employee")
    assert result["status"] == "refused" and "limited to HR" in result["answer"]
    assert a.llm_client.calls == 0  # nothing was searched or sent anywhere


def test_unknown_role_is_refused(stores):
    assert assistant(stores, honest_policy_answer).ask("What are the public holidays?", "x", "admin")["status"] == "refused"


def test_refused_question_is_logged_without_its_text(stores):
    vault, _ = stores
    assistant(stores, honest_salary_answer).ask("What is Rebecca Heath's SSN?", user="mallory", role="employee")
    entry = [e for e in vault.audit_log() if e["user"] == "mallory"][-1]
    assert not entry["allowed"] and "refused" in entry["purpose"]
    assert "Rebecca" not in json.dumps(vault.audit_log())  # the log never holds the question itself


# ---------------------------------------------------------------- step 11: the final safety check

@pytest.mark.parametrize("bad_answer, why", [
    ("Her SSN is 073-66-3900.", "real ssn"),
    ("PERSON_5 lives at 82997 Kristen Valley Suite 311.", "real address"),
    ("PERSON_999 earns MONEY_1.", "PERSON_999"),  # a placeholder the AI made up
])
def test_unsafe_answers_are_blocked(stores, bad_answer, why):
    vault, _ = stores
    reply = lambda passages: {"answer": bad_answer, "answerable": True, "citations": []}  # noqa: E731
    result = assistant(stores, reply).ask("How many days of paid sick leave do employees get?", "ravi", "employee")
    assert result == {"status": "blocked", "answer": BLOCKED_MESSAGE}
    assert why in vault.audit_log()[-1]["purpose"]


def test_real_placeholder_the_ai_was_not_shown_is_blocked(stores):
    # Pick a placeholder that exists in the vault but is in none of the passages for this question.
    vault, library = stores
    question = "How many days of paid sick leave do employees get?"
    shown = set(re.findall(r"MONEY_\d+", " ".join(c["text"] for c in library.search(question, k=5))))
    unseen = next(f"MONEY_{n}" for n in range(1, 500)
                  if vault.placeholder_exists(f"MONEY_{n}") and f"MONEY_{n}" not in shown)
    reply = lambda passages: {"answer": f"Sick pay is {unseen}.", "answerable": True, "citations": []}  # noqa: E731
    result = assistant(stores, reply).ask(question, "ravi", "employee")
    assert result["status"] == "blocked"


def test_blocked_answers_are_never_unmasked_for_hr(stores):
    reply = lambda passages: {"answer": "PERSON_999 earns MONEY_1.", "answerable": True, "citations": []}  # noqa: E731
    assert assistant(stores, reply).ask("What is Rebecca Heath's salary?", "priya", "hr")["status"] == "blocked"
