"""Step 10: ask the AI model to answer from the passages, with page citations.

The model only ever receives masked text. The provider (Claude API or a local
model) is pluggable and chosen at Milestone 6.
"""


def generate_answer(masked_question: str, passages: list[dict]) -> str:
    """Return a masked answer such as 'PERSON_1 earns SALARY_1 [payroll.pdf, p.4]'."""
    raise NotImplementedError("Milestone 6")
