FROM python:3.12-slim
WORKDIR /app
COPY relay/requirements.txt /app/relay/requirements.txt
RUN pip install --no-cache-dir -r relay/requirements.txt \
    && useradd --uid 10001 --create-home relay \
    && mkdir /data && chown relay:relay /data
COPY relay/ /app/relay/
COPY scripts/retry_delivery.py /app/scripts/retry_delivery.py
USER relay
ENV DATABASE_PATH=/data/relay.sqlite3
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"
CMD ["uvicorn", "relay.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
