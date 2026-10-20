"""Steps 1-2: open PDFs and read their text page by page (OCR for scanned pages).

Output of extract_document():
    {"doc": "payroll.pdf",
     "hidden": {"file_name": ..., "title": ...},        # text not printed on pages
     "pages": [{"page": 4, "text": "...", "method": "digital",
                "confidence": 1.0, "needs_review": False}, ...],
     "needs_review": False}

Raw text still contains real PII here, so it is never written to disk.
"""

import io
from pathlib import Path

import pymupdf
import pytesseract
from PIL import Image


ROW_TOLERANCE = 4  # points: blocks whose tops are this close sit on the same row
MIN_TEXT_CHARS = 20  # fewer characters than this means the page has no real text layer
MIN_IMAGE_COVER = 0.5  # a scan is one picture covering most of the page
OCR_DPI = 300  # at 150 dpi OCR garbled "4746 Moore Hill" into "(22 Mowe fal"
LOW_OCR_CONFIDENCE = 0.80  # below this, a page should be checked by a person
METADATA_FIELDS = ("title", "author", "subject", "keywords", "creator", "producer")
EMPTY_METADATA = {"", "(anonymous)", "(unspecified)", "untitled"}  # filler values PDF tools write


def read_digital_page(page: pymupdf.Page) -> str:
    """Return a normal (not scanned) page's text in reading order.

    A PDF stores text with positions, not in reading order. PyMuPDF groups the
    words into blocks (a form box, a table cell, a paragraph); we keep each
    block whole and arrange the blocks top to bottom, left to right.
    """
    # Each block comes back as (x0, y0, x1, y1, text, block_no, block_type).
    # x0 = distance from the left edge, y0 = distance from the top.
    # block_type 0 is text (1 would be an image); skip empty blocks.
    blocks = [b for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()]
    rows = group_into_rows(blocks)
    return "\n".join(" | ".join(" ".join(b[4].split()) for b in row) for row in rows)


def group_into_rows(blocks: list) -> list[list]:
    """Group blocks that sit side by side into rows, in reading order.

    Rows go top to bottom; inside a row, blocks go left to right. Two blocks
    share a row when their tops are within ROW_TOLERANCE of the row's first
    block, so a form's left box and right box stay on one line while each
    box's own text stays together.
    """
    rows: list[list] = []
    for block in sorted(blocks, key=lambda b: (b[1], b[0])):  # top to bottom
        if rows and block[1] - rows[-1][0][1] <= ROW_TOLERANCE:
            rows[-1].append(block)  # close enough in height: same row
        else:
            rows.append([block])  # lower down the page: start a new row
    for row in rows:
        row.sort(key=lambda b: b[0])  # left to right inside the row
    return rows


def is_scanned(page: pymupdf.Page) -> bool:
    """True if the page is a photo of paper and needs OCR.

    Both must hold: (1) almost no text can be copied out, and (2) images cover
    most of the page. A blank page fails (2); a digital page with a logo fails (1).
    """
    if len(page.get_text().strip()) >= MIN_TEXT_CHARS:
        return False  # real text is there: a digital page

    page_area = abs(page.rect)
    # Only count the part of each image that is actually on the page.
    image_area = sum(abs(pymupdf.Rect(img["bbox"]) & page.rect) for img in page.get_image_info())
    return image_area / page_area >= MIN_IMAGE_COVER


def read_scanned_page(page: pymupdf.Page) -> tuple[str, float]:
    """Read a scanned page with OCR. Returns (text, confidence from 0 to 1).

    A low confidence means OCR was unsure: misread digits or names could slip
    past PII detection, so the caller should flag the page for a person.
    """
    # Turn the page into a sharp greyscale picture for Tesseract to read.
    pix = page.get_pixmap(dpi=OCR_DPI, colorspace=pymupdf.csGRAY)
    image = Image.open(io.BytesIO(pix.tobytes("png")))

    # image_to_data gives every word it read, where it is, and how sure it was (0-100).
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)

    lines: dict[tuple, list[str]] = {}
    scores: list[float] = []
    for i, word in enumerate(data["text"]):
        if not word.strip():
            continue  # Tesseract also reports empty layout boxes; skip them
        # Tesseract numbers each line by (block, paragraph, line), already in reading order.
        line_id = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(line_id, []).append(word)
        scores.append(float(data["conf"][i]))

    text = "\n".join(" ".join(words) for words in lines.values())
    confidence = sum(scores) / len(scores) / 100 if scores else 0.0
    return text, confidence


def read_metadata(pdf: pymupdf.Document, file_name: str) -> dict[str, str]:
    """Collect text that is part of the file but not printed on its pages.

    The file name, hidden fields (title, author, ...) and comments can all hold
    personal data, e.g. a title of "personnel_file_heath". Returns only fields
    with real content, so PII detection can scan them like page text.
    """
    hidden = {"file_name": file_name}

    for field in METADATA_FIELDS:
        value = (pdf.metadata.get(field) or "").strip()
        if value.lower() not in EMPTY_METADATA:
            hidden[field] = value

    # Comments / sticky notes live on top of a page, not in its text.
    comments = [
        f"page {page.number + 1}: {annot.info['content'].strip()}"
        for page in pdf
        for annot in page.annots()
        if annot.info.get("content", "").strip()
    ]
    if comments:
        hidden["comments"] = "\n".join(comments)

    return hidden


def extract_document(pdf_path: str | Path) -> dict:
    """Read every page of one PDF, choosing digital reading or OCR per page.

    Repeated lines (like the footer) are kept on purpose: the payroll register
    repeats every employee row on each monthly page, and deleting lines that
    repeat would have wiped out the whole table.
    """
    pdf_path = Path(pdf_path)
    with pymupdf.open(pdf_path) as pdf:
        if pdf.needs_pass:
            raise ValueError(f"{pdf_path.name} is password-protected; it cannot be read")

        pages = []
        for page in pdf:
            if is_scanned(page):
                text, confidence = read_scanned_page(page)
                method = "ocr"
            else:
                text = read_digital_page(page)
                method = "digital" if text else "empty"
                confidence = 1.0  # copied straight from the file, nothing guessed
            pages.append({
                "page": page.number + 1,  # PyMuPDF counts from 0, people from 1
                "text": text,
                "method": method,
                "confidence": confidence,
                "needs_review": confidence < LOW_OCR_CONFIDENCE,
            })

        return {
            "doc": pdf_path.name,
            "hidden": read_metadata(pdf, pdf_path.name),
            "pages": pages,
            "needs_review": any(p["needs_review"] for p in pages),
        }
