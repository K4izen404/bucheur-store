import os
import re
import secrets
import smtplib
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText

from flask import (Flask, abort, flash, jsonify, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from urllib.parse import urlparse

from db import (ORDER_STATUS, PAYMENT_STATUS, WAVE_ACCOUNT, execute, init_db,
                query)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXT = {"png", "jpg", "jpeg", "webp", "gif"}

WAVE_LINK_DEFAULT = "https://pay.wave.com/m/M_-ufM0UEnXp2n/c/sn/"

LOGIN_ATTEMPTS = {}
MAX_LOGIN_FAILURES = 5
LOCKOUT_SECONDS = 600


def get_setting(key, default):
    row = query("SELECT value FROM settings WHERE key=?", (key,), one=True)
    return row["value"] if row else default


def wave_link():
    return get_setting("wave_link", WAVE_LINK_DEFAULT)


def om_status():
    return get_setting("om_status", "en_cours")


def secret_key():
    env = os.environ.get("SECRET_KEY")
    if env:
        return env
    key = get_setting("secret_key", None)
    if not key:
        key = secrets.token_hex(32)
        execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('secret_key', ?)", (key,))
    return key


app = Flask(__name__)
app.secret_key = secret_key()
app.config["UPLOAD_FOLDER"] = UPLOAD_DIR
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("FORCE_HTTPS") == "1"
os.makedirs(UPLOAD_DIR, exist_ok=True)

init_db()

# ------------------------------------------------------------------ helpers


def cart_count():
    return sum(item["qty"] for item in session.get("cart", {}).values())


def generate_csrf():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(32)
    return session["_csrf"]


@app.context_processor
def inject_globals():
    return {
        "cart_count": cart_count(),
        "wave_link": wave_link(),
        "wave_account": WAVE_ACCOUNT,
        "om_status": om_status(),
        "csrf_token": generate_csrf,
    }


@app.before_request
def csrf_protect():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        token = request.form.get("csrf_token", "")
        if not token or not secrets.compare_digest(token, session.get("_csrf", "")):
            flash("Session expirée, veuillez réessayer.", "error")
            return redirect(request.referrer or url_for("home"))


@app.after_request
def security_headers(resp):
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; frame-ancestors 'none'")
    if request.is_secure:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000"
    return resp


def login_limiter(key):
    now = time.time()
    entry = LOGIN_ATTEMPTS.get(key)
    if entry and entry["count"] >= MAX_LOGIN_FAILURES:
        if now - entry["t0"] < LOCKOUT_SECONDS:
            return False
        del LOGIN_ATTEMPTS[key]
    return True


def login_failure(key):
    now = time.time()
    entry = LOGIN_ATTEMPTS.get(key)
    if not entry or now - entry["t0"] > LOCKOUT_SECONDS:
        LOGIN_ATTEMPTS[key] = {"count": 1, "t0": now}
    else:
        entry["count"] += 1


def login_success(key):
    LOGIN_ATTEMPTS.pop(key, None)


def order_access(order):
    if session.get("user_id") and order["user_id"] == session.get("user_id"):
        return True
    return order["session_key"] and order["session_key"] == session.get("order_session")


# ------------------------------------------------------------------ OTP

OTP_TTL_MINUTES = 10


def normalize_phone(phone):
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("221") and len(digits) > 9:
        digits = digits[3:]
    if len(digits) == 9 and digits[0] in "370757678":
        return digits
    return phone.strip() if phone else ""


def smtp_configured():
    return bool(os.environ.get("SMTP_HOST"))


def otp_dev_mode():
    """Mode développement : affiche le code OTP à l'écran.
    Uniquement si FLASK_ENV=development est explicitement défini (jamais par défaut)."""
    return os.environ.get("FLASK_ENV") == "development" and not smtp_configured()


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


def generate_otp(uid):
    code = f"{secrets.randbelow(1000000):06d}"
    expires = (datetime.now() + timedelta(minutes=OTP_TTL_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
    execute("UPDATE users SET otp_code=?, otp_expires=?, verified=0 WHERE id=?",
            (code, expires, uid))
    return code


def send_otp(user):
    code = generate_otp(user["id"])
    body = f"""Bonjour {user['name']},

Votre code de vérification Bûcheur Études & Business est :

    {code}

Ce code est valable {OTP_TTL_MINUTES} minutes. Si vous n'êtes pas à l'origine de cette demande, ignorez ce message.

— Bûcheur Études & Business
Rufisque & Nord-Foire"""
    return send_email(user["email"], "Votre code de vérification Bûcheur", body), code


def login_required(f):
    from functools import wraps

    @wraps(f)
    def wrapper(*a, **k):
        if not session.get("user_id"):
            flash("Connectez-vous pour continuer.", "warning")
            return redirect(url_for("login", next=request.path))
        return f(*a, **k)

    return wrapper


def verified_required(f):
    """Compte connecté ET vérifié (email confirmé par OTP)."""
    from functools import wraps

    @wraps(f)
    def wrapper(*a, **k):
        is_xhr = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        if not session.get("user_id"):
            if is_xhr:
                return jsonify({"ok": False, "need_login": True}), 401
            flash("Créez un compte ou connectez-vous pour ajouter des articles au panier.", "warning")
            return redirect(url_for("login", next=request.path))
        user = query("SELECT verified FROM users WHERE id=?", (session["user_id"],), one=True)
        if not user or not user["verified"]:
            session.pop("user_id", None)
            if is_xhr:
                return jsonify({"ok": False, "need_login": True}), 401
            flash("Votre compte doit être vérifié (email confirmé) pour continuer.", "warning")
            return redirect(url_for("login"))
        return f(*a, **k)

    return wrapper


def admin_required(f):
    from functools import wraps

    @wraps(f)
    def wrapper(*a, **k):
        if not session.get("user_id"):
            return redirect(url_for("admin_login"))
        user = query("SELECT * FROM users WHERE id=?", (session["user_id"],), one=True)
        if not user or not user["is_admin"]:
            abort(403)
        return f(*a, **k)

    return wrapper


def money(value):
    return f"{value:,.0f} F".replace(",", " ")


def wa_number(value):
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("221") and len(digits) > 9:
        digits = digits[3:]
    if len(digits) == 9:
        return digits
    return digits[-9:] if len(digits) > 9 else digits


app.jinja_env.filters["money"] = money
app.jinja_env.filters["wa_number"] = wa_number
app.jinja_env.globals["PAYMENT_STATUS"] = PAYMENT_STATUS
app.jinja_env.globals["ORDER_STATUS"] = ORDER_STATUS


def allowed_file(name):
    return "." in name and name.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def is_real_image(f):
    try:
        from PIL import Image
        f.seek(0)
        img = Image.open(f)
        img.verify()
        f.seek(0)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- client


@app.route("/")
def home():
    featured = query(
        "SELECT * FROM products WHERE active=1 AND featured=1 ORDER BY id DESC LIMIT 4")
    latest = query(
        "SELECT * FROM products WHERE active=1 ORDER BY id DESC LIMIT 8")
    return render_template("index.html", featured=featured, latest=latest)


@app.route("/catalogue")
def catalog():
    cond = []
    args = []
    sql = "SELECT * FROM products WHERE active=1"

    search = request.args.get("q", "").strip()
    if search:
        cond.append("(name LIKE ? OR model LIKE ? OR description LIKE ?)")
        args += [f"%{search}%"] * 3

    model = request.args.get("model", "").strip()
    if model:
        cond.append("model = ?")
        args.append(model)

    color = request.args.get("color", "").strip()
    if color:
        cond.append("color = ?")
        args.append(color)

    storage = request.args.get("storage", "").strip()
    if storage:
        cond.append("storage = ?")
        args.append(storage)

    etat = request.args.get("condition", "").strip()
    if etat:
        cond.append("condition = ?")
        args.append(etat)

    sort = request.args.get("sort", "recent")
    order_map = {
        "recent": "id DESC",
        "price_asc": "price ASC",
        "price_desc": "price DESC",
        "name": "name ASC",
    }
    if cond:
        sql += " AND " + " AND ".join(cond)
    sql += f" ORDER BY {order_map.get(sort, 'id DESC')}"

    products = query(sql, args)
    models = query("SELECT DISTINCT model FROM products WHERE active=1 AND model != ''")
    colors = query("SELECT DISTINCT color FROM products WHERE active=1 AND color != ''")
    storages = query("SELECT DISTINCT storage FROM products WHERE active=1 AND storage != ''")
    conditions = query("SELECT DISTINCT condition FROM products WHERE active=1 AND condition != ''")

    return render_template("catalog.html", products=products, models=models,
                           colors=colors, storages=storages, conditions=conditions,
                           filters=request.args)


@app.route("/produit/<int:pid>")
def product(pid):
    p = query("SELECT * FROM products WHERE id=? AND active=1", (pid,), one=True)
    if not p:
        abort(404)
    related = query(
        "SELECT * FROM products WHERE active=1 AND id != ? AND model = ? LIMIT 4",
        (pid, p["model"] or p["name"]))
    if not related:
        related = query("SELECT * FROM products WHERE active=1 AND id != ? LIMIT 4", (pid,))
    return render_template("product.html", p=p, related=related)


# ---------------------------------------------------------------- panier


@app.route("/panier/ajouter/<int:pid>", methods=["POST"])
@verified_required
def cart_add(pid):
    p = query("SELECT * FROM products WHERE id=? AND active=1", (pid,), one=True)
    if not p:
        abort(404)
    qty = max(1, int(request.form.get("qty", 1)))
    qty = min(qty, max(p["stock"], 1))
    cart = session.get("cart", {})
    key = str(pid)
    if key in cart:
        cart[key]["qty"] = min(cart[key]["qty"] + qty, max(p["stock"], 1))
    else:
        cart[key] = {"qty": qty, "price": p["price"]}
    session["cart"] = cart
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "count": cart_count(), "name": p["name"]})
    flash(f"{p['name']} ajouté au panier.", "success")
    return redirect(request.referrer or url_for("home"))


@app.route("/panier")
@verified_required
def cart():
    cart = session.get("cart", {})
    items = []
    total = 0
    for key, item in cart.items():
        p = query("SELECT * FROM products WHERE id=?", (key,), one=True)
        if not p or not p["active"]:
            continue
        subtotal = p["price"] * item["qty"]
        total += subtotal
        items.append({"product": p, "qty": item["qty"], "subtotal": subtotal})
    return render_template("cart.html", items=items, total=total)


@app.route("/panier/modifier/<int:pid>", methods=["POST"])
@verified_required
def cart_update(pid):
    cart = session.get("cart", {})
    qty = max(0, int(request.form.get("qty", 0)))
    if str(pid) in cart:
        if qty == 0:
            del cart[str(pid)]
        else:
            p = query("SELECT * FROM products WHERE id=?", (pid,), one=True)
            cart[str(pid)]["qty"] = min(qty, max(p["stock"], 1)) if p else qty
    session["cart"] = cart
    return redirect(url_for("cart"))


# ---------------------------------------------------------------- commande


@app.route("/commande", methods=["GET", "POST"])
@verified_required
def checkout():
    cart = session.get("cart", {})
    if not cart:
        flash("Votre panier est vide.", "warning")
        return redirect(url_for("cart"))

    items = []
    total = 0
    for key, item in cart.items():
        p = query("SELECT * FROM products WHERE id=?", (key,), one=True)
        if not p or not p["active"]:
            continue
        subtotal = p["price"] * item["qty"]
        total += subtotal
        items.append({"product": p, "qty": item["qty"], "subtotal": subtotal})

    user = query("SELECT * FROM users WHERE id=?", (session["user_id"],), one=True)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = normalize_phone(request.form.get("phone", "").strip())
        email = request.form.get("email", "").strip()
        address = request.form.get("address", "").strip()
        method = request.form.get("payment_method", "")
        note = request.form.get("note", "").strip()

        if not name:
            flash("Le nom est obligatoire.", "error")
            return redirect(url_for("checkout"))
        if not phone or len(re.sub(r"\D", "", phone)) != 9:
            flash("Numéro de téléphone invalide. Format sénégalais attendu (ex : 77 123 45 67).", "error")
            return redirect(url_for("checkout"))
        if method not in ("wave", "om", "cod"):
            flash("Choisissez un moyen de paiement.", "error")
            return redirect(url_for("checkout"))
        if method == "om" and om_status() != "active":
            flash("Orange Money sera disponible très bientôt. Choisissez Wave ou le paiement à la livraison.", "warning")
            return redirect(url_for("checkout"))

        if not session.get("order_session"):
            session["order_session"] = secrets.token_hex(16)
        oid = execute(
            """INSERT INTO orders (user_id, session_key, customer_name, customer_phone, customer_email,
               address, total, payment_method, note)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (session.get("user_id"), session["order_session"], name, phone, email, address,
             total, method, note))
        for it in items:
            execute(
                """INSERT INTO order_items (order_id, product_id, product_name, quantity, price)
                   VALUES (?,?,?,?,?)""",
                (oid, it["product"]["id"], it["product"]["name"], it["qty"], it["product"]["price"]))
            execute("UPDATE products SET stock = stock - ? WHERE id=?",
                    (it["qty"], it["product"]["id"]))
        session["cart"] = {}
        session["last_order"] = oid

        if method == "wave":
            return redirect(url_for("payment", oid=oid))
        if method == "om":
            return redirect(url_for("payment", oid=oid))
        return redirect(url_for("order_success", oid=oid))

    return render_template("checkout.html", items=items, total=total, user=user)


@app.route("/paiement/<int:oid>")
def payment(oid):
    order = query("SELECT * FROM orders WHERE id=?", (oid,), one=True)
    if not order:
        abort(404)
    if not order_access(order):
        abort(404)
    if order["payment_method"] == "cod":
        return redirect(url_for("order_success", oid=oid))
    return render_template("payment.html", order=order)


@app.route("/paiement/wave/<int:oid>")
def payment_wave(oid):
    order = query("SELECT * FROM orders WHERE id=?", (oid,), one=True)
    if not order or order["payment_method"] != "wave":
        abort(404)
    if not order_access(order):
        abort(404)
    return redirect(wave_link())


@app.route("/paiement/confirmer/<int:oid>", methods=["POST"])
def payment_confirm(oid):
    order = query("SELECT * FROM orders WHERE id=?", (oid,), one=True)
    if not order:
        abort(404)
    if not order_access(order):
        abort(404)
    ref = request.form.get("reference", "").strip()
    if not ref:
        flash("Veuillez saisir la référence de votre paiement.", "error")
        return redirect(url_for("payment", oid=oid))
    execute("UPDATE orders SET reference=?, payment_status='paid' WHERE id=?",
            (ref, oid))
    flash("Paiement enregistré ! Nous vérifions votre transaction, votre commande sera confirmée sous peu.", "success")
    return redirect(url_for("order_success", oid=oid))


@app.route("/commande/succes/<int:oid>")
def order_success(oid):
    order = query("SELECT * FROM orders WHERE id=?", (oid,), one=True)
    if not order:
        abort(404)
    if not order_access(order):
        abort(404)
    items = query("SELECT * FROM order_items WHERE order_id=?", (oid,))
    return render_template("order_success.html", order=order, items=items)


# ---------------------------------------------------------------- comptes


@app.route("/inscription", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("account"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        if not name or not email or not password:
            flash("Tous les champs sont obligatoires.", "error")
            return redirect(url_for("register"))
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            flash("Adresse email invalide.", "error")
            return redirect(url_for("register"))
        phone = normalize_phone(phone)
        if not phone or len(re.sub(r"\D", "", phone)) != 9:
            flash("Numéro de téléphone invalide. Format sénégalais attendu (ex : 77 123 45 67).", "error")
            return redirect(url_for("register"))
        if password != confirm:
            flash("Les mots de passe ne correspondent pas.", "error")
            return redirect(url_for("register"))
        if len(password) < 6:
            flash("Le mot de passe doit faire au moins 6 caractères.", "error")
            return redirect(url_for("register"))
        if query("SELECT id FROM users WHERE email=?", (email,), one=True):
            flash("Un compte existe déjà avec cet email.", "error")
            return redirect(url_for("register"))
        if not smtp_configured() and not otp_dev_mode():
            flash("Le service d'inscription est temporairement indisponible. Contactez l'administration : +221 77 757 27 76.", "error")
            return redirect(url_for("register"))

        uid = execute(
            "INSERT INTO users (name, email, phone, password_hash, verified) VALUES (?,?,?,?,0)",
            (name, email, phone, generate_password_hash(password)))
        user = query("SELECT * FROM users WHERE id=?", (uid,), one=True)
        delivered, code = send_otp(user)
        session["pending_otp"] = uid
        if not delivered and not otp_dev_mode():
            execute("DELETE FROM users WHERE id=?", (uid,))
            flash("Impossible d'envoyer le code de vérification. Vérifiez la configuration email du site, ou contactez l'administration : +221 77 757 27 76.", "error")
            return redirect(url_for("register"))
        flash("Vérifiez votre boîte mail : un code de confirmation vous a été envoyé.", "info")
        return render_template("auth/otp.html", user=user, dev_code=code if otp_dev_mode() else None)

    return render_template("auth/register.html")


@app.route("/verification", methods=["POST"])
def otp_verify():
    uid = session.get("pending_otp")
    if not uid:
        flash("Veuillez d'abord créer votre compte.", "warning")
        return redirect(url_for("register"))
    user = query("SELECT * FROM users WHERE id=?", (uid,), one=True)
    if not user:
        session.pop("pending_otp", None)
        return redirect(url_for("register"))
    code = request.form.get("otp", "").strip()
    expires = datetime.strptime(user["otp_expires"], "%Y-%m-%d %H:%M:%S") if user["otp_expires"] else None
    if not code or code != user["otp_code"]:
        flash("Code incorrect. Vérifiez le code reçu.", "error")
        return render_template("auth/otp.html", user=user, dev_code=None)
    if not expires or expires < datetime.now():
        flash("Ce code a expiré. Demandez-en un nouveau.", "error")
        return render_template("auth/otp.html", user=user, dev_code=None)
    execute("UPDATE users SET verified=1, otp_code=NULL, otp_expires=NULL WHERE id=?", (uid,))
    session.pop("pending_otp", None)
    session["user_id"] = uid
    flash(f"Compte vérifié. Bienvenue {user['name']} !", "success")
    return redirect(url_for("account"))


@app.route("/verification/renvoyer", methods=["POST"])
def otp_resend():
    uid = session.get("pending_otp")
    if not uid:
        return redirect(url_for("register"))
    user = query("SELECT * FROM users WHERE id=?", (uid,), one=True)
    if not user:
        return redirect(url_for("register"))
    if not smtp_configured() and not otp_dev_mode():
        flash("Le service d'envoi est indisponible. Contactez l'administration : +221 77 757 27 76.", "error")
        return redirect(url_for("register"))
    delivered, code = send_otp(user)
    if not delivered and not otp_dev_mode():
        flash("Impossible d'envoyer le code. Réessayez dans quelques instants.", "error")
        return render_template("auth/otp.html", user=user, dev_code=None)
    flash("Un nouveau code vient d'être envoyé par email.", "info")
    return render_template("auth/otp.html", user=user, dev_code=code if otp_dev_mode() else None)


@app.route("/connexion", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("home"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        key = f"{email}|{request.remote_addr}"
        if not login_limiter(key):
            flash("Trop de tentatives. Réessayez dans 10 minutes.", "error")
            return redirect(url_for("login"))
        user = query("SELECT * FROM users WHERE email=?", (email,), one=True)
        if user and user["verified"] and check_password_hash(user["password_hash"], password):
            login_success(key)
            session["user_id"] = user["id"]
            flash(f"Bon retour, {user['name']} !", "success")
            nxt = request.args.get("next") or url_for("home")
            if not nxt.startswith("/") or nxt.startswith("//"):
                nxt = url_for("home")
            return redirect(nxt)
        login_failure(key)
        flash("Email ou mot de passe incorrect.", "error")
    return render_template("auth/login.html")


@app.route("/deconnexion", methods=["POST"])
def logout():
    session.clear()
    flash("Vous êtes déconnecté.", "info")
    return redirect(url_for("home"))


@app.route("/compte")
@login_required
def account():
    user = query("SELECT * FROM users WHERE id=?", (session["user_id"],), one=True)
    orders = query(
        "SELECT * FROM orders WHERE user_id=? ORDER BY id DESC", (user["id"],))
    return render_template("account.html", user=user, orders=orders)


# ---------------------------------------------------------------- admin


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        key = f"admin|{request.remote_addr}"
        if not login_limiter(key):
            flash("Trop de tentatives. Réessayez dans 10 minutes.", "error")
            return redirect(url_for("admin_login"))
        user = query("SELECT * FROM users WHERE email=? AND is_admin=1", (email,), one=True)
        if user and check_password_hash(user["password_hash"], password):
            login_success(key)
            session["user_id"] = user["id"]
            return redirect(url_for("admin_dashboard"))
        login_failure(key)
        flash("Identifiants administrateur incorrects.", "error")
    return render_template("admin/login.html")


@app.route("/admin")
@admin_required
def admin_dashboard():
    today = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    total_revenue = query(
        "SELECT COALESCE(SUM(total),0) t FROM orders WHERE payment_status='paid'", one=True)["t"]
    today_revenue = query(
        "SELECT COALESCE(SUM(total),0) t FROM orders WHERE payment_status='paid' AND date(created_at)=?",
        (today,), one=True)["t"]
    week_revenue = query(
        "SELECT COALESCE(SUM(total),0) t FROM orders WHERE payment_status='paid' AND date(created_at)>=?",
        (week_ago,), one=True)["t"]

    orders_count = query("SELECT COUNT(*) c FROM orders", one=True)["c"]
    pending_count = query(
        "SELECT COUNT(*) c FROM orders WHERE payment_status='pending'", one=True)["c"]
    low_stock = query("SELECT COUNT(*) c FROM products WHERE stock <= 3", one=True)["c"]

    by_method = query(
        """SELECT payment_method, COUNT(*) c, COALESCE(SUM(total),0) t
           FROM orders WHERE payment_status='paid' GROUP BY payment_method""")
    wave_total = sum(r["t"] for r in by_method if r["payment_method"] == "wave")
    om_total = sum(r["t"] for r in by_method if r["payment_method"] == "om")

    best_sellers = query(
        """SELECT product_name, SUM(quantity) q, SUM(quantity*price) t
           FROM order_items GROUP BY product_name ORDER BY q DESC LIMIT 5""")

    recent_orders = query("SELECT * FROM orders ORDER BY id DESC LIMIT 6")

    last7 = []
    for i in range(6, -1, -1):
        day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        rev = query(
            "SELECT COALESCE(SUM(total),0) t FROM orders WHERE payment_status='paid' AND date(created_at)=?",
            (day,), one=True)["t"]
        last7.append({"day": day[5:], "total": rev})

    return render_template("admin/dashboard.html",
                           total_revenue=total_revenue, today_revenue=today_revenue,
                           week_revenue=week_revenue, orders_count=orders_count,
                           pending_count=pending_count, low_stock=low_stock,
                           wave_total=wave_total, om_total=om_total,
                           best_sellers=best_sellers, recent_orders=recent_orders,
                           last7=last7)


@app.route("/admin/produits")
@admin_required
def admin_products():
    products = query("SELECT * FROM products ORDER BY id DESC")
    return render_template("admin/products.html", products=products)


@app.route("/admin/produits/ajouter", methods=["GET", "POST"])
@admin_required
def admin_product_add():
    if request.method == "POST":
        return _save_product()
    return render_template("admin/product_form.html", p=None)


@app.route("/admin/produits/<int:pid>/modifier", methods=["GET", "POST"])
@admin_required
def admin_product_edit(pid):
    p = query("SELECT * FROM products WHERE id=?", (pid,), one=True)
    if not p:
        abort(404)
    if request.method == "POST":
        return _save_product(p)
    return render_template("admin/product_form.html", p=p)


def _save_product(p=None):
    name = request.form.get("name", "").strip()
    if not name:
        flash("Le nom du produit est obligatoire.", "error")
        return redirect(request.referrer or url_for("admin_products"))
    data = dict(
        name=name,
        model=request.form.get("model", "").strip(),
        price=float(request.form.get("price", 0) or 0),
        old_price=float(request.form.get("old_price", 0) or 0) or None,
        storage=request.form.get("storage", "").strip(),
        color=request.form.get("color", "").strip(),
        condition=request.form.get("condition", "Neuf"),
        description=request.form.get("description", "").strip(),
        stock=int(request.form.get("stock", 0) or 0),
        featured=1 if request.form.get("featured") else 0,
        active=1 if request.form.get("active") else 0,
    )
    image = p["image"] if p else None
    f = request.files.get("image")
    if f and f.filename:
        if not (allowed_file(f.filename) and is_real_image(f)):
            flash("Image invalide : le fichier n'est pas une vraie image.", "error")
            return redirect(request.referrer or url_for("admin_products"))
        fn = secure_filename(f.filename)
        image = f"uploads/{secrets.token_hex(4)}_{fn}"
        f.save(os.path.join(UPLOAD_DIR, os.path.basename(image)))
    data["image"] = image

    if p:
        execute(
            """UPDATE products SET name=?, model=?, price=?, old_price=?, storage=?,
               color=?, condition=?, description=?, stock=?, featured=?, active=?, image=?
               WHERE id=?""",
            (data["name"], data["model"], data["price"], data["old_price"], data["storage"],
             data["color"], data["condition"], data["description"], data["stock"],
             data["featured"], data["active"], data["image"], p["id"]))
        flash("Produit mis à jour.", "success")
    else:
        execute(
            """INSERT INTO products (name, model, price, old_price, storage, color,
               condition, description, stock, featured, active, image)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (data["name"], data["model"], data["price"], data["old_price"], data["storage"],
             data["color"], data["condition"], data["description"], data["stock"],
             data["featured"], data["active"], data["image"]))
        flash("Produit ajouté au catalogue.", "success")
    return redirect(url_for("admin_products"))


@app.route("/admin/produits/<int:pid>/supprimer", methods=["POST"])
@admin_required
def admin_product_delete(pid):
    execute("DELETE FROM products WHERE id=?", (pid,))
    flash("Produit supprimé.", "info")
    return redirect(url_for("admin_products"))


@app.route("/admin/commandes")
@admin_required
def admin_orders():
    status = request.args.get("status", "")
    payment = request.args.get("payment", "")
    sql = "SELECT * FROM orders WHERE 1=1"
    args = []
    if status in ORDER_STATUS:
        sql += " AND order_status=?"
        args.append(status)
    if payment in PAYMENT_STATUS:
        sql += " AND payment_status=?"
        args.append(payment)
    sql += " ORDER BY id DESC"
    orders = query(sql, args)
    return render_template("admin/orders.html", orders=orders, cur_status=status,
                           cur_payment=payment)


@app.route("/admin/commandes/<int:oid>")
@admin_required
def admin_order_detail(oid):
    order = query("SELECT * FROM orders WHERE id=?", (oid,), one=True)
    if not order:
        abort(404)
    items = query("SELECT * FROM order_items WHERE order_id=?", (oid,))
    return render_template("admin/order_detail.html", order=order, items=items)


@app.route("/admin/commandes/<int:oid>/statut", methods=["POST"])
@admin_required
def admin_order_status(oid):
    status = request.form.get("order_status")
    payment = request.form.get("payment_status")
    if status in ORDER_STATUS:
        execute("UPDATE orders SET order_status=? WHERE id=?", (status, oid))
    if payment in PAYMENT_STATUS:
        execute("UPDATE orders SET payment_status=? WHERE id=?", (payment, oid))
    flash("Statut de la commande mis à jour.", "success")
    return redirect(url_for("admin_order_detail", oid=oid))


@app.route("/admin/utilisateurs")
@admin_required
def admin_users():
    users = query(
        """SELECT u.id, u.name, u.email, u.phone, u.is_admin, u.verified, u.created_at,
                  COUNT(o.id) orders_count,
                  COALESCE(SUM(CASE WHEN o.payment_status='paid' THEN o.total END),0) spent
           FROM users u LEFT JOIN orders o ON o.user_id = u.id
           GROUP BY u.id ORDER BY u.is_admin DESC, u.created_at DESC""")
    return render_template("admin/users.html", users=users)


@app.route("/admin/utilisateurs/ajouter", methods=["POST"])
@admin_required
def admin_user_add():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "").strip() or None
    password = request.form.get("password", "")
    is_admin = 1 if request.form.get("is_admin") else 0

    if not name or not email or not password or len(password) < 6:
        flash("Nom, email et mot de passe (min. 6 caractères) obligatoires.", "error")
        return redirect(url_for("admin_users"))
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        flash("Adresse email invalide.", "error")
        return redirect(url_for("admin_users"))
    if query("SELECT id FROM users WHERE email=?", (email,), one=True):
        flash("Cet email est déjà utilisé.", "error")
        return redirect(url_for("admin_users"))
    if phone:
        phone = normalize_phone(phone)
        if query("SELECT id FROM users WHERE phone=?", (phone,), one=True):
            flash("Ce téléphone est déjà utilisé.", "error")
            return redirect(url_for("admin_users"))
    execute("INSERT INTO users (name, email, phone, password_hash, is_admin, verified) VALUES (?,?,?,?,?,1)",
            (name, email, phone, generate_password_hash(password), is_admin))
    flash(f"Utilisateur « {name} » créé.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/utilisateurs/<int:uid>/modifier", methods=["POST"])
@admin_required
def admin_user_edit(uid):
    user = query("SELECT * FROM users WHERE id=?", (uid,), one=True)
    if not user:
        abort(404)
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "").strip() or None
    is_admin = 1 if request.form.get("is_admin") else 0
    new_password = request.form.get("new_password", "")

    if not name or not email:
        flash("Le nom et l'email sont obligatoires.", "error")
        return redirect(url_for("admin_users"))
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        flash("Adresse email invalide.", "error")
        return redirect(url_for("admin_users"))
    if query("SELECT id FROM users WHERE email=? AND id != ?", (email, uid), one=True):
        flash("Cet email est déjà utilisé par un autre compte.", "error")
        return redirect(url_for("admin_users"))
    if phone:
        phone = normalize_phone(phone)
        if query("SELECT id FROM users WHERE phone=? AND id != ?", (phone, uid), one=True):
            flash("Ce téléphone est déjà utilisé par un autre compte.", "error")
            return redirect(url_for("admin_users"))
    if user["is_admin"] and not is_admin and query(
            "SELECT COUNT(*) c FROM users WHERE is_admin=1", one=True)["c"] <= 1:
        flash("Impossible de retirer le rôle admin : c'est le dernier administrateur.", "error")
        return redirect(url_for("admin_users"))

    if new_password:
        if len(new_password) < 6:
            flash("Le nouveau mot de passe doit faire au moins 6 caractères.", "error")
            return redirect(url_for("admin_users"))
        execute("UPDATE users SET name=?, email=?, phone=?, is_admin=?, password_hash=? WHERE id=?",
                (name, email, phone, is_admin, generate_password_hash(new_password), uid))
        flash("Utilisateur modifié (mot de passe changé).", "success")
    else:
        execute("UPDATE users SET name=?, email=?, phone=?, is_admin=? WHERE id=?",
                (name, email, phone, is_admin, uid))
        flash("Utilisateur modifié.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/utilisateurs/<int:uid>/supprimer", methods=["POST"])
@admin_required
def admin_user_delete(uid):
    user = query("SELECT * FROM users WHERE id=?", (uid,), one=True)
    if not user:
        abort(404)
    if uid == session["user_id"]:
        flash("Vous ne pouvez pas supprimer votre propre compte.", "error")
        return redirect(url_for("admin_users"))
    if user["is_admin"] and query(
            "SELECT COUNT(*) c FROM users WHERE is_admin=1", one=True)["c"] <= 1:
        flash("Impossible de supprimer le dernier administrateur.", "error")
        return redirect(url_for("admin_users"))
    execute("UPDATE orders SET user_id=NULL WHERE user_id=?", (uid,))
    execute("DELETE FROM users WHERE id=?", (uid,))
    flash(f"Utilisateur « {user['name']} » supprimé.", "info")
    return redirect(url_for("admin_users"))


@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    if request.method == "POST":
        wave = request.form.get("wave_link", "").strip()
        om_status_val = request.form.get("om_status", "en_cours")
        execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('wave_link', ?)", (wave,))
        execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('om_status', ?)", (om_status_val,))

        old_pw = request.form.get("old_password", "")
        new_pw = request.form.get("new_password", "")
        if old_pw or new_pw:
            user = query("SELECT * FROM users WHERE id=?", (session["user_id"],), one=True)
            if len(new_pw) < 8:
                flash("Le nouveau mot de passe doit faire au moins 8 caractères.", "error")
                return redirect(url_for("admin_settings"))
            if not user or not check_password_hash(user["password_hash"], old_pw):
                flash("Ancien mot de passe incorrect.", "error")
                return redirect(url_for("admin_settings"))
            execute("UPDATE users SET password_hash=? WHERE id=?",
                    (generate_password_hash(new_pw), user["id"]))
            flash("Mot de passe changé avec succès.", "success")
        else:
            flash("Paramètres enregistrés.", "success")
    return render_template("admin/settings.html", wave_link=wave_link(), om_status=om_status())


# ---------------------------------------------------------------- seed

def seed():
    conn = __import__("db").get_db()
    if conn.execute("SELECT COUNT(*) c FROM products").fetchone()["c"] > 0:
        conn.close()
        return
    admin = conn.execute("SELECT id FROM users WHERE email='admin@bucheur.sn'").fetchone()
    if not admin:
        admin_pw = os.environ.get("ADMIN_PASSWORD") or secrets.token_urlsafe(10)
        conn.execute(
            "INSERT INTO users (name, email, phone, password_hash, is_admin) VALUES (?,?,?,?,1)",
            ("Bûcheur", "admin@bucheur.sn", "770000000",
             generate_password_hash(admin_pw)))
        print(f"Compte admin créé : admin@bucheur.sn / {admin_pw}")
        print("(changez ce mot de passe dans Admin → Réglages)")
    conn.commit()
    conn.close()


@app.cli.command("seed")
def seed_command():
    seed()
    print("Données de démonstration ajoutées (admin@bucheur.sn / bucheur2026)")


if __name__ == "__main__":
    seed()
    app.run(debug=True, host="0.0.0.0", port=5000)