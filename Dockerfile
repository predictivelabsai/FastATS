FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

RUN mkdir -p /data/uploads
ENV FASTATS_DB=/data/fastats.sqlite FASTATS_UPLOAD_DIR=/data/uploads FASTATS_PORT=5020
EXPOSE 5020
CMD ["python", "web_app.py"]

