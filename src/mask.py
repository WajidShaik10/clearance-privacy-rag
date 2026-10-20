"""Steps 4, 8 and 13: swap real values for placeholders, and back.

- Step 4: mask a document          "Danielle Johnson" -> "PERSON_1"
- Step 8: mask a user's question   with the same placeholders (lookup only)
- Step 13: unmask an answer for HR "PERSON_1" -> "Danielle Johnson" (logged)

Like redaction, but reversible and consistent (pseudonymization): the same
person is PERSON_1 in every document, so questions across documents still work.
"""

import re
from collections.abc import Iterable

from src.detect import TITLES, Finding, find_pii, find_pii_in_document
from src.vault import Vault

# Any placeholder the vault hands out: PERSON_1, SSN_12, BANK_ACCOUNT_3, DOC_7 ...
PLACEHOLDER = re.compile(r"\b[A-Z][A-Z_]*_\d+\b")
TITLE_PREFIX = re.compile(rf"^{TITLES} ")


# ---------------------------------------------------------------- one person, one placeholder

def full_names_in(findings: Iterable[Finding], known_names: Iterable[str]) -> set[str]:
    """Every full name (two or more words) we know of for this document."""
    names = {" ".join(n.split()) for n in known_names}
    names |= {" ".join(f.value.split()) for f in findings
              if f.type == "PERSON" and len(f.value.split()) >= 2 and not TITLE_PREFIX.match(f.value)}
    return names


def canonical_name(value: str, full_names: set[str]) -> str:
    """Link "Rebecca" and "Mx. Heath" to "Rebecca Heath" when exactly one full name fits.

    If two people share a first name, we cannot tell which one is meant, so the
    short form keeps a placeholder of its own: less helpful, but never wrong.
    """
    value = " ".join(value.split())
    if value in full_names:
        return value
    if TITLE_PREFIX.match(value):
        last = TITLE_PREFIX.sub("", value).casefold()
        matches = [n for n in full_names if n.split()[-1].casefold() == last]
    elif len(value.split()) == 1:
        matches = [n for n in full_names if n.split()[0].casefold() == value.casefold()]
    else:
        matches = []
    return matches[0] if len(matches) == 1 else value


def placeholder_for(finding: Finding, vault: Vault, full_names: set[str], create: bool = True) -> str:
    value = canonical_name(finding.value, full_names) if finding.type == "PERSON" else finding.value
    if create:
        return vault.get_placeholder(value, finding.type)
    # Questions: only look up. A value the documents never mentioned gets a generic
    # stand-in, so it is still never sent on, but nothing new is stored.
    return vault.find_placeholder(value, finding.type) or f"[UNKNOWN_{finding.type}]"


def replace_findings(text: str, findings: list[Finding], placeholders: list[str]) -> str:
    # Work from the end of the text backwards, so earlier positions stay correct.
    for f, placeholder in sorted(zip(findings, placeholders), key=lambda pair: pair[0].start, reverse=True):
        text = text[:f.start] + placeholder + text[f.end:]
    return text


# ---------------------------------------------------------------- step 4: documents

def mask_document(extracted: dict, vault: Vault, known_names: Iterable[str] = ()) -> dict:
    """Mask everything extract_document() returned. The result holds no real values.

    The file name becomes DOC_n (it often contains a name: w2_2025_johnson.pdf).
    Hidden fields such as the PDF title are dropped: Q&A does not need them, and
    data we do not keep cannot leak. Comments are kept, masked like page text.
    """
    known_names = list(known_names)
    page_findings = find_pii_in_document([p["text"] for p in extracted["pages"]], known_names)
    full_names = full_names_in((f for page in page_findings for f in page), known_names)

    pages = []
    for page, findings in zip(extracted["pages"], page_findings):
        placeholders = [placeholder_for(f, vault, full_names) for f in findings]
        pages.append({**page, "text": replace_findings(page["text"], findings, placeholders)})

    comments = extracted["hidden"].get("comments")
    if comments:
        findings = find_pii(comments, full_names)
        comments = replace_findings(comments, findings, [placeholder_for(f, vault, full_names) for f in findings])

    return {
        "doc_id": vault.get_placeholder(extracted["doc"], "DOC"),
        "pages": pages,
        "comments": comments,
        "needs_review": extracted["needs_review"],
    }


# ---------------------------------------------------------------- step 8: questions

def mask_question(question: str, vault: Vault, known_names: Iterable[str] = ()) -> str:
    """Mask a user's question with the documents' placeholders, storing nothing new.

    "What is Rebecca's salary?" -> "What is PERSON_5's salary?"
    """
    known_names = list(known_names)
    findings = find_pii(question, known_names)
    full_names = full_names_in(findings, known_names)
    placeholders = [placeholder_for(f, vault, full_names, create=False) for f in findings]
    return replace_findings(question, findings, placeholders)


# ---------------------------------------------------------------- step 13: answers for HR

def unmask(text: str, vault: Vault, user: str, role: str, purpose: str = "") -> str:
    """Swap placeholders back to real values. Only HR may; the vault logs each one.

    Citations (DOC_3) turn back into file names too, so HR can open the original.
    A placeholder the vault does not know (one the AI made up) is left as it is;
    the output guard deals with those.
    """
    real = {}
    for placeholder in dict.fromkeys(PLACEHOLDER.findall(text)):  # each placeholder once
        if vault.placeholder_exists(placeholder):
            real[placeholder] = vault.reveal(placeholder, user, role, purpose)
    return PLACEHOLDER.sub(lambda m: real.get(m.group(), m.group()), text)
