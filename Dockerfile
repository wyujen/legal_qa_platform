FROM python:3.12-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN python -m pip install "uv==0.12.5"

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync \
    --frozen \
    --no-dev \
    --extra ui \
    --extra observability \
    --no-editable \
    --no-python-downloads


FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --gid 10001 appuser \
    && useradd --create-home --uid 10001 --gid 10001 appuser

COPY --from=builder /build/.venv /build/.venv

COPY --chown=appuser:appuser data ./data
COPY --chown=appuser:appuser migrations ./migrations
COPY --chown=appuser:appuser profiles ./profiles
COPY --chown=appuser:appuser scripts ./scripts
COPY --chown=appuser:appuser src/legal_qa_platform/ui ./src/legal_qa_platform/ui

ENV PATH="/build/.venv/bin:${PATH}"

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"]

CMD ["python", "-m", "legal_qa_platform.api.server", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
