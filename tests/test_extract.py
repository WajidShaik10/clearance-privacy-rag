"""Milestone 2: reading text out of the PDFs."""

import json
from pathlib import Path

import pymupdf
import pytest

from src.extract import read_digital_page

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "data" / "fake_docs"
KEY = json.loads((ROOT / "data" / "answer_key.json").read_text())
DIGITAL = [d for d in KEY["documents"] if not d["scanned"]]


def page_text(file: str, page: int = 1) -> str:
    with pymupdf.open(DOCS / file) as pdf:
        return read_digital_page(pdf[page - 1])


# ---------------------------------------------------------------- function 1: read_digital_page

def test_footer_comes_last():
    lines = page_text("payslip_september_2025_johnson.pdf").splitlines()
    assert lines[0] == "Brightline Logistics LLC"
    assert "Confidential" in lines[-1]


def test_table_row_stays_on_one_line():
    lines = page_text("payslip_september_2025_johnson.pdf").splitlines()
    assert "Employee Danielle Johnson Employee ID EMP-1040" in lines


@pytest.mark.parametrize("doc", DIGITAL, ids=lambda d: d["file"])
def test_every_private_value_is_read_on_its_page(doc):
    for item in doc["pii"]:
        text = " ".join(page_text(doc["file"], item["page"]).split())
        value = " ".join(item["value"].split())
        digits = "".join(c for c in value if c.isdigit())
        found = value in text or (digits and digits in "".join(c for c in text if c.isdigit()))
        assert found, item


def test_scanned_page_gives_no_text():
    assert page_text("scan_w4_olson.pdf") == ""


# ---------------------------------------------------------------- function 2: group_into_rows

def test_form_box_stays_whole():
    # On the W-2, the employer address box sits next to the wage boxes.
    # Sorting single words mixed "5 Medicare wages" into the middle of the address.
    lines = page_text("w2_2025_johnson.pdf").splitlines()
    address_line = next(l for l in lines if "Brightline Logistics LLC" in l)
    assert "Brightline Logistics LLC 200 W Lakeview Ave, Suite 900 Chicago, IL 60606" in address_line
    assert "Medicare" not in address_line


def test_two_line_table_cell_stays_with_its_row():
    # The directory's address cell wraps onto two lines; it must stay on the person's row.
    lines = page_text("employee_directory.pdf").splitlines()
    row = next(l for l in lines if l.startswith("Danielle Johnson"))
    assert row.endswith("819 Johnson Course East William, IL 60608")


def test_side_by_side_boxes_share_a_row():
    from src.extract import group_into_rows

    left = (40, 98, 300, 130, "Brightline Logistics LLC", 0, 0)
    right = (417, 96, 570, 108, "59500.00", 1, 0)
    lower = (339, 109, 570, 120, "5 Medicare wages", 2, 0)
    rows = group_into_rows([lower, right, left])
    assert rows == [[left, right], [lower]]


# ---------------------------------------------------------------- function 3: is_scanned

@pytest.mark.parametrize("doc", KEY["documents"], ids=lambda d: d["file"])
def test_scan_detection_matches_answer_key(doc):
    from src.extract import is_scanned

    with pymupdf.open(DOCS / doc["file"]) as pdf:
        assert all(is_scanned(page) == doc["scanned"] for page in pdf)


def test_blank_page_is_not_a_scan():
    from src.extract import is_scanned

    with pymupdf.open() as pdf:
        assert not is_scanned(pdf.new_page())


def test_digital_page_with_logo_is_not_a_scan():
    # The W-2 carries small IRS logo images but plenty of real text.
    from src.extract import is_scanned

    with pymupdf.open(DOCS / "w2_2025_johnson.pdf") as pdf:
        page = pdf[0]
        assert page.get_image_info()
        assert not is_scanned(page)


# ---------------------------------------------------------------- function 4: read_scanned_page

SCANNED = [d for d in KEY["documents"] if d["scanned"]]


@pytest.fixture(scope="module")
def ocr_results():
    """OCR every scanned page once (it takes a few seconds) and share it across tests."""
    from src.extract import read_scanned_page

    results = {}
    for doc in SCANNED:
        with pymupdf.open(DOCS / doc["file"]) as pdf:
            results[doc["file"]] = [read_scanned_page(page) for page in pdf]
    return results


@pytest.mark.parametrize("doc", SCANNED, ids=lambda d: d["file"])
def test_ocr_reads_every_private_value(doc, ocr_results):
    # A misread value would slip past PII detection, so OCR must get every one exactly.
    for item in doc["pii"]:
        text, _ = ocr_results[doc["file"]][item["page"] - 1]
        assert " ".join(item["value"].split()) in " ".join(text.split()), item


@pytest.mark.parametrize("doc", SCANNED, ids=lambda d: d["file"])
def test_ocr_confidence_is_high_on_our_scans(doc, ocr_results):
    from src.extract import LOW_OCR_CONFIDENCE

    for _, confidence in ocr_results[doc["file"]]:
        assert LOW_OCR_CONFIDENCE <= confidence <= 1.0


def test_blank_page_gives_no_text_and_zero_confidence():
    from src.extract import read_scanned_page

    with pymupdf.open() as pdf:
        assert read_scanned_page(pdf.new_page()) == ("", 0.0)


# ---------------------------------------------------------------- function 5: read_metadata

def test_hidden_title_with_employee_name_is_read():
    from src.extract import read_metadata

    with pymupdf.open(DOCS / "personnel_file_heath.pdf") as pdf:
        hidden = read_metadata(pdf, "personnel_file_heath.pdf")
    assert hidden["file_name"] == "personnel_file_heath.pdf"
    assert hidden["title"] == "personnel_file_heath"


def test_filler_values_are_skipped():
    # ReportLab writes "(anonymous)" as author: there is nothing to scan there.
    from src.extract import read_metadata

    with pymupdf.open(DOCS / "personnel_file_heath.pdf") as pdf:
        hidden = read_metadata(pdf, "personnel_file_heath.pdf")
    assert "author" not in hidden and "subject" not in hidden


def test_file_without_metadata_still_reports_its_name():
    from src.extract import read_metadata

    with pymupdf.open(DOCS / "scan_w4_olson.pdf") as pdf:
        assert read_metadata(pdf, "scan_w4_olson.pdf") == {"file_name": "scan_w4_olson.pdf"}


def test_comments_are_read():
    from src.extract import read_metadata

    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.add_text_annot((72, 72), "Approved raise for Rebecca Heath")
        page.insert_text((72, 120), "Quarterly review")
        hidden = read_metadata(pdf, "review.pdf")
    assert hidden["comments"] == "page 1: Approved raise for Rebecca Heath"


# ---------------------------------------------------------------- function 6: extract_document

@pytest.fixture(scope="module")
def extracted():
    """Extract all 22 documents once (OCR takes a few seconds) and share the results."""
    from src.extract import extract_document

    return {doc["file"]: extract_document(DOCS / doc["file"]) for doc in KEY["documents"]}


@pytest.mark.parametrize("doc", KEY["documents"], ids=lambda d: d["file"])
def test_every_private_value_comes_out_on_its_page(doc, extracted):
    # The milestone's finish line: nothing in the answer key is lost, digital or scanned.
    result = extracted[doc["file"]]
    assert [p["page"] for p in result["pages"]] == list(range(1, doc["pages"] + 1))
    for item in doc["pii"]:
        text = " ".join(result["pages"][item["page"] - 1]["text"].split())
        value = " ".join(item["value"].split())
        digits = "".join(c for c in value if c.isdigit())
        found = value in text or (digits and digits in "".join(c for c in text if c.isdigit()))
        assert found, item


@pytest.mark.parametrize("doc", KEY["documents"], ids=lambda d: d["file"])
def test_right_reading_method_per_document(doc, extracted):
    methods = {p["method"] for p in extracted[doc["file"]]["pages"]}
    assert methods == ({"ocr"} if doc["scanned"] else {"digital"})


def test_hidden_info_travels_with_the_document(extracted):
    assert extracted["personnel_file_heath.pdf"]["hidden"]["title"] == "personnel_file_heath"


def test_payroll_rows_are_kept_on_every_page(extracted):
    # A "delete lines that repeat on every page" footer rule would have erased these.
    pages = extracted["payroll_register_q3_2025.pdf"]["pages"]
    assert all("EMP-1040 Danielle Johnson 282-32-3658" in p["text"] for p in pages)


def test_low_confidence_ocr_is_flagged(monkeypatch):
    import src.extract as extract

    monkeypatch.setattr(extract, "read_scanned_page", lambda page: ("blurry text", 0.55))
    result = extract.extract_document(DOCS / "scan_w4_olson.pdf")
    assert result["pages"][0]["needs_review"] is True
    assert result["needs_review"] is True


def test_our_documents_need_no_review(extracted):
    assert not any(result["needs_review"] for result in extracted.values())


def test_password_protected_pdf_is_refused(tmp_path):
    from src.extract import extract_document

    locked = tmp_path / "locked.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((72, 72), "secret")
        pdf.save(locked, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    with pytest.raises(ValueError, match="password-protected"):
        extract_document(locked)
