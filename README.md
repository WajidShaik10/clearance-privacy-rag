 # Privacy-Safe RAG

Ask plain-English questions about HR, payroll and tax documents and get answers with page citations, without exposing personal data. Real values (SSNs, names, salaries, bank details) are replaced with placeholders like `PERSON_1` before anything is stored or sent to an AI model. Only HR can see the real values, and every reveal is logged.

![How it works](docs/system-design-explained.png)

## Code layout

| File | Diagram steps | Job |
|---|---|---|
| `src/extract.py` | 1, 2 | Read PDFs page by page |
| `src/detect.py` | 3, 11 | Find private info (documents and answers) |
| `src/mask.py` | 4, 8, 13 | Swap real values ↔ placeholders |
| `src/vault.py` | safe, 16 | Encrypted store + audit log |
| `src/index.py` | 5, 9 | Store and search masked passages |
| `src/answer.py` | 10 | Ask the AI model |
| `src/roles.py` | 7, 12 | Who can ask what, who sees real values |
| `src/pipeline.py` | 6, 14, 15, blocked | Run a question through every step |

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_lg   # name-finding model (~400 MB)
brew install tesseract                    # OCR for scanned pages
python scripts/make_fake_docs.py          # 22 fake PDFs + data/answer_key.json
pytest
python scripts/evaluate_detection.py      # PII detection score vs the answer key
python scripts/evaluate_unseen.py test    # PII detection score on unseen documents (Gretel)
```

## Test data

All test documents are fake. `scripts/make_fake_docs.py` invents 12 employees and 2 contractors with Faker (fixed seed, so the output is the same every run). It writes their details onto real blank IRS forms (W-2, W-4, W-9 from irs.gov) and onto generated payslips, HR files and a payroll register. Two documents are also saved as scanned images to test OCR. Phone numbers use the reserved 555-01xx range and emails use `example.com`.

`data/answer_key.json` lists every private value and the page it appears on, so we can measure exactly what the PII detector catches.
