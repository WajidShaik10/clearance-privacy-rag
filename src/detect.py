"""Steps 3 and 11: find private info (SSN, EIN/ITIN, names, addresses, phones,
bank details, salaries).

The same detector scans documents at ingestion (step 3) and every AI answer
before it reaches the user (step 11), so the safety check is never weaker
than ingestion.
"""


def find_pii(text: str) -> list[dict]:
    """Return [{"type": "SSN", "value": "123-45-6789", "start": 10, "end": 21}, ...]."""
    raise NotImplementedError("Milestone 3")


def contains_pii(text: str) -> bool:
    """Step 11 guard: True if any private value is found in the text."""
    return bool(find_pii(text))
