FROM python:3.13-slim

# ffmpeg per i fotogrammi, Liberation Sans come equivalente di Arial nel PDF
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-liberation ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt   # include yt-dlp

COPY app ./app
COPY run.py .

ENV DATA_DIR=/app/data \
    PYTHONUNBUFFERED=1
VOLUME ["/app/data"]
EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
