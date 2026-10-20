"""The locked safe and step 16 (audit log).

Stores placeholder -> encrypted real value. Values are looked up by a keyed hash,
so finding a placeholder never needs decryption. Every decrypt is logged.
"""


def get_or_create_placeholder(value: str, pii_type: str) -> str:
    """Return the placeholder for this value, creating one (e.g. SSN_3) if new."""
    raise NotImplementedError("Milestone 4")


def reveal(placeholder: str, user: str) -> str:
    """Decrypt a placeholder's real value and write an audit log entry."""
    raise NotImplementedError("Milestone 7")
