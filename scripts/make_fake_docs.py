"""Milestone 1: generate fake HR, payroll and tax PDFs plus an answer key.

Every person, number and company here is invented (Faker, fixed seed), so the
documents are safe to test with. The answer key lists every private value and
the page(s) it appears on, so later milestones can measure what they catch.

    python scripts/make_fake_docs.py

Outputs:
    data/fake_docs/*.pdf
    data/answer_key.json
    data/hr_roster.json   (employee names only, standing in for an HR system export)
"""

import io
import json
import random
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pymupdf
from faker import Faker
from PIL import Image, ImageFilter
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "data" / "templates" / "irs"
OUT = ROOT / "data" / "fake_docs"
KEY = ROOT / "data" / "answer_key.json"
ROSTER = ROOT / "data" / "hr_roster.json"

SEED = 42
fake = Faker("en_US")
Faker.seed(SEED)
rng = random.Random(SEED)

COMPANY = {
    "name": "Brightline Logistics LLC",
    "address": "200 W Lakeview Ave, Suite 900",
    "city": "Chicago, IL 60606",
    "ein": "36-4817205",
    "state_id": "IL 4471-0938",
    "bank": "First Lakeshore Bank",
}

NUMERIC_TYPES = {"SSN", "ITIN", "EIN", "PHONE", "BANK_ROUTING", "BANK_ACCOUNT", "SALARY"}


# ---------------------------------------------------------------- people

@dataclass
class Person:
    emp_id: str
    first: str
    last: str
    ssn: str
    dob: str
    street: str
    city_line: str
    phone: str
    email: str
    routing: str
    account: str
    salary: int
    department: str
    title: str
    hire_date: str
    emergency_name: str
    emergency_phone: str

    @property
    def name(self) -> str:
        return f"{self.first} {self.last}"


def fictional_phone() -> str:
    # 555-01xx numbers are reserved for fiction, so no real person is ever dialled
    return fake.numerify("(312) 555-01##")


def money(x: float) -> str:
    return f"${x:,.2f}"


DEPARTMENTS = [
    ("Operations", "Logistics Coordinator", 58000, 72000),
    ("Operations", "Warehouse Supervisor", 61000, 76000),
    ("Finance", "Payroll Specialist", 64000, 78000),
    ("Finance", "Senior Accountant", 82000, 98000),
    ("Engineering", "Software Engineer", 105000, 138000),
    ("Engineering", "Data Analyst", 78000, 96000),
    ("Human Resources", "HR Generalist", 60000, 74000),
    ("Sales", "Account Executive", 70000, 92000),
]


def make_people(n: int = 12) -> list[Person]:
    people = []
    for i in range(n):
        dept, title, lo, hi = DEPARTMENTS[i % len(DEPARTMENTS)]
        first, last = fake.unique.first_name(), fake.unique.last_name()
        people.append(Person(
            emp_id=f"EMP-{1040 + i}",
            first=first,
            last=last,
            ssn=fake.ssn(),
            dob=fake.date_of_birth(minimum_age=23, maximum_age=62).strftime("%m/%d/%Y"),
            street=fake.street_address(),
            city_line=f"{fake.city()}, IL {fake.numerify('606##')}",
            phone=fictional_phone(),
            email=f"{first.lower()}.{last.lower()}@example.com",
            routing=fake.aba(),
            account=fake.numerify("############")[: rng.choice([10, 11, 12])],
            salary=rng.randrange(lo, hi, 500),
            department=dept,
            title=title,
            hire_date=fake.date_between(start_date="-9y", end_date="-1y").strftime("%m/%d/%Y"),
            emergency_name=fake.name(),
            emergency_phone=fictional_phone(),
        ))
    return people


def make_contractors() -> list[dict]:
    a_first, a_last = fake.unique.first_name(), fake.unique.last_name()
    b_first, b_last = fake.unique.first_name(), fake.unique.last_name()
    return [
        {"name": f"{a_first} {a_last}", "business": "", "itin": fake.itin(), "ein": None,
         "street": fake.street_address(), "city_line": f"{fake.city()}, IL {fake.numerify('606##')}"},
        {"name": f"{b_first} {b_last}", "business": f"{b_last} Freight Consulting LLC", "itin": None,
         "ein": fake.ein(), "street": fake.street_address(),
         "city_line": f"{fake.city()}, IN {fake.numerify('463##')}"},
    ]


# ---------------------------------------------------------------- answer key

@dataclass
class Doc:
    file: str
    kind: str
    scanned: bool = False
    pages: int = 0
    pii: list[dict] = field(default_factory=list)


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def locate(pdf: Path, items: list[tuple[str, str]]) -> tuple[list[dict], list[str]]:
    """Find the page(s) each private value appears on. Returns (pii entries, misses)."""
    with pymupdf.open(pdf) as d:
        texts = [norm(p.get_text()) for p in d]
    found, misses = [], []
    for pii_type, value in dict.fromkeys(items):  # de-duplicate, keep order
        pages = [i + 1 for i, t in enumerate(texts)
                 if norm(value) in t or (pii_type in NUMERIC_TYPES and digits(value) and digits(value) in digits(t))]
        if not pages:
            misses.append(f"{pdf.name}: {pii_type} {value!r}")
        found += [{"page": p, "type": pii_type, "value": value} for p in pages]
    return found, misses


def person_items(p: Person, *, salary_text: str | None = None) -> list[tuple[str, str]]:
    items = [("PERSON", p.name), ("SSN", p.ssn), ("ADDRESS", p.street)]
    if salary_text:
        items.append(("SALARY", salary_text))
    return items


# ---------------------------------------------------------------- IRS forms

def fill_form(template: str, page_index: int, values: dict[str, str], out: Path) -> None:
    """Fill fields on one page of an IRS PDF, flatten it, and save just that page."""
    src = pymupdf.open(TEMPLATES / template)
    src.select([page_index])
    page = src[0]
    for w in page.widgets():
        key = w.field_name.split(".")[-1].removesuffix("[0]")
        if key in values:
            w.field_value = values[key]
            w.update()
    src.bake()  # turn form fields into ordinary page text, like a printed form
    src.save(out, garbage=4, deflate=True)
    src.close()


def make_w2(p: Person) -> tuple[Path, list[tuple[str, str]]]:
    wages = float(p.salary)
    fed = round(wages * rng.uniform(0.11, 0.17), 2)
    ss_wages = min(wages, 176_100)
    vals = {
        "a": p.ssn, "b": COMPANY["ein"],
        "c": f"{COMPANY['name']}\n{COMPANY['address']}\n{COMPANY['city']}",
        "d": f"{rng.randint(100000, 999999)}",
        "e_first": p.first, "e_last": p.last, "f": f"{p.street}\n{p.city_line}",
        "1": f"{wages:.2f}", "2": f"{fed:.2f}", "3": f"{ss_wages:.2f}", "4": f"{ss_wages * 0.062:.2f}",
        "5": f"{wages:.2f}", "6": f"{wages * 0.0145:.2f}",
        "15": "IL", "15id": COMPANY["state_id"], "16": f"{wages:.2f}", "17": f"{wages * 0.0495:.2f}",
    }
    # W-2 Copy B prints two identical copies per page: fields f2_01-f2_44 (top) and f2_45-f2_88 (bottom)
    layout = {"a": 1, "b": 2, "c": 3, "d": 4, "e_first": 5, "e_last": 6, "f": 8, "1": 9, "2": 10, "3": 11,
              "4": 12, "5": 13, "6": 14, "15": 31, "15id": 32, "16": 35, "17": 37}
    fields = {}
    for k, n in layout.items():
        fields[f"f2_{n:02d}"] = vals[k]
        fields[f"f2_{n + 44:02d}"] = vals[k]
    out = OUT / f"w2_2025_{p.last.lower()}.pdf"
    fill_form("fw2.pdf", 3, fields, out)
    items = person_items(p, salary_text=f"{wages:.2f}") + [("EIN", COMPANY["ein"])]
    return out, items


def make_w4(p: Person) -> tuple[Path, list[tuple[str, str]]]:
    fields = {
        "f1_01": p.first, "f1_02": p.last, "f1_03": p.street, "f1_04": p.city_line, "f1_05": p.ssn,
        "f1_13": f"{COMPANY['name']}, {COMPANY['address']}, {COMPANY['city']}    {p.hire_date}",
        "f1_14": COMPANY["ein"],
    }
    out = OUT / f"w4_{p.last.lower()}.pdf"
    fill_form("fw4.pdf", 0, fields, out)
    return out, person_items(p) + [("EIN", COMPANY["ein"])]


def make_w9(c: dict) -> tuple[Path, list[tuple[str, str]]]:
    fields = {"f1_01": c["name"], "f1_02": c["business"], "f1_07": c["street"], "f1_08": c["city_line"],
              "f1_09": f"{COMPANY['name']}\n{COMPANY['address']}, {COMPANY['city']}"}
    items = [("PERSON", c["name"]), ("ADDRESS", c["street"])]
    if c["itin"]:
        a, b, d = c["itin"].split("-")
        fields |= {"f1_11": a, "f1_12": b, "f1_13": d}  # ITIN goes in the SSN boxes, split 3-2-4
        items.append(("ITIN", c["itin"]))
    else:
        a, b = c["ein"].split("-")
        fields |= {"f1_14": a, "f1_15": b}
        items.append(("EIN", c["ein"]))
    out = OUT / f"w9_{c['name'].split()[-1].lower()}.pdf"
    fill_form("fw9.pdf", 0, fields, out)
    return out, items


# ---------------------------------------------------------------- ReportLab documents

styles = getSampleStyleSheet()
H1, H2, BODY, SMALL = styles["Title"], styles["Heading2"], styles["BodyText"], styles["Italic"]
GRID = TableStyle([
    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8ecf2")),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
])


def header() -> list:
    return [Paragraph(COMPANY["name"], H2),
            Paragraph(f"{COMPANY['address']}, {COMPANY['city']}", SMALL), Spacer(1, 10)]


def build(out: Path, story: list, pagesize=letter) -> None:
    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.drawString(0.75 * inch, 0.5 * inch, f"{COMPANY['name']}  |  Confidential")
        canvas.drawRightString(pagesize[0] - 0.75 * inch, 0.5 * inch, f"Page {doc.page}")

    SimpleDocTemplate(str(out), pagesize=pagesize, topMargin=0.7 * inch, bottomMargin=0.8 * inch,
                      title=out.stem).build(story, onFirstPage=footer, onLaterPages=footer)


def taxes(gross: float) -> dict[str, float]:
    return {"Federal income tax": gross * 0.14, "Social Security": gross * 0.062,
            "Medicare": gross * 0.0145, "Illinois state tax": gross * 0.0495}


def make_payslip(p: Person, period: str, pay_date: str, show_full_account: bool) -> tuple[Path, list[tuple[str, str]]]:
    gross = p.salary / 12
    ded = taxes(gross) | {"401(k) 5%": gross * 0.05, "Health insurance": 210.00}
    net = gross - sum(ded.values())
    account = p.account if show_full_account else f"****{p.account[-4:]}"
    story = header() + [
        Paragraph(f"Earnings Statement: {period}", H1),
        Table([["Employee", p.name, "Employee ID", p.emp_id],
               ["SSN", p.ssn, "Department", p.department],
               ["Address", f"{p.street}, {p.city_line}", "Pay date", pay_date]],
              colWidths=[1 * inch, 2.6 * inch, 1.1 * inch, 1.8 * inch], style=GRID),
        Spacer(1, 12),
        Table([["Earnings", "Amount"], ["Regular salary", money(gross)]]
              + [[k, f"-{money(v)}"] for k, v in ded.items()]
              + [["Net pay", money(net)]], colWidths=[3 * inch, 1.6 * inch], style=GRID),
        Spacer(1, 12),
        Paragraph("Direct deposit", H2),
        Table([["Bank", "Routing number", "Account number", "Amount"],
               [COMPANY["bank"], p.routing, account, money(net)]], style=GRID),
        Spacer(1, 8),
        Paragraph(f"Annual base salary: {money(p.salary)}", BODY),
    ]
    out = OUT / f"payslip_{period.lower().replace(' ', '_')}_{p.last.lower()}.pdf"
    build(out, story)
    items = person_items(p, salary_text=money(p.salary)) + [
        ("EMPLOYEE_ID", p.emp_id), ("BANK_ROUTING", p.routing), ("SALARY", money(gross)), ("SALARY", money(net))]
    if show_full_account:
        items.append(("BANK_ACCOUNT", p.account))
    return out, items


def make_directory(people: list[Person]) -> tuple[Path, list[tuple[str, str]]]:
    rows = [["Name", "Department", "Title", "Phone", "Email", "Home address"]]
    rows += [[p.name, p.department, p.title, p.phone, p.email, Paragraph(f"{p.street}<br/>{p.city_line}", BODY)]
             for p in people]
    story = header() + [
        Paragraph("Employee Directory", H1),
        Paragraph("For internal use only. Home addresses and personal phone numbers are restricted "
                  "to HR and direct managers.", BODY), Spacer(1, 10),
        Table(rows, repeatRows=1, colWidths=[1.3 * inch, 1.1 * inch, 1.4 * inch, 1.1 * inch, 2.1 * inch, 2.4 * inch],
              style=GRID),
    ]
    out = OUT / "employee_directory.pdf"
    build(out, story, landscape(letter))
    items = []
    for p in people:
        items += [("PERSON", p.name), ("PHONE", p.phone), ("EMAIL", p.email), ("ADDRESS", p.street)]
    return out, items


def make_payroll_register(people: list[Person]) -> tuple[Path, list[tuple[str, str]]]:
    story, items = header() + [Paragraph("Payroll Register: Q3 2025", H1)], []
    for month in ["July 2025", "August 2025", "September 2025"]:
        rows = [["Emp ID", "Name", "SSN", "Gross", "Fed tax", "FICA", "IL tax", "Net", "Bank account"]]
        for p in people:
            g = p.salary / 12
            t = taxes(g)
            net = g - sum(t.values())
            rows.append([p.emp_id, p.name, p.ssn, money(g), money(t["Federal income tax"]),
                         money(t["Social Security"] + t["Medicare"]), money(t["Illinois state tax"]), money(net),
                         p.account])
            items += [("EMPLOYEE_ID", p.emp_id), ("PERSON", p.name), ("SSN", p.ssn), ("SALARY", money(g)),
                      ("BANK_ACCOUNT", p.account)]
        story += [Paragraph(month, H2), Table(rows, repeatRows=1, style=GRID), PageBreak()]
    out = OUT / "payroll_register_q3_2025.pdf"
    build(out, story[:-1], landscape(letter))
    return out, items


def make_personnel_file(p: Person, people: list[Person]) -> tuple[Path, list[tuple[str, str]]]:
    manager = next(m for m in people if m.department == p.department and m is not p) if any(
        m.department == p.department and m is not p for m in people) else people[0]
    raise1, raise2 = round(p.salary * 0.91, -2), round(p.salary * 0.96, -2)
    story = header() + [
        Paragraph(f"Personnel File: {p.name}", H1),
        Paragraph("Section 1: Personal information", H2),
        Table([["Full name", p.name], ["Employee ID", p.emp_id], ["Date of birth", p.dob],
               ["Social Security number", p.ssn], ["Home address", f"{p.street}, {p.city_line}"],
               ["Personal phone", p.phone], ["Personal email", p.email],
               ["Emergency contact", f"{p.emergency_name}, {p.emergency_phone}"],
               ["Direct deposit", f"{COMPANY['bank']}, routing {p.routing}, account {p.account}"]],
              colWidths=[1.8 * inch, 4.6 * inch], style=GRID),
        PageBreak(),
        Paragraph("Section 2: Compensation history", H2),
        Table([["Effective date", "Title", "Annual salary", "Reason"],
               [p.hire_date, p.title, money(raise1), "Hire"],
               ["03/01/2024", p.title, money(raise2), "Annual merit increase"],
               ["03/01/2025", p.title, money(p.salary), "Annual merit increase"]], style=GRID),
        Spacer(1, 10),
        Paragraph(f"{p.first}'s current base salary of {money(p.salary)} was approved by "
                  f"{manager.name} on 02/14/2025.", BODY),
        PageBreak(),
        Paragraph("Section 3: Performance review 2025", H2),
        Paragraph(f"Reviewer: {manager.name}. {p.first} consistently met deadlines this year and took "
                  f"ownership of the quarterly close. Mx. {p.last} mentored two new hires and is "
                  f"recommended for promotion in the next cycle.", BODY),
        Spacer(1, 8),
        Paragraph(f"Note from HR: {p.first} requested a schedule change for medical appointments; "
                  f"approved. Contact on file: {p.phone}.", BODY),
    ]
    out = OUT / f"personnel_file_{p.last.lower()}.pdf"
    build(out, story)
    items = person_items(p, salary_text=money(p.salary)) + [
        ("EMPLOYEE_ID", p.emp_id), ("DOB", p.dob), ("PHONE", p.phone), ("EMAIL", p.email),
        ("PERSON", p.emergency_name), ("PHONE", p.emergency_phone), ("BANK_ROUTING", p.routing),
        ("BANK_ACCOUNT", p.account), ("SALARY", money(raise1)), ("SALARY", money(raise2)),
        ("PERSON", manager.name), ("PERSON", f"Mx. {p.last}"), ("PERSON", p.first)]
    return out, items


def make_leave_policy() -> tuple[Path, list[tuple[str, str]]]:
    """No personal data at all: tests answering general questions and avoiding false alarms."""
    paras = [
        ("1. Paid time off", "Full-time employees accrue 1.5 days of paid time off (PTO) per month, up to "
         "18 days per year. Unused PTO up to 5 days carries over to the next calendar year."),
        ("2. Sick leave", "Employees receive 8 days of paid sick leave per year. A doctor's note is required "
         "for absences longer than 3 consecutive working days."),
        ("3. Parental leave", "Employees with at least 12 months of service receive 12 weeks of paid parental "
         "leave at 100% of base pay, to be taken within 12 months of a birth or adoption."),
        ("4. Bereavement leave", "Up to 5 paid days for an immediate family member, and 2 days for extended family."),
        ("5. Requesting leave", "Submit requests in the HR portal at least 2 weeks in advance where possible. "
         "Your manager approves PTO; HR approves parental and medical leave."),
        ("6. Protecting your information", "HR will never ask for your Social Security number, bank account "
         "number or password by email. Report suspicious requests to the security team."),
        ("7. Public holidays", "The company observes 10 paid public holidays each year, published every December."),
    ]
    story = header() + [Paragraph("Employee Handbook: Leave Policy (2025)", H1)]
    for i, (title, text) in enumerate(paras):
        story += [Paragraph(title, H2), Paragraph(text, BODY)]
        if i == 3:
            story.append(PageBreak())
    out = OUT / "leave_policy_2025.pdf"
    build(out, story)
    return out, []


# ---------------------------------------------------------------- scanned copies

def make_scanned(src: Path) -> Path:
    """Re-create a PDF as page images, slightly tilted and noisy, like a paper scan."""
    out = OUT / f"scan_{src.name}"
    with pymupdf.open(src) as d, pymupdf.open() as scan:
        for page in d:
            pix = page.get_pixmap(dpi=150, colorspace=pymupdf.csGRAY)
            img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
            img = img.rotate(rng.uniform(-0.8, 0.8), expand=False, fillcolor=255, resample=Image.BICUBIC)
            img = img.filter(ImageFilter.GaussianBlur(0.4))
            noise = Image.effect_noise(img.size, 12).convert("L")
            img = Image.blend(img, noise, 0.06)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=70)
            p = scan.new_page(width=page.rect.width, height=page.rect.height)
            p.insert_image(p.rect, stream=buf.getvalue())
        scan.save(out, garbage=4, deflate=True)
    return out


# ---------------------------------------------------------------- main

def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.pdf"):
        old.unlink()

    people = make_people()
    contractors = make_contractors()
    jobs = []
    jobs += [("W-2", make_w2(p)) for p in people[:5]]
    jobs += [("W-4", make_w4(p)) for p in people[5:8]]
    jobs += [("W-9", make_w9(c)) for c in contractors]
    jobs += [("Payslip", make_payslip(p, "September 2025", "09/30/2025", show_full_account=i % 2 == 0))
             for i, p in enumerate(people[:5])]
    jobs.append(("Employee directory", make_directory(people)))
    jobs.append(("Payroll register", make_payroll_register(people)))
    jobs += [("Personnel file", make_personnel_file(p, people)) for p in (people[0], people[4])]
    jobs.append(("Leave policy", make_leave_policy()))

    docs, misses = [], []
    for kind, (path, items) in jobs:
        pii, miss = locate(path, items)
        misses += miss
        with pymupdf.open(path) as d:
            docs.append(Doc(path.name, kind, pages=d.page_count, pii=pii))

    # scanned copies: same answer key as their source, but the text is only in the image
    for src_name in ("w4_" + people[5].last.lower() + ".pdf", "personnel_file_" + people[4].last.lower() + ".pdf"):
        src = next(d for d in docs if d.file == src_name)
        scan = make_scanned(OUT / src.file)
        docs.append(Doc(scan.name, src.kind, scanned=True, pages=src.pages, pii=[dict(x) for x in src.pii]))

    KEY.write_text(json.dumps({
        "note": "All data is fake (Faker seed 42). Values are listed per page as they appear in the PDF.",
        "company": COMPANY,
        "people": [asdict(p) | {"name": p.name} for p in people],
        "contractors": contractors,
        "documents": [asdict(d) for d in docs],
    }, indent=2))

    # Only employees: contractors, managers' contacts and emergency contacts are
    # not in HR's employee list, so the detector must find those on its own.
    ROSTER.write_text(json.dumps({"employees": [p.name for p in people]}, indent=2) + "\n")

    total = sum(len(d.pii) for d in docs)
    print(f"{len(docs)} documents, {sum(d.pages for d in docs)} pages, {total} private values in the answer key")
    for d in docs:
        print(f"  {d.file:42} {d.kind:20} {d.pages:>2} p  {len(d.pii):>3} PII{'  (scanned)' if d.scanned else ''}")
    if misses:
        print("\nNOT FOUND in the PDF text (fix the generator):")
        print("\n".join("  " + m for m in misses))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
