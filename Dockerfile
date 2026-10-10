FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first so this layer is cached until requirements change.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY dashboard.py ./
COPY sample_data ./sample_data

# Run as a non-root user; /data holds the SQLite file (mount a volume here).
RUN useradd --create-home appuser \
    && mkdir /data \
    && chown -R appuser /app /data
USER appuser
ENV DATABASE_URL=sqlite:////data/upi_analyzer.db

EXPOSE 8000 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
