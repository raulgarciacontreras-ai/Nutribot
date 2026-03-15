"""
Memory Store — perfil de Nathalie, historial de conversación y log de comidas.
SQLite liviano, sin dependencias externas.
"""
import sqlite3
import json
from datetime import datetime, timezone
from typing import Optional

from config import SQLITE_DB_PATH, CONVERSATION_WINDOW

# ── Schema ───────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_profile (
    id          INTEGER PRIMARY KEY DEFAULT 1,
    name        TEXT DEFAULT 'Nathalie',
    weight_kg   REAL,
    height_cm   REAL,
    age         INTEGER,
    activity    TEXT,
    goal        TEXT,
    restrictions TEXT,
    symptoms    TEXT,
    notes       TEXT,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS conversation (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    role        TEXT NOT NULL,          -- 'user' | 'assistant'
    content     TEXT NOT NULL,
    msg_type    TEXT DEFAULT 'text',    -- 'text' | 'photo' | 'reminder'
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS meal_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    meal_type   TEXT NOT NULL,          -- breakfast | lunch | dinner | snack
    description TEXT NOT NULL,
    est_cal     INTEGER,
    created_at  TEXT DEFAULT (datetime('now'))
);
"""


def _conn() -> sqlite3.Connection:
    import os
    os.makedirs(os.path.dirname(SQLITE_DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Crea las tablas si no existen."""
    with _conn() as conn:
        conn.executescript(_SCHEMA)


# ── Perfil ───────────────────────────────────────────────────────────────────

def get_profile() -> Optional[dict]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM user_profile WHERE id = 1").fetchone()
        return dict(row) if row else None


def update_profile(**kwargs):
    """Upsert del perfil. Acepta cualquier campo del schema."""
    kwargs["updated_at"] = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        existing = conn.execute("SELECT id FROM user_profile WHERE id = 1").fetchone()
        if existing:
            sets = ", ".join(f"{k} = ?" for k in kwargs)
            conn.execute(f"UPDATE user_profile SET {sets} WHERE id = 1", list(kwargs.values()))
        else:
            cols = ", ".join(kwargs.keys())
            placeholders = ", ".join("?" for _ in kwargs)
            conn.execute(f"INSERT INTO user_profile ({cols}) VALUES ({placeholders})", list(kwargs.values()))
        conn.commit()


# ── Conversación ─────────────────────────────────────────────────────────────

def save_turn(role: str, content: str, msg_type: str = "text"):
    with _conn() as conn:
        conn.execute(
            "INSERT INTO conversation (role, content, msg_type) VALUES (?, ?, ?)",
            (role, content, msg_type),
        )
        conn.commit()


def get_recent_turns(n: int = None) -> list[dict]:
    n = n or CONVERSATION_WINDOW
    with _conn() as conn:
        rows = conn.execute(
            "SELECT role, content, msg_type FROM conversation ORDER BY id DESC LIMIT ?",
            (n,),
        ).fetchall()
        rows = [dict(r) for r in rows]
        rows.reverse()
        return rows


# ── Meal log ─────────────────────────────────────────────────────────────────

def log_meal(meal_type: str, description: str, est_cal: int = None):
    with _conn() as conn:
        conn.execute(
            "INSERT INTO meal_log (meal_type, description, est_cal) VALUES (?, ?, ?)",
            (meal_type, description, est_cal),
        )
        conn.commit()


def get_today_meals() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT meal_type, description, est_cal FROM meal_log "
            "WHERE date(created_at) = date('now') ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]


def get_today_total_kcal() -> int:
    """Retorna el total de calorias estimadas registradas hoy."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(est_cal), 0) AS total FROM meal_log "
            "WHERE date(created_at) = date('now')"
        ).fetchone()
        return row["total"]
