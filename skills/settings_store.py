"""
Settings + creative cache storage (SQLite at data/reports.db).

Tables:
- settings: key-value store for token, ad_account_id, etc.
- creative_cache: ad_id -> thumbnail_url (cached 24h)
"""
from __future__ import annotations
import hashlib
import json
import secrets
import sqlite3
import time
from pathlib import Path


def _db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS creative_cache (
            ad_id TEXT PRIMARY KEY,
            data_json TEXT NOT NULL,
            fetched_at INTEGER NOT NULL
        )
    """)
    return conn


def set_setting(db_path: Path, key: str, value) -> None:
    with _db(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            (key, json.dumps(value), int(time.time())),
        )


def get_setting(db_path: Path, key: str, default=None):
    with _db(db_path) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row[0])
    except Exception:
        return default


def get_all_settings(db_path: Path) -> dict:
    with _db(db_path) as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    out = {}
    for k, v in rows:
        try:
            out[k] = json.loads(v)
        except Exception:
            out[k] = v
    return out


def cache_creative(db_path: Path, ad_id: str, data: dict) -> None:
    with _db(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO creative_cache (ad_id, data_json, fetched_at) VALUES (?, ?, ?)",
            (str(ad_id), json.dumps(data), int(time.time())),
        )


def get_cached_creative(db_path: Path, ad_id: str, ttl_seconds: int = 86400) -> dict | None:
    """Get cached creative if not older than ttl. Default 24h."""
    with _db(db_path) as conn:
        row = conn.execute(
            "SELECT data_json, fetched_at FROM creative_cache WHERE ad_id = ?",
            (str(ad_id),),
        ).fetchone()
    if not row:
        return None
    fetched_at = row[1]
    if int(time.time()) - fetched_at > ttl_seconds:
        return None
    try:
        return json.loads(row[0])
    except Exception:
        return None


def clear_creative_cache(db_path: Path) -> int:
    with _db(db_path) as conn:
        cur = conn.execute("DELETE FROM creative_cache")
        return cur.rowcount


# ---------- Password gate ----------
def _hash_password(password: str, salt: str) -> str:
    h = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return h


def password_is_set(db_path: Path) -> bool:
    return bool(get_setting(db_path, "auth_password_hash"))


def set_password(db_path: Path, new_password: str) -> None:
    """Set or change the shared hub password."""
    salt = secrets.token_hex(16)
    set_setting(db_path, "auth_password_salt", salt)
    set_setting(db_path, "auth_password_hash", _hash_password(new_password, salt))


def verify_password(db_path: Path, attempt: str) -> bool:
    stored_hash = get_setting(db_path, "auth_password_hash")
    salt = get_setting(db_path, "auth_password_salt")
    if not stored_hash or not salt:
        return False
    return _hash_password(attempt, salt) == stored_hash


def mask_secret(secret: str, keep_last: int = 4) -> str:
    """Mask a secret string for display: 'EAA...XYZW' -> '••••••XYZW'."""
    if not secret:
        return "(empty)"
    if len(secret) <= keep_last:
        return "•" * len(secret)
    return "•" * 8 + secret[-keep_last:]
