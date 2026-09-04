FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PHENIKAA_SERVER_HOST=0.0.0.0 \
    PHENIKAA_SERVER_STATE=/data \
    PHENIKAA_BROWSER_NO_SANDBOX=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

WORKDIR /app

COPY pyproject.toml setup.py README.md ./
COPY phenikaa_exporter.py phenikaa_login.py ./
COPY server ./server

RUN pip install --no-cache-dir '.[server]' \
    && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/* /tmp/*

RUN useradd --create-home --uid 1000 phenikaa \
    && mkdir -p /data \
    && chown -R phenikaa:phenikaa /data /app
USER phenikaa

VOLUME /data
EXPOSE 8416

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os, sys, urllib.request; port = os.environ.get('PHENIKAA_SERVER_PORT', '8416'); sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:' + port + '/healthz', timeout=4).status == 200 else 1)"

ENTRYPOINT ["phenikaa-calendar-server"]
