# Clearance: the privacy-safe HR document assistant, packaged.
#   docker compose up --build      (then open http://127.0.0.1:8000)
# Secrets (vault keys, OpenAI key) are NOT built into the image: they come from .env at run time.

FROM python:3.14-slim

# Tesseract reads scanned pages (OCR).
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr \
 && rm -rf /var/lib/apt/lists/*

# Run as an ordinary user, not root.
RUN useradd --create-home --uid 1000 clearance
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && python -m spacy download en_core_web_lg

COPY --chown=clearance:clearance src ./src
COPY --chown=clearance:clearance app ./app
COPY --chown=clearance:clearance scripts/ingest.py ./scripts/ingest.py
COPY --chown=clearance:clearance data/fake_docs ./data/fake_docs
COPY --chown=clearance:clearance data/hr_roster.json ./data/hr_roster.json
COPY --chown=clearance:clearance docker/entrypoint.sh ./entrypoint.sh

USER clearance
# Download the embedding model now, so the container never fetches anything when it starts.
RUN python -c "from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2; ONNXMiniLM_L6_V2()(['warm up'])" \
 && mkdir -p data/vault data/index

ENV HOST=0.0.0.0 PYTHONUNBUFFERED=1
EXPOSE 8000
ENTRYPOINT ["sh", "./entrypoint.sh"]
