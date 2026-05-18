FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/app/data

WORKDIR /app

RUN addgroup --system fisbot \
    && adduser --system --ingroup fisbot fisbot

COPY pyproject.toml ./
COPY fisbot ./fisbot

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

RUN mkdir -p /app/data \
    && chown -R fisbot:fisbot /app

USER fisbot

VOLUME ["/app/data"]

CMD ["fisbot"]
