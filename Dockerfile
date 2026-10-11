FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY config ./config

RUN useradd --create-home --uid 10001 sync && mkdir -p /data && chown sync /data
USER sync

VOLUME ["/data"]

ENTRYPOINT ["python", "-m", "app"]
CMD ["run"]
