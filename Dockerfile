FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    DATABASE=/data/printmanager.db \
    UPLOAD_FOLDER=/data/uploads

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY printmanager ./printmanager

VOLUME /data
EXPOSE 8000

# One worker is plenty for two users and keeps SQLite writes simple.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "printmanager:create_app()"]
