"""Steps 3 and 11: find private info (SSN, ITIN, EIN, names, addresses, phones,
emails, birth dates, bank details, employee IDs, money amounts).

The same detector scans documents at ingestion (step 3) and every AI answer
before it reaches the user (step 11), so the safety check is never weaker
than ingestion. It only FINDS private data; mask.py hides it.

Three layers, because no single method catches everything:
  1. Patterns: fixed formats (SSN, phone, email...) plus checks such as the
     bank routing checksum, and context words ("routing", "date of birth").
  2. Known names: employee names from HR's roster, plus the forms people use
     in writing ("Rebecca", "Mx. Heath") once the full name is on the page.
  3. AI (spaCy): spots other people's names (contractors, emergency contacts).
"""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import lru_cache

import spacy


@dataclass(frozen=True)
class Finding:
    type: str  # "SSN", "PERSON", ...
    value: str  # the exact text found
    start: int  # position in the text
    end: int
    source: str  # which layer found it: "pattern", "roster", "variant" or "ai"


# ---------------------------------------------------------------- checks on numbers

def valid_ssn(digits: str) -> bool:
    # The SSA never issues area 000, 666 or 900-999, group 00 or serial 0000.
    area, group, serial = digits[:3], digits[3:5], digits[5:]
    return area not in ("000", "666") and area[0] != "9" and group != "00" and serial != "0000"


def valid_itin(digits: str) -> bool:
    # ITINs start with 9 and use only these middle-digit ranges.
    group = int(digits[3:5])
    return digits[0] == "9" and (50 <= group <= 65 or 70 <= group <= 88 or 90 <= group <= 92 or 94 <= group <= 99)


def valid_routing(digits: str) -> bool:
    # US bank routing numbers end in a checksum digit: weights 3, 7, 1 repeated.
    return digits != "000000000" and sum(int(d) * w for d, w in zip(digits, (3, 7, 1) * 3)) % 10 == 0


# ---------------------------------------------------------------- layer 1: patterns

STREET_SUFFIXES = (
    # USPS standard street suffixes, plus the common short forms.
    "Alley Avenue Branch Bridge Brook Brooks Burg Burgs Bypass Camp Canyon Cape Causeway Center Centers "
    "Circle Circles Cliff Cliffs Club Common Corner Corners Course Court Courts Cove Coves Creek Crescent "
    "Crest Crossing Crossroad Curve Dale Dam Divide Drive Drives Estate Estates Expressway Extension "
    "Extensions Fall Falls Ferry Field Fields Flat Flats Ford Fords Forest Forge Forges Fork Forks Fort "
    "Freeway Garden Gardens Gateway Glen Glens Green Greens Grove Groves Harbor Harbors Haven Heights "
    "Highway Hill Hills Hollow Inlet Island Islands Isle Junction Junctions Key Keys Knoll Knolls Lake "
    "Lakes Land Landing Lane Light Lights Loaf Lock Locks Lodge Loop Mall Manor Manors Meadow Meadows "
    "Mews Mill Mills Mission Motorway Mount Mountain Mountains Neck Orchard Oval Overpass Park Parks "
    "Parkway Parkways Pass Passage Path Pike Pine Pines Place Plain Plains Plaza Point Points Port Ports "
    "Prairie Radial Ramp Ranch Rapid Rapids Rest Ridge Ridges River Road Roads Route Row Rue Run Shoal "
    "Shoals Shore Shores Skyway Spring Springs Spur Spurs Square Squares Station Stravenue Stream Street "
    "Streets Summit Terrace Throughway Trace Track Trafficway Trail Tunnel Turnpike Underpass Union Unions "
    "Valley Valleys Via Viaduct View Views Village Villages Ville Vista Walk Walks Wall Way Ways Well Wells "
    "St Ave Rd Dr Blvd Boulevard Ln Ct Pl Hwy Pkwy Ter Cir Trl Sq"
).split()


@dataclass(frozen=True)
class Pattern:
    type: str
    regex: re.Pattern
    check: Callable[[str], bool] | None = None  # extra test on the match's digits
    context: re.Pattern | None = None  # a word that must appear before the match...
    window: int | None = None  # ...within this many characters (None = anywhere earlier on the page)


def _rx(pattern: str, flags: int = 0) -> re.Pattern:
    return re.compile(pattern, flags)


PATTERNS = [
    Pattern("EMAIL", _rx(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    Pattern("SSN", _rx(r"\b\d{3}-\d{2}-\d{4}\b"), check=valid_ssn),
    Pattern("ITIN", _rx(r"\b9\d{2}-\d{2}-\d{4}\b"), check=valid_itin),
    # Tax forms print one digit per box, so an SSN/ITIN can come out as "9 7 5 9 2 9 2 4 6".
    Pattern("TAX_ID", _rx(r"(?<!\d)(?<!\d )\d(?: \d){8}(?! ?\d)"), check=lambda d: valid_ssn(d) or valid_itin(d)),
    Pattern("EIN", _rx(r"\b\d{2}-\d{7}\b")),
    Pattern("PHONE", _rx(r"\(\d{3}\) ?\d{3}-\d{4}|\b\d{3}[-.]\d{3}[-.]\d{4}\b")),
    Pattern("EMPLOYEE_ID", _rx(r"\bEMP-\d{3,6}\b")),
    # Dates are only private when they are a birth date.
    Pattern("DOB", _rx(r"\b\d{1,2}/\d{1,2}/\d{4}\b"),
            context=_rx(r"birth|\bDOB\b|\bborn\b", re.I), window=40),
    Pattern("BANK_ROUTING", _rx(r"\b\d{9}\b"), check=valid_routing,
            context=_rx(r"routing|\bABA\b", re.I)),
    Pattern("BANK_ACCOUNT", _rx(r"\b\d{8,17}\b"), context=_rx(r"account", re.I)),
    Pattern("ADDRESS", _rx(
        r"\b\d{1,6}(?: (?:N|S|E|W|NE|NW|SE|SW)\.?)?(?: [A-Z][A-Za-z'.-]*){1,4}? "
        r"(?:" + "|".join(STREET_SUFFIXES) + r")\b\.?"
        r"(?:,? (?:Apt\.?|Suite|Unit|#) ?[\w-]+)?")),
    Pattern("ADDRESS", _rx(r"\b[A-Z][a-z]+(?: [A-Z][a-z]+)*, [A-Z]{2} \d{5}(?:-\d{4})?\b")),  # city, ST zip
    # Any money amount: "$4,958.33", "-$694.17", and form boxes like "59500.00".
    Pattern("MONEY", _rx(r"-?\$ ?\d{1,3}(?:,\d{3})*(?:\.\d{2})?\b|\b\d{1,3}(?:,\d{3})+\.\d{2}\b|\b\d{3,}\.\d{2}\b")),
]

# The company's own public details are not personal data.
ORGANIZATION_ALLOW_LIST = {
    "Brightline Logistics LLC",
    "200 W Lakeview Ave, Suite 900",
    "Chicago, IL 60606",
}


def digits_of(text: str) -> str:
    return re.sub(r"\D", "", text)


def find_patterns(text: str) -> list[Finding]:
    found = []
    for p in PATTERNS:
        for m in p.regex.finditer(text):
            if p.check and not p.check(digits_of(m.group())):
                continue
            if p.context:
                before = text[max(0, m.start() - p.window):m.start()] if p.window else text[:m.start()]
                if not p.context.search(before):
                    continue
            pii_type = p.type
            if pii_type == "TAX_ID":  # decide which ID the boxed digits are
                pii_type = "ITIN" if valid_itin(digits_of(m.group())) else "SSN"
            found.append(Finding(pii_type, m.group(), m.start(), m.end(), "pattern"))
    return found


# ---------------------------------------------------------------- layers 2 and 3: names

TITLES = r"(?:Mr|Mrs|Ms|Mx|Dr)\.?"
NAME_WORD = re.compile(r"^[A-Z][a-zA-Z'’-]+$")


def _name_regex(name: str) -> re.Pattern:
    # Words of a name may be split by any whitespace, e.g. a line break in a table cell.
    return re.compile(r"\b" + r"\s+".join(re.escape(part) for part in name.split()) + r"\b")


def find_known_names(text: str, known_names: Iterable[str]) -> list[Finding]:
    return [Finding("PERSON", m.group(), m.start(), m.end(), "roster")
            for name in known_names for m in _name_regex(name).finditer(text)]


@lru_cache(maxsize=1)
def _nlp():
    # Loaded once, on first use (it takes a second or two). We only need its name finder.
    return spacy.load("en_core_web_lg", exclude=["parser", "lemmatizer"])


def find_ai_names(text: str) -> list[Finding]:
    found = []
    for ent in _nlp()(text).ents:
        # spaCy sometimes includes a trailing line break ("Samantha Hooper\n"): trim it.
        value = ent.text.strip()
        start = ent.start_char + ent.text.index(value)
        words = value.split()
        # Keep "First Last"-shaped answers only: 2-4 capitalised words, no digits or line breaks.
        if ent.label_ == "PERSON" and 2 <= len(words) <= 4 and "\n" not in value \
                and all(NAME_WORD.match(w) for w in words):
            found.append(Finding("PERSON", value, start, start + len(value), "ai"))
    return found


def find_name_variants(text: str, full_names: Iterable[str], first_names: bool) -> list[Finding]:
    """For each full name, also catch "Mx. Heath" and, if first_names, "Rebecca".

    A last name on its own ("Day", "Rush") is never matched: too many are
    ordinary words. A first name on its own is only matched for names we are
    sure of (HR's roster): when the AI wrongly called "Complete Steps" a person,
    matching "Complete" alone hid that word all over the W-4.
    """
    found = []
    for name in set(full_names):
        parts = name.split()
        first, last = parts[0], parts[-1]
        regexes = [re.compile(rf"\b{TITLES} {re.escape(last)}\b")]
        if first_names and len(first) >= 3:
            regexes.append(re.compile(rf"\b{re.escape(first)}\b"))
        for rx in regexes:
            found += [Finding("PERSON", m.group(), m.start(), m.end(), "variant") for m in rx.finditer(text)]
    return found


# ---------------------------------------------------------------- putting it together

# When two findings overlap, the more specific one wins (lower number first).
PRIORITY = {"EMAIL": 0, "SSN": 1, "ITIN": 1, "EIN": 2, "PHONE": 3, "EMPLOYEE_ID": 3, "DOB": 4,
            "BANK_ROUTING": 5, "BANK_ACCOUNT": 6, "PERSON": 7, "ADDRESS": 8, "MONEY": 9}


def _rank(f: Finding) -> tuple:
    # AI guesses and name variants lose to patterns and the roster, which are surer.
    penalty = 10 if f.source in ("ai", "variant") else 0
    return (PRIORITY[f.type] + penalty, -(f.end - f.start), f.start)


def merge_addresses(findings: list[Finding], text: str) -> list[Finding]:
    """Join address pieces that touch or overlap into one finding.

    The street and the "city, ST zip" patterns can overlap ("819 Johnson Course"
    and "Johnson Course East William, IL 60608"); keeping only one would leave
    part of the address ("819") exposed.
    """
    addresses = sorted((f for f in findings if f.type == "ADDRESS"), key=lambda f: f.start)
    merged: list[Finding] = []
    for f in addresses:
        if merged and f.start <= merged[-1].end + 2 and not text[merged[-1].end:f.start].strip(" ,"):
            start, end = merged[-1].start, max(merged[-1].end, f.end)
            merged[-1] = Finding("ADDRESS", text[start:end], start, end, "pattern")
        else:
            merged.append(f)
    return [f for f in findings if f.type != "ADDRESS"] + merged


def resolve_overlaps(findings: list[Finding]) -> list[Finding]:
    kept: list[Finding] = []
    for f in sorted(findings, key=_rank):
        if all(f.end <= k.start or f.start >= k.end for k in kept):
            kept.append(f)
    return sorted(kept, key=lambda f: f.start)


def find_pii(text: str, known_names: Iterable[str] = (), other_names: Iterable[str] = ()) -> list[Finding]:
    """Return every private value in the text, in order, without overlaps.

    known_names: full names we are sure of, e.g. HR's employee roster.
    other_names: names found elsewhere in the same document by the AI.
    """
    known_names, other_names = set(known_names), set(other_names)
    findings = (find_patterns(text) + find_known_names(text, known_names | other_names)
                + find_ai_names(text))
    findings = [f for f in findings if " ".join(f.value.split()) not in ORGANIZATION_ALLOW_LIST]
    # Settle overlaps first, so an AI "name" that is really part of an address
    # ("Kristen Valley") is dropped before we look for variants of it.
    findings = resolve_overlaps(merge_addresses(findings, text))
    ai_names = other_names | {" ".join(f.value.split()) for f in findings if f.source == "ai"}
    variants = (find_name_variants(text, known_names, first_names=True)
                + find_name_variants(text, ai_names - known_names, first_names=False))
    return resolve_overlaps(findings + variants)


def find_pii_in_document(page_texts: list[str], known_names: Iterable[str] = ()) -> list[list[Finding]]:
    """Find PII on every page of one document, sharing names across its pages.

    A personnel file names "Rebecca Heath" on page 1 and only "Rebecca" or
    "Mx. Heath" later, so names found on any page are looked for on all of them.
    """
    known_names = set(known_names)
    first_pass = [find_pii(text, known_names) for text in page_texts]
    ai_names = {" ".join(f.value.split()) for page in first_pass for f in page if f.source == "ai"}
    if not ai_names:
        return first_pass  # nothing new to look for
    return [find_pii(text, known_names, ai_names) for text in page_texts]


def contains_pii(text: str, known_names: Iterable[str] = ()) -> bool:
    """Step 11 guard: True if any private value is found in the text."""
    return bool(find_pii(text, known_names))
