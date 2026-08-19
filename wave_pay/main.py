"""Microservice FastAPI dédié à Wave Payments.

- POST /checkout      (interne, secret partagé) : crée une session Wave avec le
                       montant LU EN BASE, redirigeable vers wave_launch_url.
- POST /webhook/wave  (public, HTTPS) : vérifie la signature HMAC officielle,
                       contrôle le montant côté serveur puis confirme la commande
                       via la route interne de l'application Flask.
- GET  /health
"""
import os
import sys

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STORE_DIR = os.path.dirname(BASE_DIR)
sys.path.insert(0, STORE_DIR)

from db import execute, query  # noqa: E402
from wave_client import create_checkout_session  # noqa: E402
from webhook_verify import WaveWebhookError, verify_webhook  # noqa: E402

INTERNAL_SECRET = os.environ.get("WAVE_INTERNAL_SECRET", "")
FLASK_INTERNAL_URL = os.environ.get("FLASK_INTERNAL_URL", "http://127.0.0.1:5000")
SUCCESS_URL_BASE = os.environ.get("WAVE_SUCCESS_URL_BASE", "http://127.0.0.1:5000")

app = FastAPI(title="Wave Payments Service", docs_url=None, redoc_url=None)


@app.get("/health")
def health():
    return {"status": "ok"}


def _check_internal_secret(request: Request):
    if not INTERNAL_SECRET or not __import__("hmac").compare_digest(
            request.headers.get("X-Internal-Secret", ""), INTERNAL_SECRET):
        raise HTTPException(status_code=401, detail="Accès refusé")


@app.post("/checkout")
async def create_checkout(request: Request):
    """Crée une session Wave. Le montant vient de la base, jamais du navigateur."""
    _check_internal_secret(request)
    body = await request.json()
    try:
        oid = int(body["order_id"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="order_id invalide")

    order = query("SELECT * FROM orders WHERE id=?", (oid,), one=True)
    if not order:
        raise HTTPException(status_code=404, detail="Commande introuvable")
    if order["payment_method"] != "wave":
        raise HTTPException(status_code=409, detail="Commande non Wave")
    if order["payment_status"] == "paid":
        raise HTTPException(status_code=409, detail="Déjà payée")

    payer = None
    digits = "".join(ch for ch in (order["customer_phone"] or "") if ch.isdigit())
    if digits.startswith("221"):
        digits = digits[3:]
    if len(digits) == 9:
        payer = f"+221{digits}"

    try:
        session = create_checkout_session(
            amount_xof=int(order["total"]),
            client_reference=f"order-{oid}",
            success_url=f"{SUCCESS_URL_BASE}/commande/succes/{oid}",
            error_url=f"{SUCCESS_URL_BASE}/paiement/{oid}",
            restrict_payer_mobile=payer)
    except RuntimeError as exc:
        print(f"[wave] création session échouée #{oid} : {exc}")
        raise HTTPException(status_code=502, detail=str(exc))

    execute("UPDATE orders SET wave_session_id=?, wave_launch_url=? WHERE id=?",
            (session["session_id"], session["wave_launch_url"], oid))
    return session


@app.post("/webhook/wave")
async def wave_webhook(request: Request):
    raw_body = await request.body()
    wave_signature = request.headers.get("Wave-Signature", "")
    try:
        event = verify_webhook(raw_body, wave_signature)
    except WaveWebhookError as exc:
        print(f"[webhook] rejeté : {exc}")
        return JSONResponse(status_code=401, content={"error": str(exc)})

    event_type = event.get("type")
    data = event.get("data") or {}

    if event_type == "checkout.session.completed":
        client_ref = data.get("client_reference") or ""
        if not client_ref.startswith("order-"):
            return JSONResponse(status_code=200, content={"status": "ignored"})
        try:
            oid = int(client_ref.split("-", 1)[1])
        except ValueError:
            return JSONResponse(status_code=200, content={"status": "ignored"})

        import httpx
        try:
            resp = httpx.post(
                f"{FLASK_INTERNAL_URL}/api/paiement/confirme/{oid}",
                json={
                    "amount": data.get("amount"),
                    "currency": data.get("currency"),
                    "transaction_id": data.get("transaction_id"),
                    "session_id": data.get("id"),
                },
                headers={"X-Internal-Secret": INTERNAL_SECRET},
                timeout=15)
        except httpx.HTTPError as exc:
            print(f"[webhook] appel Flask échoué #{oid} : {exc}")
            return JSONResponse(status_code=502, content={"error": "flask unreachable"})
        if resp.status_code >= 300:
            print(f"[webhook] Flask a refusé #{oid} : {resp.status_code} {resp.text[:200]}")
            return JSONResponse(status_code=502, content={"error": "flask refused"})
        return JSONResponse(status_code=200, content={"status": "ok"})

    if event_type == "checkout.session.payment_failed":
        print(f"[webhook] échec de paiement : {data.get('last_payment_error')}")
        return JSONResponse(status_code=200, content={"status": "ok"})

    return JSONResponse(status_code=200, content={"status": "ignored"})