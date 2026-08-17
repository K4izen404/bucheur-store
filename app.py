import os
import secrets
from datetime import datetime, timedelta

from flask import (Flask, abort, flash, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from db import (ORDER_STATUS, PAYMENT_STATUS, WAVE_ACCOUNT, execute, init_db,
                query)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXT = {"png", "jpg", "jpeg", "webp", "gif"}

WAVE_LINK_DEFAULT = "https://pay.wave.com/m/M_-ufM0UEnXp2n/c/sn/"


def get_setting(key, default):
    row = query("SELECT value FROM settings WHERE key=?", (key,), one=True)
    return row["value"] if row else default


def wave_link():
    return get_setting("wave_link", WAVE_LINK_DEFAULT)


def om_status():
    return get_setting("om_status", "en_cours")


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "bucheur-store-dev-key-change-me")
app.config["UPLOAD_FOLDER"] = UPLOAD_DIR
os.makedirs(UPLOAD_DIR, exist_ok=True)

init_db()

# ------------------------------------------------------------------ helpers


def cart_count():
    return sum(item["qty"] for item in session.get("cart", {}).values())


@app.context_processor
def inject_globals():
    return {
        "cart_count": cart_count(),
        "wave_link": wave_link(),
        "wave_account": WAVE_ACCOUNT,
        "om_status": om_status(),
    }


def login_required(f):
    from functools import wraps

    @wraps(f)
    def wrapper(*a, **k):
        if not session.get("user_id"):
            flash("Connectez-vous pour continuer.", "warning")
            return redirect(url_for("login", next=request.path))
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


app.jinja_env.filters["money"] = money
app.jinja_env.globals["PAYMENT_STATUS"] = PAYMENT_STATUS
app.jinja_env.globals["ORDER_STATUS"] = ORDER_STATUS


def allowed_file(name):
    return "." in name and name.rsplit(".", 1)[1].lower() in ALLOWED_EXT


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
    flash(f"{p['name']} ajouté au panier.", "success")
    return redirect(request.referrer or url_for("home"))


@app.route("/panier")
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

    user = None
    if session.get("user_id"):
        user = query("SELECT * FROM users WHERE id=?", (session["user_id"],), one=True)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        address = request.form.get("address", "").strip()
        method = request.form.get("payment_method", "")
        note = request.form.get("note", "").strip()

        if not name or not phone:
            flash("Nom et téléphone sont obligatoires.", "error")
            return redirect(url_for("checkout"))
        if method not in ("wave", "om", "cod"):
            flash("Choisissez un moyen de paiement.", "error")
            return redirect(url_for("checkout"))
        if method == "om" and om_status() != "active":
            flash("Orange Money sera disponible très bientôt. Choisissez Wave ou le paiement à la livraison.", "warning")
            return redirect(url_for("checkout"))

        oid = execute(
            """INSERT INTO orders (user_id, customer_name, customer_phone, customer_email,
               address, total, payment_method, note)
               VALUES (?,?,?,?,?,?,?,?)""",
            (session.get("user_id"), name, phone, email, address, total, method, note))
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
    if order["payment_method"] == "cod":
        return redirect(url_for("order_success", oid=oid))
    return render_template("payment.html", order=order)


@app.route("/paiement/wave/<int:oid>")
def payment_wave(oid):
    order = query("SELECT * FROM orders WHERE id=?", (oid,), one=True)
    if not order or order["payment_method"] != "wave":
        abort(404)
    return redirect(wave_link())


@app.route("/paiement/confirmer/<int:oid>", methods=["POST"])
def payment_confirm(oid):
    order = query("SELECT * FROM orders WHERE id=?", (oid,), one=True)
    if not order:
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
        if password != confirm:
            flash("Les mots de passe ne correspondent pas.", "error")
            return redirect(url_for("register"))
        if query("SELECT id FROM users WHERE email=?", (email,), one=True):
            flash("Un compte existe déjà avec cet email.", "error")
            return redirect(url_for("register"))
        uid = execute(
            "INSERT INTO users (name, email, phone, password_hash) VALUES (?,?,?,?)",
            (name, email, phone, generate_password_hash(password)))
        session["user_id"] = uid
        flash(f"Bienvenue {name} ! Votre compte est créé.", "success")
        return redirect(url_for("home"))
    return render_template("auth/register.html")


@app.route("/connexion", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("home"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = query("SELECT * FROM users WHERE email=?", (email,), one=True)
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            flash(f"Bon retour, {user['name']} !", "success")
            return redirect(request.args.get("next") or url_for("home"))
        flash("Email ou mot de passe incorrect.", "error")
    return render_template("auth/login.html")


@app.route("/deconnexion")
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
        user = query("SELECT * FROM users WHERE email=? AND is_admin=1", (email,), one=True)
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            return redirect(url_for("admin_dashboard"))
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
    if f and f.filename and allowed_file(f.filename):
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


@app.route("/admin/clients")
@admin_required
def admin_customers():
    customers = query(
        """SELECT u.id, u.name, u.email, u.phone, u.created_at,
                  COUNT(o.id) orders_count, COALESCE(SUM(CASE WHEN o.payment_status='paid' THEN o.total END),0) spent
           FROM users u LEFT JOIN orders o ON o.user_id = u.id
           WHERE u.is_admin = 0
           GROUP BY u.id ORDER BY spent DESC""")
    return render_template("admin/customers.html", customers=customers)


@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    if request.method == "POST":
        wave = request.form.get("wave_link", "").strip()
        om_status_val = request.form.get("om_status", "en_cours")
        execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('wave_link', ?)", (wave,))
        execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('om_status', ?)", (om_status_val,))
        flash("Paramètres enregistrés.", "success")
    return render_template("admin/settings.html", wave_link=wave_link(), om_status=om_status())


# ---------------------------------------------------------------- seed

def seed():
    conn = __import__("db").get_db()
    if conn.execute("SELECT COUNT(*) c FROM products").fetchone()["c"] > 0:
        conn.close()
        return
    import sqlite3
    admin = conn.execute("SELECT id FROM users WHERE email='admin@bucheur.sn'").fetchone()
    if not admin:
        conn.execute(
            "INSERT INTO users (name, email, phone, password_hash, is_admin) VALUES (?,?,?,?,1)",
            ("Bûcheur", "admin@bucheur.sn", "770000000",
             generate_password_hash("bucheur2026")))
    conn.commit()
    conn.close()


@app.cli.command("seed")
def seed_command():
    seed()
    print("Données de démonstration ajoutées (admin@bucheur.sn / bucheur2026)")


if __name__ == "__main__":
    seed()
    app.run(debug=True, host="0.0.0.0", port=5000)