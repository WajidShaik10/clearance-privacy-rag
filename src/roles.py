"""Steps 7 and 12: permission checks.

- Step 7: may this user ask this question at all? (checked before any search)
- Step 12: may this user see real values (HR) or only placeholders?

Rules, in plain words:
- HR may ask anything and see real values (each reveal is logged by the vault).
- Employees may ask about policies and rules ("How many sick days do I get?").
  They may not ask about a specific person, or for other people's sensitive
  details (pay, IDs, bank, address, health...): those are refused up front.
- Any other role is refused: deny by default.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from src.detect import find_pii

HR = "hr"
EMPLOYEE = "employee"
ROLES = {HR, EMPLOYEE}

# Words asking for someone's sensitive details. ("paid" and "health" are left out:
# "paid sick leave" and "health insurance" are policy topics.)
SENSITIVE_TOPIC = re.compile(
    r"\b(salar(y|ies)|pay|wages?|earn(s|ed|ing)?|compensation|bonus(es)?|raises?"
    r"|ssn|social security|tax(payer)? id|itin|ein|bank|account numbers?|routing"
    r"|address(es)?|phone|email|date of birth|birthdays?|dob|age"
    r"|performance reviews?|disciplinary|medical|emergency contacts?)\b", re.I)

# Words pointing at OTHER people. Plain "employees" is not one of them: "do employees
# get 8 sick days?" is about the rules. "employee's", "everyone", "who" or "John's" are.
OTHER_PEOPLE = re.compile(
    # the word list ignores case ("Who", "who"); a name's possessive ("John's") needs its capital
    r"(?i:\b(employee['’]s|employees['’]|everyone(['’]s)?|everybody|all|each|anyone|someone(['’]s)?"
    r"|colleagues?|co-?workers?|team|managers?(['’]s)?|boss|who|whose|list|top|highest|lowest"
    r"|average|others?|other people)\b)"
    r"|\b[A-Z][a-z]+['’]s\b")


# PERSON_5, or PERSON-5 / person 5. Only our own types, so "Form W-4" or "COVID-19" are not caught.
PLACEHOLDER_TYPES = ("PERSON", "SSN", "ITIN", "EIN", "PHONE", "EMAIL", "EMPLOYEE_ID", "DOB",
                     "BANK_ROUTING", "BANK_ACCOUNT", "ADDRESS", "MONEY", "DOC")
PLACEHOLDER_SHAPE = re.compile(r"\b(?:" + "|".join(PLACEHOLDER_TYPES) + r")[_ -]\d+\b", re.I)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str  # shown to the user when refused, and written to the log


def can_ask(role: str, question: str, known_names: Iterable[str] = ()) -> Decision:
    """Step 7: decide before searching whether this user may ask this question."""
    if role not in ROLES:
        return Decision(False, f"Unknown role {role!r}: access denied.")
    if role == HR:
        return Decision(True, "HR may ask about any employee.")

    # Typing a placeholder ("What is PERSON_5's salary?") is asking about one person's record.
    if PLACEHOLDER_SHAPE.search(question):
        return Decision(False, "Questions about a specific record (placeholder) are limited to HR.")
    personal = [f for f in find_pii(question, known_names) if f.type != "MONEY"]
    if personal:
        kinds = ", ".join(sorted({f.type.lower().replace("_", " ") for f in personal}))
        return Decision(False, f"Questions about a specific person ({kinds}) are limited to HR.")
    if SENSITIVE_TOPIC.search(question) and OTHER_PEOPLE.search(question):
        return Decision(False, "Questions about other people's pay or personal details are limited to HR.")
    return Decision(True, "General question about policies or rules.")


def can_see_real_values(role: str) -> bool:
    """Step 12: only HR sees real values; everyone else sees placeholders."""
    return role == HR
