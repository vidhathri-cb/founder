# Reconstructed 2026-09-06 -- the original Dockerfile was on the GitHub
# repo/account that got deleted before it could be copied over, so this is
# a fresh rebuild matching what main.py actually needs (FastAPI + reportlab
# + Google Drive upload), not a byte-identical copy of whatever was there
# before. Worth a first real deploy to confirm it behaves the same as the
# original -- see the note in the top-level README.

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render assigns the port to listen on via $PORT at runtime (not a fixed
# value) -- shell form CMD so that variable actually expands; 8000 is just
# a local-run fallback.
EXPOSE 8000
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
