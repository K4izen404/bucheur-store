#!/bin/sh
set -e

# Premier démarrage : copie la base et les images produits de l'image
# vers les volumes persistants (ensuite elles restent dans les volumes).
if [ ! -f /app/data/bucheur.db ]; then
  cp /app/bucheur.db /app/data/bucheur.db
  echo "[entrypoint] base initialisée depuis l'image"
fi
if [ -d /app/seed_uploads ] && [ -n "$(ls -A /app/seed_uploads 2>/dev/null)" ]; then
  mkdir -p /app/static/uploads
  cp -n /app/seed_uploads/. /app/static/uploads/ 2>/dev/null || true
fi

exec "$@"