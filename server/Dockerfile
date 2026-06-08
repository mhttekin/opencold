# OpenCold API — private FastAPI service.
# Build from the repo root so the opencold package is in context:
#   docker build -f server/Dockerfile -t opencold-api .
FROM python:3.11-slim

WORKDIR /app

# Install the opencold package (core pipeline) first for better layer caching.
COPY pyproject.toml ./
COPY opencold ./opencold
RUN pip install --no-cache-dir .

# Then the server's own deps and code.
COPY server ./server
RUN pip install --no-cache-dir -r server/requirements.txt

EXPOSE 8000

# Single worker: the in-memory job store is per-process. No access log so that
# request bodies (which carry the user's keys) are never written anywhere.
CMD ["uvicorn", "main:app", "--app-dir", "server", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
