FROM python:3.12-slim AS builder

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip hatchling

COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libnss3 libnspr4 libatk-bridge2.0-0 libdrm2 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 \
    libasound2t64 libpango-1.0-0 libcairo2 libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

RUN pip install --no-cache-dir playwright && \
    python -m playwright install chromium && \
    python -m playwright install-deps chromium

RUN useradd -m -u 1000 appuser && \
    mkdir -p /data/results && \
    chown -R appuser:appuser /data

WORKDIR /app
COPY --chown=appuser:appuser site2md/ ./site2md/

USER appuser

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD curl -f http://localhost:8088/health || exit 1

EXPOSE 8088

CMD ["uvicorn", "site2md.main:app", "--host", "0.0.0.0", "--port", "8088", "--workers", "2"]
