# Linux / Oracle / Windows via Docker. On a Mac, prefer the native install so Ollama can use Metal.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    MEMEDESK_DATA=/data \
    DESK_HOST=0.0.0.0 \
    DESK_PORT=8787 \
    TRUST_PROXY=1 \
    KAIRO_ENV=production \
    KAIRO_MULTIUSER=1 \
    KAIRO_LIVE_ENABLED=0 \
    KAIRO_NO_BROWSER=1

LABEL org.opencontainers.image.source="https://github.com/businesstradeforex-ui/kairo" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.title="Kairo"

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 kairo \
    && mkdir -p /data && chown kairo /data

COPY --chown=kairo kairo/ /app/
USER kairo
VOLUME /data
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/health', timeout=4)"
CMD ["python", "run.py", "all"]
