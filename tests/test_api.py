"""Milestone 9: the web API behind the chat page, with a stand-in for OpenAI."""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from src.extract import extract_document
from src.index import SearchLibrary, chunk_document
from src.mask import mask_document
from src.pipeline import Assistant
from src.vault import Vault, new_keys
from tests.test_pipeline import FakeLLM, honest_policy_answer, honest_salary_answer

ROOT = Path(__file__).resolve().parent.parent
ROSTER = json.loads((ROOT / "data" / "hr_roster.json").read_text())["employees"]


@pytest.fixture(scope="module")
def stores(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("api")
    k = new_keys()
    vault = Vault(tmp / "vault.db", k["VAULT_ENCRYPTION_KEY"].encode(), k["VAULT_INDEX_KEY"].encode())
    library = SearchLibrary(tmp / "index")
    for name in ["personnel_file_heath.pdf", "leave_policy_2025.pdf"]:
        library.add(chunk_document(mask_document(extract_document(ROOT / "data" / "fake_docs" / name), vault, ROSTER)))
    return vault, library


def client(stores, reply) -> TestClient:
    vault, library = stores
    assistant = Assistant(vault=vault, library=library, llm_client=FakeLLM(reply), known_names=ROSTER)
    return TestClient(create_app(assistant))


def test_page_and_static_files_are_served(stores):
    with client(stores, honest_policy_answer) as c:
        assert "Clearance" in c.get("/").text
        assert c.get("/static/app.css").status_code == 200
        assert c.get("/static/app.js").status_code == 200


def test_users_come_with_their_roles(stores):
    with client(stores, honest_policy_answer) as c:
        assert {(u["id"], u["role"]) for u in c.get("/api/users").json()} == {("oliver", "employee"), ("charlotte", "hr")}


def test_employee_gets_a_sealed_answer(stores):
    with client(stores, honest_policy_answer) as c:
        reply = c.post("/api/ask", json={"user": "oliver", "question": "How many days of paid sick leave do employees get?"}).json()
    assert reply["status"] == "answered" and "8 days" in reply["answer"]
    assert re.fullmatch(r"DOC_\d+", reply["sources"][0]["doc"])


def test_role_comes_from_the_server_not_the_page(stores):
    # The page cannot claim to be HR: an extra "role" field is ignored.
    with client(stores, honest_salary_answer) as c:
        reply = c.post("/api/ask", json={"user": "oliver", "role": "hr",
                                         "question": "What is Rebecca Heath's annual base salary?"}).json()
    assert reply["status"] == "refused" and "Rebecca" not in json.dumps(reply["segments"][1:])


def test_hr_gets_unsealed_values(stores):
    with client(stores, honest_salary_answer) as c:
        reply = c.post("/api/ask", json={"user": "charlotte", "question": "What is Rebecca Heath's annual base salary?"}).json()
    assert [s["value"] for s in reply["segments"] if "placeholder" in s] == ["Rebecca Heath", "$111,500.00"]


def test_unknown_user_and_bad_input_are_rejected(stores):
    with client(stores, honest_policy_answer) as c:
        assert c.post("/api/ask", json={"user": "mallory", "question": "Hi"}).status_code == 404
        assert c.post("/api/ask", json={"user": "oliver", "question": ""}).status_code == 422
        assert c.post("/api/ask", json={"user": "oliver", "question": "x" * 1001}).status_code == 422


def test_only_hr_can_read_the_audit_log(stores):
    with client(stores, honest_policy_answer) as c:
        assert c.get("/api/audit", params={"user": "oliver"}).status_code == 403
        log = c.get("/api/audit", params={"user": "charlotte"}).json()
    assert isinstance(log, list)


def test_ai_failure_is_reported_without_details(stores):
    def broken(passages):
        raise ConnectionError("network down: could echo the question 'What is Rebecca Heath's SSN'")

    with client(stores, broken) as c:
        res = c.post("/api/ask", json={"user": "oliver", "question": "How many days of paid sick leave do employees get?"})
    assert res.status_code == 502
    assert "ConnectionError" in res.json()["detail"] and "Rebecca" not in res.text
