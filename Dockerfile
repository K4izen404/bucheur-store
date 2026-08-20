FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Seed pour le premier démarrage (base + images) conservés dans l'image
RUN mkdir -p /app/seed_uploads && cp -rn static/uploads/. seed_uploads/ 2>/dev/null || true

RUN chmod +x /app/entrypoint.sh

EXPOSE 5000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "-c", "from app import app; app.run(host='0.0.0.0', port=5000, threaded=True)"]