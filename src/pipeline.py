"""Steps 6, 14, 15 and Blocked: run a question through every step in order.

question -> roles.can_ask -> mask -> index.search -> answer -> detect (guard)
         -> roles.can_see_real_values -> unmask (HR) or masked answer (everyone else)
"""

BLOCKED_MESSAGE = "Sorry, I can't share that."


def ask(question: str, user: str, role: str) -> str:
    """Answer a question for this user, never exposing private data they may not see."""
    raise NotImplementedError("Milestone 6-7")
