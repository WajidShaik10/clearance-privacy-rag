"""The locked safe and step 16 (audit log).

Each private value is stored twice:
  - encrypted (Fernet / AES): unreadable without the key, unlocked only for HR
  - as a keyed fingerprint (HMAC-SHA256): the same every time for the same
    value, so "have I seen Danielle before?" is answered without decrypting

Every unlock, allowed or refused, is written to the audit log.
The two secret keys come from the environment (.env), never from the code.

    python -m src.vault     # create a .env with two new keys (first-time setup)
"""

import hashlib
import hmac
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "vault" / "vault.db"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
ALLOWED_ROLE = "hr"  # only HR may see real values

# Types whose value is a number however it is written: "282-32-3658" = "2 8 2 3 2 3 6 5 8".
NUMBER_TYPES = {"SSN", "ITIN", "EIN", "PHONE", "BANK_ROUTING", "BANK_ACCOUNT", "MONEY", "DOB"}


def normalize(value: str, pii_type: str) -> str:
    """Write a value one standard way, so every spelling of it gets the same fingerprint."""
    if pii_type in NUMBER_TYPES:
        # Keep a leading minus for money: -$694.17 is not $694.17.
        sign = "-" if pii_type == "MONEY" and value.strip().startswith("-") else ""
        return sign + re.sub(r"[^\dA-Za-z]", "", value).upper()
    return " ".join(value.split()).casefold()  # names, addresses, emails: ignore case and spacing


class Vault:
    def __init__(self, path: str | Path, encryption_key: bytes, index_key: bytes):
        if encryption_key == index_key:
            raise ValueError("Use two different keys: if one leaks, the other must stay safe")
        self._fernet = Fernet(encryption_key)
        self._index_key = index_key
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS entries (
                placeholder TEXT PRIMARY KEY,   -- PERSON_1
                pii_type    TEXT NOT NULL,      -- PERSON
                fingerprint TEXT NOT NULL UNIQUE,
                encrypted   BLOB NOT NULL,
                created_at  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id          INTEGER PRIMARY KEY,
                at          TEXT NOT NULL,
                user        TEXT NOT NULL,
                role        TEXT NOT NULL,
                placeholder TEXT NOT NULL,
                allowed     INTEGER NOT NULL,
                purpose     TEXT NOT NULL
            );
        """)

    @classmethod
    def from_env(cls, path: str | Path = DEFAULT_PATH) -> "Vault":
        """Open the vault with the keys from .env (VAULT_ENCRYPTION_KEY, VAULT_INDEX_KEY)."""
        from dotenv import load_dotenv

        load_dotenv(ENV_FILE)
        try:
            return cls(path, os.environ["VAULT_ENCRYPTION_KEY"].encode(), os.environ["VAULT_INDEX_KEY"].encode())
        except KeyError as missing:
            raise RuntimeError(f"{missing} is not set: run `python -m src.vault` to create keys") from None

    # ------------------------------------------------------------ masking side

    def fingerprint(self, value: str, pii_type: str) -> str:
        # The type is part of the fingerprint, so an SSN and an account number
        # that happen to share digits never share a placeholder.
        message = f"{pii_type}:{normalize(value, pii_type)}".encode()
        return hmac.new(self._index_key, message, hashlib.sha256).hexdigest()

    def find_placeholder(self, value: str, pii_type: str) -> str | None:
        """Look a value up without storing anything (for user questions). None if unknown."""
        fp = self.fingerprint(value, pii_type)
        row = self._db.execute("SELECT placeholder FROM entries WHERE fingerprint = ?", (fp,)).fetchone()
        return row[0] if row else None

    def get_placeholder(self, value: str, pii_type: str) -> str:
        """Return this value's placeholder, storing it (encrypted) the first time it is seen."""
        existing = self.find_placeholder(value, pii_type)
        if existing:
            return existing  # seen before: same value, same placeholder
        fp = self.fingerprint(value, pii_type)

        with self._db:  # one transaction: the number and the new row are saved together
            count = self._db.execute("SELECT COUNT(*) FROM entries WHERE pii_type = ?", (pii_type,)).fetchone()[0]
            placeholder = f"{pii_type}_{count + 1}"
            self._db.execute(
                "INSERT INTO entries VALUES (?, ?, ?, ?, ?)",
                (placeholder, pii_type, fp, self._fernet.encrypt(value.encode()), _now()),
            )
        return placeholder

    # ------------------------------------------------------------ unmasking side

    def reveal(self, placeholder: str, user: str, role: str, purpose: str = "") -> str:
        """Unlock a placeholder's real value. HR only; every attempt is logged."""
        allowed = role == ALLOWED_ROLE
        with self._db:
            self._db.execute(
                "INSERT INTO audit_log (at, user, role, placeholder, allowed, purpose) VALUES (?, ?, ?, ?, ?, ?)",
                (_now(), user, role, placeholder, int(allowed), purpose),
            )
        if not allowed:
            raise PermissionError(f"{user} ({role}) may not see real values")

        row = self._db.execute("SELECT encrypted FROM entries WHERE placeholder = ?", (placeholder,)).fetchone()
        if row is None:
            raise KeyError(f"No such placeholder: {placeholder}")
        return self._fernet.decrypt(row[0]).decode()

    def log_event(self, user: str, role: str, allowed: bool, purpose: str) -> None:
        """Log something other than a reveal, e.g. a refused question or a blocked answer.

        Only who, when and why: never the question itself, which may hold a name or an SSN.
        """
        with self._db:
            self._db.execute(
                "INSERT INTO audit_log (at, user, role, placeholder, allowed, purpose) VALUES (?, ?, ?, ?, ?, ?)",
                (_now(), user, role, "-", int(allowed), purpose),
            )

    def placeholder_exists(self, placeholder: str) -> bool:
        """Used by the output guard: is this a real placeholder or one the AI made up?"""
        return self._db.execute("SELECT 1 FROM entries WHERE placeholder = ?", (placeholder,)).fetchone() is not None

    def audit_log(self) -> list[dict]:
        rows = self._db.execute(
            "SELECT at, user, role, placeholder, allowed, purpose FROM audit_log ORDER BY id").fetchall()
        return [dict(zip(("at", "user", "role", "placeholder", "allowed", "purpose"), r)) for r in rows]

    def close(self) -> None:
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_keys() -> dict[str, str]:
    """Two fresh, random keys: one to encrypt, one to fingerprint."""
    return {
        "VAULT_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "VAULT_INDEX_KEY": Fernet.generate_key().decode(),
    }


if __name__ == "__main__":
    if ENV_FILE.exists() and "VAULT_ENCRYPTION_KEY" in ENV_FILE.read_text():
        print(f"{ENV_FILE} already has vault keys; not overwriting them (that would lock the vault forever).")
    else:
        with ENV_FILE.open("a") as f:
            f.writelines(f"{k}={v}\n" for k, v in new_keys().items())
        print(f"Wrote two new vault keys to {ENV_FILE} (git ignores this file). Keep a backup somewhere safe.")
