"""Milestone 3: finding private data."""

import pytest

from src.detect import contains_pii, find_pii, find_pii_in_document

ROSTER = ["Rebecca Heath", "Nicole Day", "Ryan Rush"]


def found(text, known_names=()):
    return [(f.type, f.value) for f in find_pii(text, known_names)]


# ---------------------------------------------------------------- numbers with rules

def test_ssn_found():
    assert found("SSN 282-32-3658") == [("SSN", "282-32-3658")]


@pytest.mark.parametrize("impossible", ["000-12-3456", "666-12-3456", "282-00-3658", "282-32-0000"])
def test_impossible_ssns_are_ignored(impossible):
    # The SSA never issues these, so they are not SSNs.
    assert ("SSN", impossible) not in found(f"number {impossible}")


def test_itin_found():
    assert found("ITIN 975-92-9246") == [("ITIN", "975-92-9246")]


def test_tax_id_printed_one_digit_per_box():
    # The W-9 prints each digit in its own box: "9 7 5 9 2 9 2 4 6".
    assert found("TIN 9 7 5 9 2 9 2 4 6") == [("ITIN", "9 7 5 9 2 9 2 4 6")]


def test_ein_found():
    assert ("EIN", "36-4817205") in found("EIN 36-4817205")


def test_phone_and_email_found():
    assert found("call (312) 555-0110 or rebecca.heath@example.com") == [
        ("PHONE", "(312) 555-0110"), ("EMAIL", "rebecca.heath@example.com")]


def test_routing_number_needs_valid_checksum_and_context():
    assert ("BANK_ROUTING", "075133384") in found("routing 075133384")
    assert ("BANK_ROUTING", "075133385") not in found("routing 075133385")  # bad checksum
    assert ("BANK_ROUTING", "075133384") not in found("order 075133384")  # no bank context


def test_account_number_needs_context():
    assert ("BANK_ACCOUNT", "726247317810") in found("account 726247317810")
    assert found("tracking 726247317810") == []


def test_only_birth_dates_are_private():
    assert found("Date of birth 12/03/1974") == [("DOB", "12/03/1974")]
    assert found("Pay date 09/30/2025") == []


def test_social_security_tax_line_is_money_not_an_ssn():
    # On a payslip, "Social Security" is a tax; the amount is money, not an SSN.
    assert found("Social Security -$307.42") == [("MONEY", "-$307.42")]


@pytest.mark.parametrize("amount", ["$4,958.33", "-$694.17", "$85,000", "59500.00"])
def test_money_found(amount):
    assert found(f"amount {amount}") == [("MONEY", amount)]


# ---------------------------------------------------------------- addresses

def test_street_and_city_are_one_address():
    # The two address patterns overlap here; neither piece may be left exposed.
    assert found("819 Johnson Course East William, IL 60608") == [
        ("ADDRESS", "819 Johnson Course East William, IL 60608")]


def test_apartment_numbers_are_part_of_the_address():
    assert found("0154 Brian Wells Apt. 171") == [("ADDRESS", "0154 Brian Wells Apt. 171")]


def test_company_address_is_not_personal():
    assert found("Brightline Logistics LLC 200 W Lakeview Ave, Suite 900 Chicago, IL 60606") == []


# ---------------------------------------------------------------- names

def test_roster_name_found_in_a_table_row():
    # The AI alone misses names in table rows; HR's roster catches them.
    assert ("PERSON", "Nicole Day") in found("Nicole Day Finance Payroll Specialist", ROSTER)


def test_name_that_is_also_a_word_is_not_hidden_everywhere():
    # "Day" and "Rush" are ordinary words: only the full name or a title + last name count.
    assert found("The project was a rush, finished in one day.", ROSTER) == []


def test_first_name_and_title_variants_of_roster_names():
    text = "Rebecca met the deadline. Mx. Heath mentored two hires."
    assert found(text, ROSTER) == [("PERSON", "Rebecca"), ("PERSON", "Mx. Heath")]


def test_ai_finds_names_outside_the_roster():
    assert ("PERSON", "Alexis Davis") in found("Emergency contact: Alexis Davis, (312) 555-0132")


def test_ai_name_with_trailing_line_break():
    # On the real W-9, spaCy returned "Samantha Hooper\n"; the name must still count.
    from src.extract import extract_document

    text = extract_document("data/fake_docs/w9_hooper.pdf")["pages"][0]["text"]
    assert ("PERSON", "Samantha Hooper") in found(text)


def test_possessive_is_not_part_of_the_name():
    # "Samantha Hooper's" must match the vault's "Samantha Hooper".
    assert found("What is Samantha Hooper's taxpayer identification number?") == [("PERSON", "Samantha Hooper")]


def test_apostrophe_and_hyphen_names():
    assert found("Full Name: Pat O'Neil") == [("PERSON", "Pat O'Neil")]
    assert found("Signature: Luce Lefort-Auger") == [("PERSON", "Luce Lefort-Auger")]


def test_names_carry_across_pages_of_a_document():
    pages = ["Personnel File: Rebecca Heath", "Rebecca requested a schedule change."]
    assert [(f.type, f.value) for f in find_pii_in_document(pages, ROSTER)[1]] == [("PERSON", "Rebecca")]


# ---------------------------------------------------------------- formats added after testing on unseen data

@pytest.mark.parametrize("phone", ["+1-123-456-7890", "1-800-123-4567", "+1 (800) 123-4567", "312.555.0110"])
def test_phone_formats(phone):
    assert found(f"call {phone} today") == [("PHONE", phone)]


def test_ten_plain_digits_are_a_phone_only_next_to_a_phone_word():
    assert found("Phone: 6774125602") == [("PHONE", "6774125602")]
    assert found("Invoice 6774125602") == []


def test_iban_found():
    assert ("BANK_ACCOUNT", "GB36LUIE38711470005097") in found("pay to GB36LUIE38711470005097")


def test_street_address_continues_into_city_and_country():
    assert found("Ship to 123 Maple Street, Anytown, USA.") == [("ADDRESS", "123 Maple Street, Anytown, USA")]


@pytest.mark.parametrize("text, name", [
    ("Signature: Luigi Clelia Togliatti", "Luigi Clelia Togliatti"),
    ("Full Name: John Doe", "John Doe"),
    ("Borrower: Pedro", "Pedro"),
    ("**User:** Annibale Caboto ([email])", "Annibale Caboto"),
    ("Dear Mr. Booth,", "Booth"),
    ("Hi, my name is Ilaria.", "Ilaria"),
    ("[2022-08-15 14:31:21] - Paul Sanders: Hi, I need help", "Paul Sanders"),
    ("Reviewer: Richard Olson. Rebecca met deadlines.", "Richard Olson"),  # stops at the full stop
])
def test_names_after_labels(text, name):
    assert ("PERSON", name) in found(text)


def test_first_name_of_a_labelled_name_is_found_later():
    text = "**User:** Annibale Caboto\nUpdated Annibale's access level."
    assert ("PERSON", "Annibale") in found(text)


def test_labelled_ids_and_accounts():
    assert ("EMPLOYEE_ID", "Nm-80877") in found("My employee_id is Nm-80877")
    assert ("BANK_ACCOUNT", "RBKJ59644698401273") in found("BBAN: RBKJ59644698401273")


def test_account_table_header_is_not_an_account():
    # On our payslip, "Account number Amount" is a header followed by a word, not a number.
    assert found("Bank Routing number Account number Amount") == []


# ---------------------------------------------------------------- the guard (step 11)

def test_guard_flags_an_answer_with_pii():
    assert contains_pii("Rebecca Heath's SSN is 073-66-3900", ROSTER)


def test_guard_passes_a_masked_answer():
    assert not contains_pii("PERSON_1 earns SALARY_1 [DOC_3, page 2]", ROSTER)


def test_guard_passes_a_policy_answer():
    assert not contains_pii("Employees get 12 weeks of paid parental leave.", ROSTER)


# ---------------------------------------------------------------- the whole answer key

@pytest.fixture(scope="module")
def evaluation():
    from scripts.evaluate_detection import evaluate

    return evaluate()


def test_every_private_value_in_the_answer_key_is_found(evaluation):
    missed = {t: items for t, items in evaluation["misses"].items() if items}
    assert not missed


def test_no_false_alarms_on_the_policy_document(evaluation):
    assert evaluation["policy_findings"] == []


# ---------------------------------------------------------------- unseen documents (Gretel)

def test_recall_on_unseen_documents_does_not_drop():
    # A guard against changes that quietly make detection worse. The held-out
    # test split scored 68.1% (up from 41.0%); this fails if it drops below 65%.
    from scripts.evaluate_unseen import DATA, IN_SCOPE, evaluate

    if not list(DATA.glob("rows_*.json")):
        pytest.skip("Gretel sample not downloaded")
    r = evaluate("test")
    caught = sum(r["caught"][label] for label in IN_SCOPE)
    total = sum(r["total"][label] for label in IN_SCOPE)
    assert caught / total >= 0.65
