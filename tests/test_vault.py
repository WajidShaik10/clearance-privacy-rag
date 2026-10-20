"""Milestone 4: the locked vault."""

import pytest
from cryptography.fernet import Fernet, InvalidToken

from src.vault import Vault, new_keys, normalize


@pytest.fixture
def keys():
    k = new_keys()
    return k["VAULT_ENCRYPTION_KEY"].encode(), k["VAULT_INDEX_KEY"].encode()


@pytest.fixture
def vault(tmp_path, keys):
    with Vault(tmp_path / "vault.db", *keys) as v:
        yield v


# ---------------------------------------------------------------- masking side

def test_new_value_gets_a_numbered_placeholder(vault):
    assert vault.get_placeholder("Danielle Johnson", "PERSON") == "PERSON_1"
    assert vault.get_placeholder("Rebecca Heath", "PERSON") == "PERSON_2"
    assert vault.get_placeholder("282-32-3658", "SSN") == "SSN_1"  # each type counts on its own


def test_same_value_gets_the_same_placeholder_every_time(vault):
    first = vault.get_placeholder("Danielle Johnson", "PERSON")
    assert vault.get_placeholder("Danielle Johnson", "PERSON") == first


@pytest.mark.parametrize("spelling", ["282-32-3658", "282 32 3658", "2 8 2 3 2 3 6 5 8"])
def test_every_spelling_of_a_number_is_the_same_value(vault, spelling):
    # The W-9 prints an SSN one digit per box; it is still the same SSN.
    vault.get_placeholder("282-32-3658", "SSN")
    assert vault.get_placeholder(spelling, "SSN") == "SSN_1"


def test_names_ignore_case_and_extra_spaces(vault):
    vault.get_placeholder("Danielle Johnson", "PERSON")
    assert vault.get_placeholder("danielle  JOHNSON", "PERSON") == "PERSON_1"


def test_money_keeps_its_sign():
    assert normalize("-$694.17", "MONEY") != normalize("$694.17", "MONEY")


def test_same_digits_of_different_types_stay_apart(vault):
    assert vault.get_placeholder("123456789", "BANK_ACCOUNT") == "BANK_ACCOUNT_1"
    assert vault.get_placeholder("123456789", "BANK_ROUTING") == "BANK_ROUTING_1"


def test_vault_file_contains_no_readable_private_values(tmp_path, keys):
    with Vault(tmp_path / "vault.db", *keys) as v:
        for value, kind in [("Danielle Johnson", "PERSON"), ("282-32-3658", "SSN"), ("654235116155", "BANK_ACCOUNT")]:
            v.get_placeholder(value, kind)
    raw = (tmp_path / "vault.db").read_bytes()
    for secret in [b"Danielle", b"Johnson", b"282-32-3658", b"282323658", b"654235116155"]:
        assert secret not in raw


def test_placeholders_survive_closing_and_reopening(tmp_path, keys):
    with Vault(tmp_path / "vault.db", *keys) as v:
        v.get_placeholder("Danielle Johnson", "PERSON")
    with Vault(tmp_path / "vault.db", *keys) as v:
        assert v.get_placeholder("Danielle Johnson", "PERSON") == "PERSON_1"


# ---------------------------------------------------------------- unmasking side

def test_hr_can_reveal_and_it_is_logged(vault):
    vault.get_placeholder("Danielle Johnson", "PERSON")
    assert vault.reveal("PERSON_1", user="priya", role="hr", purpose="payroll check") == "Danielle Johnson"
    entry = vault.audit_log()[-1]
    assert (entry["user"], entry["placeholder"], entry["allowed"], entry["purpose"]) == (
        "priya", "PERSON_1", 1, "payroll check")


def test_non_hr_is_refused_and_the_attempt_is_logged(vault):
    vault.get_placeholder("Danielle Johnson", "PERSON")
    with pytest.raises(PermissionError):
        vault.reveal("PERSON_1", user="ravi", role="employee")
    entry = vault.audit_log()[-1]
    assert (entry["user"], entry["allowed"]) == ("ravi", 0)


def test_unknown_placeholder(vault):
    with pytest.raises(KeyError):
        vault.reveal("PERSON_99", user="priya", role="hr")
    assert not vault.placeholder_exists("PERSON_99")


def test_wrong_encryption_key_cannot_unlock(tmp_path, keys):
    encryption_key, index_key = keys
    with Vault(tmp_path / "vault.db", encryption_key, index_key) as v:
        v.get_placeholder("Danielle Johnson", "PERSON")
    with Vault(tmp_path / "vault.db", Fernet.generate_key(), index_key) as thief:
        with pytest.raises(InvalidToken):
            thief.reveal("PERSON_1", user="thief", role="hr")


def test_two_keys_must_differ(tmp_path):
    key = Fernet.generate_key()
    with pytest.raises(ValueError):
        Vault(tmp_path / "vault.db", key, key)
