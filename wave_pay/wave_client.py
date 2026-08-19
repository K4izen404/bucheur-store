"""Client de l'API Payments Wave (https://docs.wave.com/checkout).

- Authentification par clé API (Bearer), jamais côté client.
- Signature des requêtes (HMAC-SHA256) si un signing secret est configuré.
- Mode sandbox : définir WAVE_API_BASE (ex : https://api.wave.com/v1/sandbox)
  avec une clé de test fournie par Wave.
"""
import hashlib
import hmac
import os
import time

import httpx

API_BASE = os.environ.get("WAVE_API_BASE", "https://api.wave.com")
API_KEY = os.environ.get("WAVE_API_KEY", "")
SIGNING_SECRET = os.environ.get("WAVE_SIGNING_SECRET", "")


def _sign_headers(body: str) -> dict:
    """Signe la requête : Wave-Signature: t=<ts>,v1=<hmac-sha256(ts+body)> (doc officielle)."""
    if not SIGNING_SECRET:
        return {}
    timestamp = str(int(time.time()))
    digest = hmac.new(SIGNING_SECRET.encode(), (timestamp + body).encode(),
                      hashlib.sha256).hexdigest()
    return {"Wave-Signature": f"t={timestamp},v1={digest}"}


def create_checkout_session(*, amount_xof: int, client_reference: str,
                            success_url: str, error_url: str,
                            restrict_payer_mobile: str | None = None) -> dict:
    """Crée une session de paiement Wave pour un montant EXACT (issu de la base, jamais du client)."""
    if not API_KEY:
        raise RuntimeError("WAVE_API_KEY non configurée")
    body = {
        "amount": str(int(amount_xof)),
        "currency": "XOF",
        "client_reference": client_reference,
        "success_url": success_url,
        "error_url": error_url,
    }
    if restrict_payer_mobile:
        body["restrict_payer_mobile"] = restrict_payer_mobile
    payload = __import__("json").dumps(body)
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    headers.update(_sign_headers(payload))
    resp = httpx.post(f"{API_BASE}/v1/checkout/sessions", content=payload,
                      headers=headers, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"Wave API {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    return {
        "session_id": data["id"],
        "wave_launch_url": data["wave_launch_url"],
        "amount": data["amount"],
        "currency": data["currency"],
    }