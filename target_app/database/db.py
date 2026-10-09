"""Data access for the login app. See agents/shared_context/test-contract.md, section 1.

Every function takes the SQLite file path first and opens its own connection.
Passwords are stored only as salted PBKDF2-SHA256 hashes (NFR-1) and are never
logged or returned.
"""

import hashlib
import hmac
import secrets
import sqlite3

DEMO_EMAIL = "user@example.com"
DEMO_PASSWORD = "green apple house"

HASH_SCHEME = "pbkdf2_sha256"
HASH_ITERATIONS = 600_000
SALT_BYTES = 16

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL
)
"""

# Hashed once on first use, so authenticate spends the same work on an
# unknown email as on a wrong password.
_dummy_hash = None


def _connect(db_path):
    return sqlite3.connect(db_path)


def _normalize_email(email):
    return email.strip().lower()


def _row_to_user(row):
    if row is None:
        return None
    return {"id": row[0], "email": row[1], "password_hash": row[2]}


def _pbkdf2(password, salt, iterations):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def hash_password(password):
    salt = secrets.token_bytes(SALT_BYTES)
    digest = _pbkdf2(password, salt, HASH_ITERATIONS)
    return f"{HASH_SCHEME}${HASH_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password, stored_hash):
    try:
        scheme, iterations, salt_hex, hash_hex = stored_hash.split("$")
        if scheme != HASH_SCHEME:
            return False
        expected = bytes.fromhex(hash_hex)
        digest = _pbkdf2(password, bytes.fromhex(salt_hex), int(iterations))
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(digest, expected)


def init_db(db_path):
    con = _connect(db_path)
    try:
        with con:
            con.execute(_SCHEMA)
    finally:
        con.close()
    if get_user_by_email(db_path, DEMO_EMAIL) is None:
        try:
            create_user(db_path, DEMO_EMAIL, DEMO_PASSWORD)
        except ValueError:
            pass  # another process seeded it first


def create_user(db_path, email, password):
    email = _normalize_email(email)
    password_hash = hash_password(password)
    con = _connect(db_path)
    try:
        with con:
            cur = con.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (email, password_hash),
            )
        return cur.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError("a user with this email already exists") from None
    finally:
        con.close()


def get_user_by_email(db_path, email):
    con = _connect(db_path)
    try:
        row = con.execute(
            "SELECT id, email, password_hash FROM users WHERE email = ?",
            (_normalize_email(email),),
        ).fetchone()
    finally:
        con.close()
    return _row_to_user(row)


def authenticate(db_path, email, password):
    global _dummy_hash
    user = get_user_by_email(db_path, email)
    if user is None:
        if _dummy_hash is None:
            _dummy_hash = hash_password(secrets.token_urlsafe(16))
        verify_password(password, _dummy_hash)
        return None
    if verify_password(password, user["password_hash"]):
        return user
    return None
