# Project brief: Privacy-Safe RAG

Reviewed on October 20, 2026 against the current working tree, based at commit `c6954c0`. This brief describes observed implementation and local measurements, not a literature review or a completed journal manuscript. Existing uncommitted changes were included in the review and left untouched.

## 1. What the project does

This is a Python research prototype for question answering over HR, payroll, and tax PDFs. It replaces detected personal values with consistent placeholders before indexing documents or sending retrieved passages to a hosted language model. An encrypted local vault preserves the mapping. Employees receive masked answers to permitted questions; callers assigned the HR role can receive restored values, with reveal attempts recorded in an audit log.

The central technique is **reversible pseudonymization**, not irreversible anonymization. Names, numbers, and amounts become tokens such as `PERSON_5` and `MONEY_14`. Consistency allows a question and several documents to refer to the same value without exposing that value to the model, provided detection succeeds.

The practical research question is: **How much retrieval and answer utility can be preserved when personal values are pseudonymized before retrieval and generation, and where does the privacy protection fail?**

## 2. Data and architecture

The generated corpus contains 22 PDFs representing 12 employees and two contractors. It includes filled IRS forms, payslips, personnel files, a directory, a payroll register, and a leave policy. Two PDFs are scanned copies. The generator uses Faker with a fixed seed. `data/answer_key.json` provides page-level expected private values; `data/hr_roster.json` supplies known employee names.

| Stage | Implementation | What happens |
|---|---|---|
| Extraction | `src/extract.py` | PyMuPDF reads digital text in spatial order; Tesseract reads scanned pages at 300 DPI. Page numbers and OCR confidence are retained. |
| Detection | `src/detect.py` | Combines regex/context checks, labeled fields, known names and variants, and pretrained spaCy name recognition. Overlaps are resolved before replacement. |
| Vault | `src/vault.py` | SQLite stores Fernet-encrypted values and typed HMAC-SHA256 fingerprints using separate keys. Fingerprints support consistent lookup. |
| Masking | `src/mask.py` | Replaces detected values and filenames; drops unused PDF metadata; masks comments. Unambiguous name variants can share a canonical identity. |
| Chunking | `src/index.py` | Uses MiniLM token counts, a 200-token body target, 40-token header budget, and approximately 40-token overlap. Adds document/page context and an inferred subject. |
| Retrieval | `src/index.py` | Local Chroma embeddings plus custom BM25, fused with reciprocal rank fusion. Explicit placeholder matches receive priority in final ranking. |
| Authorization | `src/roles.py` | Unknown roles are denied. Employees are screened with PII detection and question heuristics. HR is allowed all questions. |
| Generation | `src/answer.py` | Sends a masked question and passages to the configured OpenAI model, requesting structured JSON with answerability and page citations. |
| Output guard | `src/pipeline.py` | Scans for detectable raw PII and rejects placeholders absent from the supplied context or vault. |
| Restoration | `src/mask.py`, `src/vault.py` | Restores values for HR and logs each distinct placeholder reveal in that answer. Other roles retain placeholders. |

Ingestion: PDF → extraction → detection → masking/vault → chunks → local embeddings/index.

Question answering: question → role gate → question masking → top-five retrieval → generation → output guard → role-dependent restoration.

Raw source PDFs and the synthetic roster remain on disk. “Masked before storage” applies to the search index, not all project storage. The index APIs rely on callers to pass correctly masked content; document shape checks are not independent privacy validation.

## 3. What happened during development

The repository records this sequence. All seven commits currently have October 20, 2026 dates; they establish order, not the duration of the work.

1. `4eb36b6`: project setup, synthetic corpus, PDF extraction, and OCR.
2. `9a76d9d`: initial layered PII detection.
3. `b7b1bb9`: external-data evaluation and detector improvements; the commit message reports approximately 41% → 68%. The historical 41% baseline was not rerun during this review.
4. `1498466`: encrypted vault and consistent reversible masking.
5. `365cdcb`: token-aware chunking, local embeddings, and hybrid retrieval.
6. `993de8b`: hosted-model answers and citation membership checks.
7. `c6954c0`: role rules, final output guard, and complete question pipeline.

Current uncommitted work adds SSNs separated by spaces/dots, fake-placeholder defanging, employee placeholder-query blocking, retrieval subject prioritization, offline attack tests, and a live answer-evaluation script. The `app/` directory contains only `.gitkeep`; a web interface is not implemented despite UI packages appearing in requirements.

Several engineering lessons are visible in comments and tests: PDF reading order must preserve table rows; OCR quality affects detection; placeholders consume multiple embedding tokens; masking must preserve identity across documents; vector similarity alone may confuse records; user-authored placeholder text must not become a vault lookup.

## 4. Measurements reproduced in this review

Commands used the existing `.venv`. Detection evaluated the current source. Search evaluated the existing persisted index, which was not rebuilt; its construction provenance must be recorded for publication.

| Measurement | Result | Interpretation |
|---|---|---|
| Test suite (`pytest -q -k 'not live'`) | 357 passed, 2 deselected; 6 deprecation warnings | Selected tests pass; name-based filtering excludes two tests. No live model result is claimed. |
| Generated PDF detection | 381/381 expected values caught, 100% recall | Success on the small, development-specific corpus. |
| Leave-policy false positives | 0 | One negative-control document, not corpus-wide precision. |
| External English test sample | 116 documents; 231/339 in-scope spans caught, 68.1% | Material domain/format generalization gap. |
| External out-of-scope sensitive spans | 1/67 caught, 1.5% | Unsupported categories remain exposed; this is not a comprehensive PII detector. |
| Vector retrieval, top five | 9/12 questions, 75% | Answer-bearing page appeared among retrieved results. |
| Keyword retrieval, top five | 12/12 questions, 100% | Exact terms and consistent placeholders work well on this question set. |
| Hybrid retrieval, top five | 12/12 questions, 100% | Ties keyword retrieval here; no demonstrated superiority over BM25. |

The external sample uses English rows from offsets 300–499 of the locally downloaded Gretel sample. Rows 0–299 serve as development data. This is the repository's local split of a sample from an upstream test split, not a score on the full dataset. Split discipline is documented in the repository but cannot be established from the present code alone.

The generated-data evaluator uses value containment or numeric equivalence. The external evaluator calls a span caught when at least 90% of its characters overlap any detection, regardless of predicted type. These are different recall definitions, and 90% coverage can still leave sensitive characters visible. Neither evaluation measures general precision or establishes zero leakage.

The external test found only 109/166 full-name spans and 0/8 standalone surname spans. Addresses reached 67/95; phones 11/16. These results give concrete directions for improvement.

Live answer accuracy and live prompt-injection behavior were not run in this review. `scripts/evaluate_answers.py` exists, but its expected-value matching is a preliminary heuristic, not a full factuality assessment. It also accepts differing register/payslip net-pay values, so answer targets need reconciliation before formal scoring.

## 5. Claims and limitations to explain honestly

- **Privacy is conditional on detection.** The same detector is used before ingestion and after generation, so both stages may share blind spots. An output guard cannot undo raw PII already sent upstream after a detection miss.
- **Role checking is not authentication.** The CLI accepts `--user` and `--role`; no identity provider verifies them. Deployment needs trusted identity-to-role binding. HR currently has unrestricted access rather than record- or field-specific authorization.
- **Masked data can remain sensitive.** Stable identifiers and surrounding context can disclose relationships or enable inference. No reidentification-risk evaluation or formal privacy guarantee is implemented.
- **Citations are checked for membership, not entailment.** A retrieved page can be cited without actually supporting the answer. Removing invalid citations does not itself block an otherwise unsupported answer.
- **The model can mix valid placeholders incorrectly.** The output guard verifies existence and context membership, not that a particular salary belongs to a particular person.
- **OCR review is advisory.** Low-confidence documents are flagged but still indexed by `scripts/ingest.py`; there is no quarantine or human-approval gate.
- **Prompt-injection testing is bounded.** Offline malicious model stand-ins test specific guard behavior. They do not prove universal resistance by a live model, especially to instructions that change non-PII facts.
- **Auditability has limits.** Reveal attempts, refusals, and blocked answers are logged. Ordinary successful employee answers are not all logged, and the SQLite audit log has no demonstrated tamper-evidence mechanism.
- **Operations are prototype-level.** Key rotation, recovery procedures, concurrency, deletion lifecycle, large-corpus performance, and production authorization need additional work. BM25 currently loads and scores all stored documents per query.
- **Avoid claims inferred from dependencies or settings.** The detector directly uses spaCy and custom rules; installing Presidio does not mean this implementation calls Presidio. `store=False` is a request setting, not evidence by itself of all provider retention behavior.

Prefer: “The system masked all annotated values in our generated corpus; held-out external evaluation exposed substantial remaining detection gaps.” Avoid: “The system never exposes personal data.”

## 6. Journal preparation

Possible working title: **Evaluating Reversible Pseudonymization for Role-Aware Question Answering over HR Documents**.

The present contribution is a systems integration and evaluation candidate. Novelty relative to published work has not been established. A paper should not present standard encryption, BM25, RRF, or RAG as new algorithms.

Suggested manuscript structure: problem and threat model; related work; corpus and annotation; pipeline design; experimental protocol; results; failure analysis; limitations and reproducibility.

Before a submission-quality draft:

1. Define the trust boundary and attacker capabilities: original documents, local vault, index, hosted model, employee, and HR. Distinguish direct identifier leakage from inference and unauthorized access.
2. Freeze a versioned dataset and genuinely untouched test set. Record corpus hashes, annotation rules, software/model versions, prompts, seeds, and the exact index build.
3. Measure exact-span and character-level detection precision/recall, residual sensitive characters, and document-level leakage. Report uncertainty and per-type sample sizes.
4. Run ablations: rules only; rules plus spaCy; roster and name variants; masking versus a synthetic-only unmasked baseline; vector/BM25/RRF; subject prioritization on/off; output guard on/off.
5. Expand and freeze retrieval questions, including paraphrases, ambiguous names, cross-document questions, and unanswerable questions. Measure page hit rate, relevant-chunk recall, and ranking quality separately.
6. Measure live answer correctness, citation support, abstention, unauthorized disclosure, attack success, latency, and cost. Use independently checked answers rather than substring matching alone.
7. Test unseen document layouts, degraded scans, new organizations, name collisions, and supported/unsupported PII formats. Keep attack development separate from final evaluation.
8. Review related literature before stating novelty or selecting a venue. No literature search was performed for this code-understanding brief.

## 7. Interview preparation

### A concise project explanation

“I built a prototype for asking questions over sensitive HR and payroll PDFs. It extracts digital and scanned text, detects personal values, and replaces them with consistent placeholders before indexing and sending passages to a language model. A local encrypted vault restores values for callers assigned the HR role and logs those reveals. I combined semantic and keyword retrieval because exact identity placeholders are important. The detector caught all 381 annotated values in my generated corpus, but only 68.1% of in-scope spans in an external English test sample, which exposed the main limitation: generalization of PII detection.”

Use “I built” only for work you can accurately claim and explain; repository history alone does not establish individual authorship.

### Questions to be ready for

**Why not delete personal data permanently?** Consistent reversible tokens preserve cross-document references and allow authorized restoration. The tradeoff is a sensitive mapping vault and persistent linkability.

**Why use HMAC and encryption?** Encryption protects recoverable values; keyed fingerprints support consistent lookup without decrypting every row. Including the type separates identical strings used for different kinds of information.

**Why combine vector search and BM25?** Semantic embeddings help with wording variation, while BM25 preserves exact placeholder matches. On the current 12-question benchmark, BM25 and hybrid both reached 12/12; more evidence is needed to justify hybrid's additional cost.

**Did you train an LLM?** No custom LLM training is implemented. This is a retrieval and privacy-control pipeline using pretrained spaCy, local pretrained embeddings, and a hosted generation model.

**What was technically difficult?** Preserving PDF table associations, reading scanned IDs correctly, handling name variants without joining different people, respecting embedding token limits after masking, and preventing forged placeholders from triggering restoration.

**What is the biggest weakness?** Detection misses can expose raw values before the model call. The output guard shares the detector's blind spots. The external recall result makes that limitation measurable.

**Is it production-ready?** It is a tested prototype. Production would require authenticated roles, narrower access policies, stronger evaluation, operational key management, and enforced review of uncertain extraction.

**What would you improve first?** Establish a stronger held-out leakage benchmark and close its most consequential detection gaps, then enforce identity and authorization boundaries. Evaluate answer support and record association alongside privacy.

For a demo, show a policy question, an employee refusal for a named person's salary, an HR answer with a page citation, and the associated audit entries. Explain that the demo assumes a trusted role assignment.
