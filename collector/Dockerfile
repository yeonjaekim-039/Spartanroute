FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY schema.sql .
COPY collector ./collector

RUN useradd --create-home app && mkdir -p /data && chown app /data
USER app

CMD ["python", "-m", "collector.main"]
