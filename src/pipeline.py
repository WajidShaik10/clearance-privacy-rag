"""Steps 6-16: run one question through every step, in order.

    question -> 7 may they ask? -> 8 mask the question -> 9 search -> 10 AI answers
             -> 11 final safety check -> 12 may they see real values?
             -> 13 HR: unmask (logged, 16)  |  15 everyone else: placeholders
             -> blocked, if the safety check fails

    python -m src.pipeline "How many sick days do employees get?" --user ravi --role employee
    python -m src.pipeline "What is Rebecca Heath's salary?" --user priya --role hr
"""

import json
import re
from pathlib import Path

from src.answer import format_answer, generate_answer
from src.detect import find_pii
from src.index import SearchLibrary
from src.mask import PLACEHOLDER, mask_question, unmask
from src.roles import can_ask, can_see_real_values
from src.vault import Vault

ROSTER_FILE = Path(__file__).resolve().parent.parent / "data" / "hr_roster.json"
BLOCKED_MESSAGE = "Sorry, I can't share that."
TOP_K = 5


def check_answer(masked_answer: str, chunks: list[dict], masked_question: str, vault: Vault,
                 known_names: list[str]) -> str | None:
    """Step 11, the final safety check, on the answer before anyone sees it.

    Returns why the answer must be blocked, or None if it is safe. Fails closed:
    any doubt blocks the answer rather than trying to repair it.
    """
    # 1. No real private value may appear. The AI never saw any, so one here means
    #    something went wrong upstream (or the AI made one up): block either way.
    leaks = find_pii(PLACEHOLDER.sub(" ", masked_answer), known_names)
    if leaks:
        return f"real {leaks[0].type.lower()} in the answer"

    # 2. Every placeholder must be real and must come from what the AI was shown.
    #    One it made up (PERSON_999), or one it was never given, means it is guessing.
    shown = set(PLACEHOLDER.findall(masked_question))
    for c in chunks:
        shown |= set(PLACEHOLDER.findall(c["text"])) | {c["doc_id"]}
    for placeholder in set(PLACEHOLDER.findall(masked_answer)):
        if placeholder not in shown or not vault.placeholder_exists(placeholder):
            return f"placeholder {placeholder} was not in the passages"
    return None


class Assistant:
    """The whole system: open once, then ask() as many questions as needed."""

    def __init__(self, vault: Vault | None = None, library: SearchLibrary | None = None,
                 llm_client=None, known_names: list[str] | None = None):
        self.vault = vault or Vault.from_env()
        self.library = library or SearchLibrary()
        self.llm_client = llm_client
        self.known_names = known_names if known_names is not None else (
            json.loads(ROSTER_FILE.read_text())["employees"])

    def ask(self, question: str, user: str, role: str) -> dict:
        """Answer one question for one user. Returns {"status", "answer"}.

        status: "answered", "no_answer", "refused" (step 7) or "blocked" (step 11).
        """
        # Step 7: may they ask this at all? Checked before anything is searched or sent.
        decision = can_ask(role, question, self.known_names)
        if not decision.allowed:
            self.vault.log_event(user, role, allowed=False, purpose=f"question refused: {decision.reason}")
            return {"status": "refused", "answer": decision.reason}

        # Steps 8-10: mask the question, search, and let the AI answer from masked passages.
        masked_question = mask_question(question, self.vault, self.known_names)
        chunks = self.library.search(masked_question, k=TOP_K)
        result = generate_answer(masked_question, chunks, client=self.llm_client)
        masked_answer = format_answer(result)

        # Step 11: the final safety check. Fail closed.
        problem = check_answer(masked_answer, chunks, masked_question, self.vault, self.known_names)
        if problem:
            self.vault.log_event(user, role, allowed=False, purpose=f"answer blocked: {problem}")
            return {"status": "blocked", "answer": BLOCKED_MESSAGE}

        status = "answered" if result["answerable"] else "no_answer"
        # Step 12: HR sees real values (step 13, each one logged by the vault: step 16).
        if can_see_real_values(role):
            return {"status": status, "answer": unmask(masked_answer, self.vault, user, role,
                                                       purpose="answer to a question")}
        # Step 15: everyone else sees placeholders.
        return {"status": status, "answer": masked_answer}

    def close(self) -> None:
        self.vault.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Ask the privacy-safe assistant a question.")
    parser.add_argument("question")
    parser.add_argument("--user", required=True)
    parser.add_argument("--role", required=True, help="hr or employee")
    args = parser.parse_args()
    with Assistant() as assistant:
        result = assistant.ask(args.question, args.user, args.role)
    print(f"[{result['status']}] {result['answer']}")


if __name__ == "__main__":
    main()
