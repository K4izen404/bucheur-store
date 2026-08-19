"""Vérification des webhooks Wave (https://docs.wave.com/webhook).

Wave-Signature: t=<timestamp>,v1=<hmac-sha256 hex>[,v1=...] (rotation de secret possible)
Payload signé : timestamp + corps brut (EXACT, jamais re-sérialisé).
Anti-rejeu : timestamp rejeté si > 5 min dans le passé ou > 30 s dans le futur.
"""
import hashlib
import hmac
import json
import os
import time

WEBHOOK_SECRET = os.environ.get("WAVE_WEBHOOK_SECRET", "")
SKIP_FRESHNESS = os.environ.get("WAVE_WEBHOOK_SKIP_FRESHNESS") == "1"
MAX_AGE_SECONDS = 300
MAX_FUTURE_SECONDS = 30


class WaveWebhookError(Exception):
    pass


def _signatures_from_header(wave_signature: str) -> tuple[str, list[str]]:
    parts = wave_signature.split(",")
    timestamp = ""
    signatures = []
    for part in parts:
        if "=" not in part:
            raise WaveWebhookError("Format Wave-Signature invalide")
        key, value = part.split("=", 1)
        if key == "t":
            timestamp = value
        elif key == "v1":
            signatures.append(value)
    if not timestamp or not signatures:
        raise WaveWebhookError("Wave-Signature incomplète (t= et v1= requis)")
    return timestamp, signatures


def verify_webhook(raw_body: bytes, wave_signature: str) -> dict:
    """Retourne l'événement JSON si la signature est valide, sinon lève WaveWebhookError."""
    if not WEBHOOK_SECRET:
        raise WaveWebhookError("WAVE_WEBHOOK_SECRET non configurée")
    if not wave_signature:
        raise WaveWebhookError("Header Wave-Signature manquant")

    timestamp, signatures = _signatures_from_header(wave_signature)

    if not SKIP_FRESHNESS:
        try:
            ts = int(timestamp)
        except ValueError:
            raise WaveWebhookError("Timestamp invalide")
        now = int(time.time())
        if ts < now - MAX_AGE_SECONDS or ts > now + MAX_FUTURE_SECONDS:
            raise WaveWebhookError("Signature expirée (anti-rejeu)")

    payload = (timestamp + raw_body.decode("utf-8")).encode("utf-8")
    computed = hmac.new(WEBHOOK_SECRET.encode(), payload, hashlib.sha256).hexdigest()

    if not any(hmac.compare_digest(computed, sig) for sig in signatures):
        raise WaveWebhookError("Signature invalide")

    try:
        return json.loads(raw_body)
    except json.JSONDecodeError:
        raise WaveWebhookError("Corps JSON invalide")