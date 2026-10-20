"""Phase 1 end to end: read -> find PII -> mask -> chunk -> embed -> store.

    python scripts/ingest.py                    # all PDFs in data/fake_docs/
    python scripts/ingest.py path/to/folder

Uses the real vault (data/vault/, keys from .env) and the real search library
(data/index/). Both folders are git-ignored. The library is rebuilt from scratch
by a separate, clean process that only ever receives masked chunks; the vault is
kept, so the same person keeps the same placeholder.
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.extract import extract_document  # noqa: E402
from src.index import INDEX_PATH, SearchLibrary, build_in_clean_process, chunk_document  # noqa: E402
from src.mask import mask_document  # noqa: E402
from src.vault import Vault  # noqa: E402

ROSTER = json.loads((ROOT / "data" / "hr_roster.json").read_text())["employees"]


def main() -> None:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "fake_docs"
    pdfs = sorted(folder.glob("*.pdf"))
    start, review, all_chunks = time.time(), [], []
    with Vault.from_env() as vault:
        for pdf in pdfs:
            masked = mask_document(extract_document(pdf), vault, ROSTER)
            chunks = chunk_document(masked)
            all_chunks += chunks
            if masked["needs_review"]:
                review.append(masked["doc_id"])
            print(f"  {masked['doc_id']:7} {len(chunks):3} chunks")  # the doc_id, never the file name
    build_in_clean_process(all_chunks, INDEX_PATH)  # this process read raw PDFs: it must not write the library
    print(f"\n{len(pdfs)} documents -> {SearchLibrary().count()} chunks in {time.time() - start:.0f}s")
    if review:
        print(f"Needs a person to check (low OCR confidence): {', '.join(review)}")


if __name__ == "__main__":
    main()
