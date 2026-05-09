import sqlite3
import os
import secrets
import time
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "walkie_talkie.db")


def canonicalize_user_id(user_id: str) -> str:
    """
    Normalize user IDs so identity is consistent across casing/spacing variants.
    """
    return (user_id or "").strip().lower()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,            -- app-level stable user id
            display_name TEXT,
            budget INTEGER,
            dietary_restriction TEXT,
            home_country TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            session_token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            expires_at INTEGER NOT NULL,         -- unix epoch seconds
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS visited_places (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            city TEXT,
            place_name TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            city TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS city_index_status (
            city TEXT PRIMARY KEY,
            status TEXT NOT NULL,               -- missing | building | ready | failed
            updated_at INTEGER NOT NULL,        -- unix epoch seconds
            source_count INTEGER DEFAULT 0,
            chunk_count INTEGER DEFAULT 0,
            error TEXT
        )
    ''')
    
    # Best-effort schema evolution for existing DBs that may not have these columns.
    for alter_sql in (
        "ALTER TABLE users ADD COLUMN display_name TEXT",
        "ALTER TABLE users ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE visited_places ADD COLUMN city TEXT",
    ):
        try:
            cursor.execute(alter_sql)
        except Exception:
            pass

    conn.commit()
    conn.close()

def ensure_user(user_id: str, display_name: Optional[str] = None):
    user_id = canonicalize_user_id(user_id)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, display_name, budget, dietary_restriction, home_country) VALUES (?, ?, ?, ?, ?)",
        (user_id, display_name or user_id, None, None, None),
    )
    if display_name:
        cursor.execute("UPDATE users SET display_name = ? WHERE user_id = ?", (display_name, user_id))
    conn.commit()
    conn.close()

def create_session(user_id: str, ttl_hours: int = 24) -> dict:
    user_id = canonicalize_user_id(user_id)
    purge_expired_sessions()
    ensure_user(user_id)
    token = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + (ttl_hours * 3600)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO sessions (session_token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user_id, expires_at),
    )
    conn.commit()
    conn.close()
    return {"session_token": token, "user_id": user_id, "expires_at": expires_at}

def get_user_by_session(session_token: str) -> Optional[dict]:
    if not session_token:
        return None
    purge_expired_sessions()
    now = int(time.time())
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT s.user_id, s.expires_at, u.display_name, u.budget, u.dietary_restriction, u.home_country
        FROM sessions s
        JOIN users u ON s.user_id = u.user_id
        WHERE s.session_token = ? AND s.expires_at > ?
        """,
        (session_token, now),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "user_id": row[0],
        "expires_at": row[1],
        "display_name": row[2],
        "budget": row[3],
        "dietary": row[4],
        "country": row[5],
    }


def revoke_session(session_token: str) -> bool:
    if not session_token:
        return False
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE session_token = ?", (session_token,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def purge_expired_sessions() -> int:
    now = int(time.time())
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted

def update_user_preferences(
    user_id: str,
    budget: Optional[int] = None,
    dietary: Optional[str] = None,
    country: Optional[str] = None,
):
    user_id = canonicalize_user_id(user_id)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    ensure_user(user_id)
    if budget is not None:
        cursor.execute("UPDATE users SET budget = ? WHERE user_id = ?", (budget, user_id))
    if dietary is not None:
        cursor.execute("UPDATE users SET dietary_restriction = ? WHERE user_id = ?", (dietary, user_id))
    if country is not None:
        cursor.execute("UPDATE users SET home_country = ? WHERE user_id = ?", (country, user_id))
    conn.commit()
    conn.close()

def get_user_preferences(user_id: str):
    user_id = canonicalize_user_id(user_id)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT budget, dietary_restriction, home_country FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"budget": row[0], "dietary": row[1], "country": row[2]}
    return None

def save_visited_place(user_id: str, place_name: str, city: Optional[str] = None):
    user_id = canonicalize_user_id(user_id)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO visited_places (user_id, city, place_name) VALUES (?, ?, ?)",
        (user_id, city, place_name),
    )
    conn.commit()
    conn.close()
    return f"Saved {place_name} for user {user_id}"

def save_chat_message(user_id: str, city: str, role: str, content: str):
    user_id = canonicalize_user_id(user_id)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO chat_history (user_id, city, role, content) VALUES (?, ?, ?, ?)",
        (user_id, city, role, content),
    )
    conn.commit()
    conn.close()

def get_chat_history(user_id: str, city: str, limit: int = 100):
    user_id = canonicalize_user_id(user_id)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT role, content, created_at
        FROM chat_history
        WHERE user_id = ? AND city = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, city, limit),
    )
    rows = cursor.fetchall()
    conn.close()
    rows.reverse()
    return [{"role": r[0], "content": r[1], "created_at": r[2]} for r in rows]


def set_city_index_status(
    city: str,
    status: str,
    source_count: int = 0,
    chunk_count: int = 0,
    error: Optional[str] = None,
):
    city = (city or "").strip()
    if not city:
        return
    now = int(time.time())
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO city_index_status (city, status, updated_at, source_count, chunk_count, error)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(city) DO UPDATE SET
            status=excluded.status,
            updated_at=excluded.updated_at,
            source_count=excluded.source_count,
            chunk_count=excluded.chunk_count,
            error=excluded.error
        """,
        (city, status, now, source_count, chunk_count, error),
    )
    conn.commit()
    conn.close()


def get_city_index_status(city: str) -> Optional[dict]:
    city = (city or "").strip()
    if not city:
        return None
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT city, status, updated_at, source_count, chunk_count, error FROM city_index_status WHERE city = ?",
        (city,),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "city": row[0],
        "status": row[1],
        "updated_at": row[2],
        "source_count": row[3],
        "chunk_count": row[4],
        "error": row[5],
    }

# Initialize db on load
init_db()
