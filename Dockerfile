FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN python -m pip install --no-cache-dir . \
    && useradd --uid 1000 --create-home --shell /usr/sbin/nologin trading

COPY configs/ ./configs/
USER 1000:1000
CMD ["trading-platform", "info"]
