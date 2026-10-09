"""FR-14, FR-29, NFR-1 to NFR-3, AC-22: data-access functions in database/db.py."""

import hashlib
import inspect
import os
import sqlite3

import pytest

from tests.helpers import DEMO_EMAIL, DEMO_PASSWORD, OTHER_EMAIL, OTHER_PASSWORD, WRONG_PASSWORD


def _rows(db_path, sql, params=()):
    con = sqlite3.connect(db_path)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def test_fr29_init_db_creates_file_and_users_table(db_module, db_path):
    assert not os.path.exists(db_path)
    db_module.init_db(db_path)
    assert os.path.exists(db_path)
    columns = {row[1] for row in _rows(db_path, "PRAGMA table_info(users)")}
    assert {"id", "email", "password_hash"} <= columns


def test_fr29_init_db_seeds_demo_account(db_module, db_path):
    db_module.init_db(db_path)
    assert _rows(db_path, "SELECT email FROM users") == [(DEMO_EMAIL,)]


def test_fr29_init_db_is_idempotent(db_module, db_path):
    db_module.init_db(db_path)
    db_module.init_db(db_path)
    assert _rows(db_path, "SELECT COUNT(*) FROM users") == [(1,)]


def test_fr29_email_is_unique(db_module, db_path):
    db_module.init_db(db_path)
    with pytest.raises(ValueError):
        db_module.create_user(db_path, " USER@Example.com ", "some other words")


def test_fr29_create_user_returns_id_and_stores_normalized_email(db_module, db_path):
    db_module.init_db(db_path)
    user_id = db_module.create_user(db_path, "  Other@Example.COM ", OTHER_PASSWORD)
    assert isinstance(user_id, int)
    assert _rows(db_path, "SELECT id FROM users WHERE email = ?", (OTHER_EMAIL,)) == [(user_id,)]


def test_fr29_get_user_by_email(db_module, db_path):
    db_module.init_db(db_path)
    user = db_module.get_user_by_email(db_path, DEMO_EMAIL)
    assert user["email"] == DEMO_EMAIL
    assert isinstance(user["id"], int)
    assert user["password_hash"]


def test_fr14_get_user_by_email_normalizes(db_module, db_path):
    db_module.init_db(db_path)
    user = db_module.get_user_by_email(db_path, "  USER@Example.com ")
    assert user is not None and user["email"] == DEMO_EMAIL


def test_fr14_get_user_by_email_unknown_returns_none(db_module, db_path):
    db_module.init_db(db_path)
    assert db_module.get_user_by_email(db_path, "nobody@example.com") is None


def test_fr14_authenticate_with_correct_password(db_module, seeded_db):
    user = db_module.authenticate(seeded_db, DEMO_EMAIL, DEMO_PASSWORD)
    assert user["email"] == DEMO_EMAIL
    other = db_module.authenticate(seeded_db, OTHER_EMAIL, OTHER_PASSWORD)
    assert other["email"] == OTHER_EMAIL


def test_fr14_authenticate_normalizes_email(db_module, seeded_db):
    user = db_module.authenticate(seeded_db, "  USER@Example.com ", DEMO_PASSWORD)
    assert user is not None and user["email"] == DEMO_EMAIL


def test_fr14_authenticate_wrong_password_returns_none(db_module, seeded_db):
    assert db_module.authenticate(seeded_db, DEMO_EMAIL, WRONG_PASSWORD) is None


def test_fr14_authenticate_unknown_email_returns_none(db_module, seeded_db):
    assert db_module.authenticate(seeded_db, "nobody@example.com", DEMO_PASSWORD) is None


def test_fr14_password_is_case_sensitive(db_module, seeded_db):
    assert db_module.authenticate(seeded_db, DEMO_EMAIL, "Green apple house") is None


def test_fr14_password_spaces_matter(db_module, seeded_db):
    assert db_module.authenticate(seeded_db, DEMO_EMAIL, DEMO_PASSWORD + " ") is None
    assert db_module.authenticate(seeded_db, DEMO_EMAIL, "green  apple house") is None


def test_ac22_no_column_contains_plain_password(db_module, seeded_db):
    tables = [r[0] for r in _rows(seeded_db, "SELECT name FROM sqlite_master WHERE type='table'")]
    for table in tables:
        for row in _rows(seeded_db, f'SELECT * FROM "{table}"'):
            for value in row:
                text = value.decode("latin-1") if isinstance(value, bytes) else str(value)
                assert DEMO_PASSWORD not in text
                assert OTHER_PASSWORD not in text


def _parse_hash(encoded):
    scheme, iterations, salt_hex, hash_hex = encoded.split("$")
    return scheme, int(iterations), bytes.fromhex(salt_hex), hash_hex


def test_ac22_nfr1_stored_value_is_salted_pbkdf2_hash(db_module, db_path):
    db_module.init_db(db_path)
    stored = db_module.get_user_by_email(db_path, DEMO_EMAIL)["password_hash"]
    scheme, iterations, salt, hash_hex = _parse_hash(stored)
    assert scheme == "pbkdf2_sha256"
    assert iterations >= 200_000
    assert len(salt) == 16
    expected = hashlib.pbkdf2_hmac("sha256", DEMO_PASSWORD.encode("utf-8"), salt, iterations).hex()
    assert hash_hex == expected


def test_nfr1_hash_password_uses_random_salt(db_module):
    first = db_module.hash_password(DEMO_PASSWORD)
    second = db_module.hash_password(DEMO_PASSWORD)
    assert first != second
    assert _parse_hash(first)[2] != _parse_hash(second)[2]


def test_nfr1_verify_password(db_module):
    stored = db_module.hash_password(DEMO_PASSWORD)
    assert db_module.verify_password(DEMO_PASSWORD, stored) is True
    assert db_module.verify_password("green apple houses", stored) is False


def test_nfr2_hashes_compared_with_compare_digest(db_module):
    assert "compare_digest" in inspect.getsource(db_module)


@pytest.mark.parametrize(
    "email",
    ["' OR '1'='1", "user@example.com' --", "x'; DROP TABLE users; --"],
)
def test_nfr3_sql_injection_in_email_has_no_effect(db_module, seeded_db, email):
    assert db_module.get_user_by_email(seeded_db, email) is None
    assert db_module.authenticate(seeded_db, email, DEMO_PASSWORD) is None
    assert _rows(seeded_db, "SELECT COUNT(*) FROM users") == [(2,)]
