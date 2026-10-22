"""Steps 5 and 9: split masked pages into chunks, store them, and search them.

Only masked text is ever chunked or stored here. Each chunk keeps its doc_id and
page number so answers can cite them.

Chunk size is measured in the embedding model's own tokens, not words: MiniLM
reads at most 256 tokens and silently ignores the rest, and placeholders are
expensive ("BANK_ACCOUNT_1" is 5 tokens), so a masked line can cost twice its
word count.
"""

import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

from src.detect import is_organization

MAX_BODY_TOKENS = 200  # the chunk's own lines
MAX_HEADER_TOKENS = 40  # the context line added on top; 200 + 40 stays under MiniLM's 256
OVERLAP_TOKENS = 40  # up to this much of the previous chunk's end is repeated
PLACEHOLDER = re.compile(r"\b[A-Z][A-Z_]*_\d+\b")


# ---------------------------------------------------------------- counting tokens

@lru_cache(maxsize=1)
def _tokenizer():
    # The tokenizer file only exists once the model has been downloaded, which ChromaDB does on
    # the first embedding. On a fresh machine (CI) chunking runs first, so embed once to fetch it.
    embedder = _embedder()
    embedder(["warm up"])
    return embedder.tokenizer


def count_tokens(text: str) -> int:
    """How many tokens MiniLM sees for this text (padding and start/end markers excluded)."""
    if not text.strip():
        return 0
    return sum(_tokenizer().encode(text).attention_mask) - 2


def trim_to_tokens(text: str, limit: int) -> str:
    """Cut text (at a word boundary) so it fits in `limit` tokens."""
    words = text.split()
    while words and count_tokens(" ".join(words)) > limit:
        words.pop()
    return " ".join(words)


# ---------------------------------------------------------------- headers

def page_heading(page_text: str) -> str:
    """The page's first line, plus the lines after it up to the first private value.

    On our documents that is the title and, for tables, the column names
    ("Payroll Register: Q3 2025 ... Emp ID Name SSN Gross ..."): exactly what a
    chunk from the middle of the page needs to make sense on its own. The
    company's name and address, printed on every page, are skipped: they say
    nothing about the chunk and would crowd out the column names. The first line
    is kept even if it holds a placeholder: "Personnel File: PERSON_5" is the title.
    """
    lines = []
    for line in page_text.splitlines():
        if is_organization(line) or not line.strip():
            continue
        if lines and PLACEHOLDER.search(line):
            break
        lines.append(line)
    return trim_to_tokens(" ".join(lines), MAX_HEADER_TOKENS)


def document_title(first_page_text: str) -> str:
    """Just the title line ("Payroll Register: Q3 2025"), not page 1's month or columns,
    which would mislabel chunks from later pages."""
    return next((trim_to_tokens(line, MAX_HEADER_TOKENS) for line in first_page_text.splitlines()
                 if line.strip() and not is_organization(line)), "")


PERSON_PLACEHOLDER = re.compile(r"\bPERSON_\d+\b")


def document_subject(pages: list[dict]) -> str | None:
    """The person a document is about (a W-2, payslip, personnel file), if there is one.

    A long form is split into several chunks, and the name can land in a different
    chunk from, say, the federal tax box. Naming the subject in every chunk's header
    keeps "whose W-2 is this?" answerable. Documents about many people (a directory,
    a payroll register) have no single subject.
    """
    mentions = Counter(PERSON_PLACEHOLDER.findall(" ".join(p["text"] for p in pages)))
    if not mentions:
        return None
    person, count = mentions.most_common(1)[0]
    return person if count / sum(mentions.values()) >= 0.5 else None


# ---------------------------------------------------------------- splitting

def split_long_line(line: str, limit: int) -> list[str]:
    """Split a line that alone is over the limit: at sentence ends, then at words."""
    if count_tokens(line) <= limit:
        return [line]
    pieces, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", line):
        candidate = f"{current} {sentence}".strip()
        if count_tokens(candidate) <= limit:
            current = candidate
            continue
        if current:
            pieces.append(current)
        while count_tokens(sentence) > limit:  # one sentence is still too long: cut by words
            head = trim_to_tokens(sentence, limit)
            pieces.append(head)
            sentence = sentence[len(head):].strip()
        current = sentence
    if current:
        pieces.append(current)
    return pieces


def chunk_page(page_text: str) -> list[str]:
    """Split one page into bodies of at most MAX_BODY_TOKENS, never cutting a line.

    Each chunk after the first starts with the last line(s) of the previous one
    (up to OVERLAP_TOKENS), so text near a boundary appears whole in one chunk.
    """
    lines = [piece for line in page_text.splitlines() if line.strip()
             for piece in split_long_line(line, MAX_BODY_TOKENS)]
    chunks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if current and count_tokens("\n".join(current + [line])) > MAX_BODY_TOKENS:
            chunks.append(current)
            # Overlap: carry the last line(s) of this chunk into the next.
            carry = []
            for prev in reversed(current):
                if count_tokens("\n".join([prev] + carry + [line])) > OVERLAP_TOKENS + count_tokens(line):
                    break
                carry.insert(0, prev)
            current = carry
        current.append(line)
    if current:
        chunks.append(current)
    return ["\n".join(c) for c in chunks]


def chunk_document(masked: dict) -> list[dict]:
    """Chunk a document returned by mask.mask_document().

    Every chunk except the very first gets a header in square brackets: the
    document's title, plus (when the chunk does not start the page) the page's
    own heading, so a chunk from the middle of a table still says what table,
    and which month, it is from.
    """
    if "doc_id" not in masked or "doc" in masked:
        raise ValueError("chunk_document() takes masked documents only (from mask.mask_document)")

    doc_title = document_title(masked["pages"][0]["text"]) if masked["pages"] else ""
    subject = document_subject(masked["pages"])
    chunks = []
    for page in masked["pages"]:
        heading = page_heading(page["text"])
        for n, body in enumerate(chunk_page(page["text"]), start=1):
            first_of_doc = page["page"] == 1 and n == 1
            parts = [] if first_of_doc else [doc_title]
            if n > 1:
                parts.append(heading.removeprefix(doc_title).strip())
            if subject and subject not in body:
                parts.insert(0, f"About {subject}")
            header = trim_to_tokens(" | ".join(p for p in parts if p), MAX_HEADER_TOKENS)
            text = f"[{header}]\n{body}" if header else body
            chunks.append({
                "chunk_id": f"{masked['doc_id']}-p{page['page']}-c{n}",
                "doc_id": masked["doc_id"],
                "page": page["page"],
                "text": text,
                "tokens": count_tokens(text),
            })
    return chunks


# ---------------------------------------------------------------- keyword search (BM25)

WORD = re.compile(r"\w+")  # \w includes "_", so "PERSON_5" stays one word


def words(text: str) -> list[str]:
    return [w.lower() for w in WORD.findall(text)]


def bm25_scores(query: str, texts: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
    """Score each text for the query's exact words (BM25, the classic search-engine formula).

    Rare words count more than common ones: "person_5" appears in a few chunks,
    "the" in almost all, so a match on "person_5" lifts a chunk far more.
    """
    docs = [words(t) for t in texts]
    if not docs:
        return []
    avg_len = sum(map(len, docs)) / len(docs)
    doc_freq = Counter(w for d in docs for w in set(d))
    scores = []
    for d in docs:
        tf = Counter(d)
        score = 0.0
        for w in set(words(query)):
            if w not in tf:
                continue
            idf = math.log(1 + (len(docs) - doc_freq[w] + 0.5) / (doc_freq[w] + 0.5))
            score += idf * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * len(d) / avg_len))
        scores.append(score)
    return scores


# ---------------------------------------------------------------- the search library

INDEX_PATH = Path(__file__).resolve().parent.parent / "data" / "index"
RRF_K = 60  # standard constant for reciprocal rank fusion


@lru_cache(maxsize=1)
def _embedder():
    # The same MiniLM whose tokenizer measured the chunks above.
    from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

    return ONNXMiniLM_L6_V2()


class SearchLibrary:
    """Masked chunks, searchable by meaning (embeddings) and by exact words (BM25).

    Stored with ChromaDB on local disk (data/index/, not in git). It only ever
    receives masked chunks, so nothing in it is personal data.
    """

    def __init__(self, path: str | Path = INDEX_PATH):
        import chromadb
        from chromadb.config import Settings

        # Telemetry off: a privacy project should not send usage data anywhere.
        self._client = chromadb.PersistentClient(path=str(path), settings=Settings(anonymized_telemetry=False))
        self._chunks = self._client.get_or_create_collection(
            "chunks", embedding_function=_embedder(), metadata={"hnsw:space": "cosine"})

    def add(self, chunks: list[dict]) -> None:
        """Embed and store chunks. Adding the same chunk_id again replaces it."""
        if chunks:
            self._chunks.upsert(
                ids=[c["chunk_id"] for c in chunks],
                documents=[c["text"] for c in chunks],
                metadatas=[{"doc_id": c["doc_id"], "page": c["page"]} for c in chunks],
            )

    def count(self) -> int:
        return self._chunks.count()

    def reset(self) -> None:
        """Empty the library."""
        self._client.delete_collection("chunks")
        self._chunks = self._client.get_or_create_collection(
            "chunks", embedding_function=_embedder(), metadata={"hnsw:space": "cosine"})

    def vector_search(self, question: str, n: int) -> list[str]:
        """chunk_ids closest in meaning to the question, best first."""
        if not self.count():
            return []
        result = self._chunks.query(query_texts=[question], n_results=min(n, self.count()))
        return result["ids"][0]

    def keyword_search(self, question: str, n: int) -> list[str]:
        """chunk_ids sharing the question's exact words (e.g. PERSON_5), best first."""
        stored = self._chunks.get()
        scores = bm25_scores(question, stored["documents"])
        ranked = sorted(zip(scores, stored["ids"]), reverse=True)
        return [chunk_id for score, chunk_id in ranked[:n] if score > 0]

    def search(self, question: str, k: int = 5, candidates: int = 20) -> list[dict]:
        """Hybrid search: combine both rankings with reciprocal rank fusion (RRF).

        Each list gives a chunk 1 / (60 + its rank); a chunk ranked well by both
        methods beats one that only one method liked.

        When the question names records (PERSON_3), chunks that mention them come
        first: a chunk without PERSON_3 cannot answer a question about PERSON_3.
        Without this, the directory row that keyword search ranked #1 lost to W-9
        instructions that both methods half-liked for the words "phone number".
        """
        rankings = {"vector": self.vector_search(question, candidates),
                    "keyword": self.keyword_search(question, candidates)}
        fused: dict[str, float] = {}
        ranks: dict[str, dict] = {}
        for method, ids in rankings.items():
            for rank, chunk_id in enumerate(ids, start=1):
                fused[chunk_id] = fused.get(chunk_id, 0.0) + 1 / (RRF_K + rank)
                ranks.setdefault(chunk_id, {})[method] = rank
        if not fused:
            return []

        stored = self._chunks.get(ids=list(fused))
        by_id = {i: (doc, meta) for i, doc, meta in zip(stored["ids"], stored["documents"], stored["metadatas"])}
        named = set(PLACEHOLDER.findall(question))

        def order(chunk_id: str) -> tuple:
            mentions = sum(p in set(PLACEHOLDER.findall(by_id[chunk_id][0])) for p in named)
            return (mentions, fused[chunk_id])

        best = sorted(fused, key=order, reverse=True)[:k]
        return [{"chunk_id": i, "doc_id": by_id[i][1]["doc_id"], "page": by_id[i][1]["page"],
                 "text": by_id[i][0], "score": round(fused[i], 4),
                 "vector_rank": ranks[i].get("vector"), "keyword_rank": ranks[i].get("keyword")}
                for i in best]


# ---------------------------------------------------------------- writing from a clean process

def _write_chunks(chunks: list[dict], path: str) -> None:
    SearchLibrary(path).add(chunks)


def build_in_clean_process(chunks: list[dict], path: str | Path = INDEX_PATH) -> None:
    """Write a fresh library from masked chunks, in a separate process that never held real data.

    Found by the attack tests: a library file (ChromaDB's data_level0.bin) built inside
    a test run held 126 real values from documents never added to it. The file was
    written with leftover memory from the same program, which had read raw PDFs.
    So the program that reads raw PDFs never writes the library: a fresh process,
    given only masked chunks, does. The old folder is removed first, so no earlier
    build is left behind.
    """
    import multiprocessing
    import shutil

    shutil.rmtree(path, ignore_errors=True)
    worker = multiprocessing.get_context("spawn").Process(target=_write_chunks, args=(chunks, str(path)))
    worker.start()
    worker.join()
    if worker.exitcode != 0:
        raise RuntimeError(f"Building the search library failed (exit code {worker.exitcode})")
