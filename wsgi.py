"""Point d'entrée WSGI pour le déploiement sur PythonAnywhere.

Copiez ce contenu dans : Web tab > WSGI configuration file (onglet Code > WSGI).
Adaptez les valeurs marquées « à compléter ».
"""

import os

# --- Sécurité (à compléter AVANT la mise en ligne) ---
os.environ.setdefault("SECRET_KEY", "CHANGEZMOI-une-longue-cle-aleatoire-64-caracteres")
os.environ.setdefault("FORCE_HTTPS", "1")
os.environ.setdefault("APP_BASE_URL", "https://VOTRE-COMPTE.pythonanywhere.com")

# --- Emails Gmail (notifications commandes/paiements) — à compléter ---
os.environ.setdefault("SMTP_HOST", "smtp.gmail.com")
os.environ.setdefault("SMTP_PORT", "587")
os.environ.setdefault("SMTP_USER", "bucheur.store@gmail.com")
os.environ.setdefault("SMTP_PASSWORD", "VOTRE-MOT-DE-PASSE-APPLICATION-GMAIL")
os.environ.setdefault("SMTP_FROM", "bucheur.store@gmail.com")
os.environ.setdefault("ADMIN_NOTIFY_EMAIL", "bucheur.store@gmail.com")

from app import app as application  # noqa: E402