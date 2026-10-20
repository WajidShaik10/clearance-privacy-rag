"""Steps 7 and 12: permission checks.

- Step 7: is this user allowed to ask this question at all?
- Step 12: may this user see real values (HR) or only placeholders?
"""

HR = "hr"
EMPLOYEE = "employee"


def can_ask(role: str, question: str) -> bool:
    """Refuse risky questions early (e.g. a non-HR user asking for one person's salary)."""
    raise NotImplementedError("Milestone 7")


def can_see_real_values(role: str) -> bool:
    return role == HR
