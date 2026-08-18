import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "bucheur.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE,
    phone TEXT,
    password_hash TEXT NOT NULL,
    is_admin INTEGER DEFAULT 0,
    verified INTEGER DEFAULT 0,
    otp_code TEXT,
    otp_expires TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    model TEXT,
    price REAL NOT NULL,
    old_price REAL,
    storage TEXT,
    color TEXT,
    condition TEXT DEFAULT 'Neuf',
    description TEXT,
    image TEXT,
    stock INTEGER DEFAULT 0,
    featured INTEGER DEFAULT 0,
    active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    session_key TEXT,
    customer_name TEXT NOT NULL,
    customer_phone TEXT NOT NULL,
    customer_email TEXT,
    address TEXT,
    total REAL NOT NULL,
    payment_method TEXT NOT NULL,
    payment_status TEXT DEFAULT 'pending',
    order_status TEXT DEFAULT 'pending',
    reference TEXT,
    note TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    product_name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

PAYMENT_STATUS = {
    "pending": "En attente",
    "paid": "Payée",
    "failed": "Échouée",
}

ORDER_STATUS = {
    "pending": "En attente",
    "confirmed": "Confirmée",
    "shipped": "Expédiée",
    "delivered": "Livrée",
    "cancelled": "Annulée",
}

WAVE_ACCOUNT = "Bûcheur études business"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    migrate_users(conn)
    try:
        conn.execute("ALTER TABLE orders ADD COLUMN session_key TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE users ADD COLUMN verified INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE users ADD COLUMN otp_code TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE users ADD COLUMN otp_expires TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone ON users(phone) "
            "WHERE phone IS NOT NULL AND phone != ''")
    except sqlite3.OperationalError:
        pass
    conn.execute("UPDATE users SET verified = 1 WHERE verified IS NULL OR verified = 0 AND otp_code IS NULL")
    conn.commit()
    conn.close()


def migrate_users(conn):
    """Reconstruit users (email optionnel) + orders/order_items (FK réparées).
    Nécessaire car SQLite ne peut pas retirer une contrainte NOT NULL,
    et car le rename de users casse la FK de orders."""
    cols = {r["name"]: r for r in conn.execute("PRAGMA table_info(users)")}
    email = cols.get("email")
    email_notnull = bool(email and email["notnull"])
    orders_sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='orders'").fetchone()
    fk_casse = orders_sql and "users_old" in (orders_sql["sql"] or "")
    if not email_notnull and not fk_casse:
        return
    print("Migration : reconstruction users / orders / order_items (email devient optionnel)")
    if email_notnull:
        conn.execute("ALTER TABLE users RENAME TO users_old")
        conn.execute("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE,
                phone TEXT,
                password_hash TEXT NOT NULL,
                is_admin INTEGER DEFAULT 0,
                verified INTEGER DEFAULT 0,
                otp_code TEXT,
                otp_expires TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute(
            """INSERT INTO users (id, name, email, phone, password_hash, is_admin, verified,
                                  otp_code, otp_expires, created_at)
               SELECT id, name, email, phone, password_hash, is_admin, 1, NULL, NULL, created_at
               FROM users_old""")
        conn.execute("DROP TABLE users_old")

    conn.execute("ALTER TABLE orders RENAME TO orders_old")
    conn.execute("ALTER TABLE order_items RENAME TO order_items_old")
    conn.execute("""
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            session_key TEXT,
            customer_name TEXT NOT NULL,
            customer_phone TEXT NOT NULL,
            customer_email TEXT,
            address TEXT,
            total REAL NOT NULL,
            payment_method TEXT NOT NULL,
            payment_status TEXT DEFAULT 'pending',
            order_status TEXT DEFAULT 'pending',
            reference TEXT,
            note TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.execute("""
        CREATE TABLE order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    """)
    conn.execute("INSERT INTO orders SELECT * FROM orders_old")
    conn.execute("INSERT INTO order_items SELECT * FROM order_items_old")
    conn.execute("DROP TABLE order_items_old")
    conn.execute("DROP TABLE orders_old")


def query(sql, args=(), one=False):
    conn = get_db()
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return (rows[0] if rows else None) if one else rows


def execute(sql, args=()):
    conn = get_db()
    cur = conn.execute(sql, args)
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id