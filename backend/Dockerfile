FROM python:3.12-slim

WORKDIR /app

# Install build deps for asyncpg
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && rm -rf /var/lib/apt/lists/*

# All runtime dependencies (including the LLM SDKs) are declared and pinned
# in pyproject.toml — do not add ad-hoc installs here.
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

COPY . .

ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
