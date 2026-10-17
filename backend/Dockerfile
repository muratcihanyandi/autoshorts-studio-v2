FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic

EXPOSE 8000

# Uygulama root olarak kosmaz: medya dosyalari Pi'nin ana kullanıcısına
# (UID/GID 1000) ait olur. USB klasörü de ayni UID'ye chown edilmelidir:
#   chown -R 1000:1000 /mnt/usb/Autoshorts_Studio
USER 1000:1000

# Migrations run before the API starts so the schema is always current.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
