"""Steps 5 and 9: split masked pages into passages, store them, and search them.

Only masked text is ever stored here. Each passage keeps its doc name and page
number so answers can cite them.
"""


def add_pages(masked_pages: list[dict]) -> None:
    """Split masked pages into passages and add them to the search library."""
    raise NotImplementedError("Milestone 5")


def search(masked_question: str, k: int = 5) -> list[dict]:
    """Return the k best passages: [{"doc", "page", "text", "score"}, ...]."""
    raise NotImplementedError("Milestone 5")
