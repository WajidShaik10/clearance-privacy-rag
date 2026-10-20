"""Steps 4, 8 and 13: swap real values for placeholders and back.

- Step 4: mask a document page   "John Smith" -> "PERSON_1"
- Step 8: mask the user question with the same placeholders
- Step 13: unmask an answer for HR "PERSON_1" -> "John Smith"
"""


def mask(text: str) -> str:
    """Replace every private value with its placeholder (same value -> same placeholder)."""
    raise NotImplementedError("Milestone 4")


def unmask(text: str, user: str) -> str:
    """Replace placeholders with real values from the vault. HR only; every call is audit-logged."""
    raise NotImplementedError("Milestone 7")
