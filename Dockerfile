FROM python:3.12-slim

LABEL org.opencontainers.image.title="Watchtower" \
      org.opencontainers.image.description="Routes tickets to the right on-call responder. The right person. Right on time."

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    PORT=8080

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY watchtower ./watchtower
COPY config ./config

# "sync" is a built-in Debian system account, so use a distinct name.
RUN useradd --create-home --uid 10001 appuser && mkdir -p /data && chown appuser /data
USER appuser

VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4).status == 200 else 1)"

ENTRYPOINT ["python", "-m", "watchtower"]
CMD ["run"]
