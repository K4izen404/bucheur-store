import os
import smtplib
from datetime import datetime
from email.mime.text import MIMEText

from db import ORDER_STATUS


def smtp_configured():
    return bool(os.environ.get("SMTP_HOST"))


def send_email(to_addr, subject, body):
    host = os.environ.get("SMTP_HOST")
    if not host:
        return False
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    sender = os.environ.get("SMTP_FROM", user)
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_addr
    try:
        with smtplib.SMTP(host, port, timeout=10) as s:
            if port == 587 or port == 25:
                s.starttls()
            if user:
                s.login(user, password)
            s.sendmail(sender, [to_addr], msg.as_string())
        return True
    except Exception:
        return False


def _notify_new_order(oid, name, phone, email, address, method, note, items, total):
    """Email à l'admin + accusé de réception client (résilient : n'empêche jamais la commande)."""
    lines = [f"Nouvelle commande #{oid} — {name}",
             "", f"Client : {name}", f"Téléphone : +221 {phone}",
             f"Email : {email}", f"Adresse de livraison : {address or '—'}",
             "", "Articles :"]
    for it in items:
        lines.append(f"  - {it['product']['name']} x{it['qty']} — {it['product']['price']} FCFA")
    lines += ["", f"Total : {total} FCFA",
              f"Moyen de paiement : {'Wave' if method == 'wave' else ('Orange Money' if method == 'om' else 'À la livraison')}",
              f"Note du client : {note or '—'}",
              f"Date : {datetime.now().strftime('%d/%m/%Y %H:%M')}"]
    admin_to = os.environ.get("ADMIN_NOTIFY_EMAIL") or os.environ.get("SMTP_FROM", "")
    if admin_to:
        try:
            send_email(admin_to, f"Nouvelle commande #{oid} — {name}", "\n".join(lines))
        except Exception:
            print(f"[email] échec notification admin commande #{oid}")

    payment_label = {"wave": "en attente de paiement",
                     "om": "en attente de paiement",
                     "cod": "paiement à la livraison"}.get(method, "en attente")
    client_body = f"""Bonjour {name},

Merci pour votre commande sur Bûcheur Études & Business !

Commande #{oid} — récapitulatif :
"""
    for it in items:
        client_body += f"  • {it['product']['name']} x{it['qty']} — {it['product']['price']} FCFA\n"
    client_body += f"""
Total : {total} FCFA
Paiement : {payment_label}
Adresse de livraison : {address or 'à confirmer'}

Votre commande est bien enregistrée. Nous vous recontacterons au besoin sur votre téléphone ({phone}).

— Bûcheur Études & Business
Rufisque & Nord-Foire"""
    if email:
        try:
            send_email(email, f"Confirmation de votre commande #{oid} — Bûcheur Études & Business", client_body)
        except Exception:
            print(f"[email] échec confirmation client commande #{oid}")


def _notify_order_update(order, new_status=None, new_date=None, new_payment=None):
    """Email client lors d'un changement de statut, de date ou de paiement (résilient)."""
    if not order["customer_email"]:
        return
    parts = [f"Bonjour {order['customer_name']},"]
    if new_status:
        parts.append(f"Votre commande #{order['id']} est maintenant : {ORDER_STATUS.get(new_status, new_status)}.")
    if new_date:
        try:
            d = datetime.strptime(new_date, "%Y-%m-%d")
            pretty = d.strftime("%A %d %B %Y").capitalize()
        except ValueError:
            pretty = new_date
        parts.append(f"Livraison prévue : {pretty}.")
    if new_payment == "paid":
        parts.append(
            f"Votre paiement de {order['total']:,.0f} FCFA pour la commande #{order['id']} "
            "a été confirmé. Merci !")
    parts.append("")
    parts.append("Merci de votre confiance.")
    parts.append("— Bûcheur Études & Business")
    parts.append("Rufisque & Nord-Foire")
    try:
        send_email(order["customer_email"], f"Mise à jour de votre commande #{order['id']}", "\n".join(parts))
    except Exception:
        print(f"[email] échec notification mise à jour commande #{order['id']}")


def _notify_payment_to_admin(order):
    """Email à l'admin quand un client déclare un paiement Wave : à vérifier sur le
    compte Wave du marchand puis à valider manuellement (résilient)."""
    admin_to = os.environ.get("ADMIN_NOTIFY_EMAIL") or os.environ.get("SMTP_FROM", "")
    if not admin_to:
        return
    method_label = "Wave" if order["payment_method"] == "wave" else "Orange Money"
    ref = order["reference"] or "—"
    try:
        send_email(
            admin_to,
            f"Paiement {method_label} à vérifier — commande #{order['id']}",
            f"Le client {order['customer_name']} ({order['customer_phone']}) déclare avoir payé "
            f"{order['total']:,.0f} FCFA par {method_label}.\n"
            f"Référence de transaction : {ref}\n"
            "Vérifiez la réception sur votre compte, puis validez le paiement "
            "dans l'administration (Commandes → statut paiement = Payé).")
    except Exception:
        print(f"[email] échec notification admin paiement #{order['id']}")