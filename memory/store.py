"""
Memory Store — multi-usuario.
Perfil + log diario de macros + mensajes con retención de 8 horas.
SQLite liviano, sin dependencias externas.
"""
import sqlite3
import json
from datetime import datetime, date, timedelta, timezone
from typing import Optional

from config import SQLITE_DB_PATH

# ── Schema ───────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id   INTEGER NOT NULL,
    role      TEXT NOT NULL,
    content   TEXT NOT NULL,
    ts        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profile (
    chat_id   INTEGER NOT NULL,
    key       TEXT NOT NULL,
    value     TEXT NOT NULL,
    PRIMARY KEY (chat_id, key)
);

CREATE TABLE IF NOT EXISTS daily_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    meal_type   TEXT NOT NULL,
    description TEXT NOT NULL,
    kcal        INTEGER DEFAULT 0,
    proteina    REAL DEFAULT 0,
    carbos      REAL DEFAULT 0,
    grasas      REAL DEFAULT 0,
    fibra       REAL DEFAULT 0,
    logged_at   TEXT NOT NULL,
    date        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_goals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    goal        TEXT NOT NULL,
    target_kcal INTEGER,
    created_at  TEXT NOT NULL,
    status      TEXT DEFAULT 'activo'
);

CREATE TABLE IF NOT EXISTS user_reminders (
    chat_id         INTEGER PRIMARY KEY,
    breakfast_time  TEXT DEFAULT '07:00',
    lunch_time      TEXT DEFAULT '12:30',
    snack_time      TEXT DEFAULT '17:30',
    dinner_time     TEXT DEFAULT '20:00',
    checkin_time    TEXT DEFAULT '21:30',
    active          INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS user_settings (
    chat_id         INTEGER PRIMARY KEY,
    conv_style      TEXT DEFAULT 'balanceado',
    response_length TEXT DEFAULT 'corto',
    language        TEXT DEFAULT 'español',
    emoji_level     TEXT DEFAULT 'moderado',
    nickname        TEXT DEFAULT '',
    updated_at      TEXT
);
"""


def _conn() -> sqlite3.Connection:
    import os
    os.makedirs(os.path.dirname(SQLITE_DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(nathalie_chat_id: int = 0):
    """Crea las tablas si no existen."""
    with _conn() as conn:
        conn.executescript(_SCHEMA)


# ── Registro de usuarios ────────────────────────────────────────────────────

def register_user(chat_id: int, name: str = "Usuario") -> bool:
    """
    Crea el perfil de un nuevo usuario si no existe.
    Retorna True si es usuario nuevo, False si ya existía.
    """
    with _conn() as conn:
        existing = conn.execute(
            "SELECT value FROM profile WHERE chat_id=? AND key='name'",
            (chat_id,),
        ).fetchone()
        if not existing:
            defaults = {
                "name": name,
                "weight_kg": "0",
                "height_cm": "0",
                "age": "0",
                "sexo": "no especificado",
                "symptoms": "[]",
            }
            for k, v in defaults.items():
                conn.execute(
                    "INSERT OR IGNORE INTO profile (chat_id, key, value) VALUES (?, ?, ?)",
                    (chat_id, k, v),
                )
            conn.commit()
            return True
    return False


def get_all_chat_ids() -> list[int]:
    """Retorna todos los chat_ids registrados."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT chat_id FROM profile"
        ).fetchall()
        return [r["chat_id"] for r in rows]


# ── Perfil ───────────────────────────────────────────────────────────────────

def get_profile(chat_id: int) -> dict:
    """Retorna el perfil como dict {key: value}."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT key, value FROM profile WHERE chat_id=?",
            (chat_id,),
        ).fetchall()
        return {r["key"]: r["value"] for r in rows}


def update_profile(chat_id: int, key: str, value: str):
    """Upsert de un campo del perfil."""
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO profile (chat_id, key, value) VALUES (?, ?, ?)",
            (chat_id, key, str(value)),
        )
        conn.commit()


def format_profile_summary(chat_id: int) -> str:
    """Formatea el perfil como texto para el prompt."""
    profile = get_profile(chat_id)
    if not profile:
        return ""
    return ", ".join(f"{k}: {v}" for k, v in profile.items() if v and v != "0")


# ── Mensajes (retención 8 horas) ─────────────────────────────────────────────

def save_message(chat_id: int, role: str, content: str) -> None:
    """Guarda un mensaje de conversación."""
    ts = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO messages (chat_id, role, content, ts) "
            "VALUES (?, ?, ?, ?)",
            (chat_id, role, content, ts),
        )
        conn.commit()


def get_recent_messages(chat_id: int) -> list[dict]:
    """Retorna mensajes de las últimas 8 horas solamente."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=8)).isoformat()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages "
            "WHERE chat_id=? AND ts >= ? "
            "ORDER BY id DESC LIMIT 20",
            (chat_id, cutoff),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def cleanup_old_messages() -> int:
    """Borra mensajes más antiguos de 8 horas. Se llama cada hora."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=8)).isoformat()
    with _conn() as conn:
        conn.execute("DELETE FROM messages WHERE ts < ?", (cutoff,))
        conn.commit()
        # Can't get rowcount reliably with context manager, just return 0
        return 0


# ── Daily log (macros) ──────────────────────────────────────────────────────

def log_meal(chat_id: int, meal_type: str, description: str,
             kcal: int = 0, proteina: float = 0, carbos: float = 0,
             grasas: float = 0, fibra: float = 0):
    """Registra una comida con macros completos."""
    today = date.today().isoformat()
    ts = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO daily_log "
            "(chat_id, meal_type, description, kcal, proteina, "
            "carbos, grasas, fibra, logged_at, date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (chat_id, meal_type, description, kcal, proteina,
             carbos, grasas, fibra, ts, today),
        )
        conn.commit()


def get_today_summary(chat_id: int) -> dict:
    """Retorna comidas y totales de macros de hoy."""
    today = date.today().isoformat()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT meal_type, description, kcal, proteina, "
            "carbos, grasas, fibra "
            "FROM daily_log WHERE chat_id=? AND date=? "
            "ORDER BY id",
            (chat_id, today),
        ).fetchall()

    meals = []
    totales = {"kcal": 0, "proteina": 0.0, "carbos": 0.0,
               "grasas": 0.0, "fibra": 0.0}

    for r in rows:
        meals.append({
            "meal_type": r["meal_type"], "description": r["description"],
            "kcal": r["kcal"], "proteina": r["proteina"],
            "carbos": r["carbos"], "grasas": r["grasas"],
            "fibra": r["fibra"],
        })
        totales["kcal"] += r["kcal"] or 0
        totales["proteina"] += r["proteina"] or 0
        totales["carbos"] += r["carbos"] or 0
        totales["grasas"] += r["grasas"] or 0
        totales["fibra"] += r["fibra"] or 0

    return {"meals": meals, "totales": totales}


def get_today_total_kcal(chat_id: int) -> int:
    """Retorna el total de kcal de hoy."""
    return get_today_summary(chat_id)["totales"]["kcal"]


def get_today_meals(chat_id: int) -> list[dict]:
    """Retorna las comidas de hoy (compatibilidad)."""
    return get_today_summary(chat_id)["meals"]


def reset_daily_log(chat_id: int) -> None:
    """Borra el log del día anterior."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    with _conn() as conn:
        conn.execute(
            "DELETE FROM daily_log WHERE chat_id=? AND date<=?",
            (chat_id, yesterday),
        )
        conn.commit()


def format_today_for_prompt(chat_id: int) -> str:
    """Formatea el log de hoy para el prompt del LLM."""
    summary = get_today_summary(chat_id)
    meals = summary["meals"]
    t = summary["totales"]
    profile = get_profile(chat_id)
    tdee = int(profile.get("tdee", "2000") or "2000")
    restante = tdee - t["kcal"]

    if not meals:
        return f"Hoy no ha comido nada todavía. Meta: {tdee} kcal."

    lines = []
    for m in meals:
        lines.append(
            f"  - {m['meal_type']}: {m['description'][:50]} "
            f"({m['kcal']} kcal | P:{m['proteina']}g "
            f"C:{m['carbos']}g G:{m['grasas']}g)"
        )

    lines.append(f"\nTotal hoy: {t['kcal']} kcal | "
                 f"P:{round(t['proteina'])}g C:{round(t['carbos'])}g "
                 f"G:{round(t['grasas'])}g")
    lines.append(f"Meta: {tdee} kcal | Faltan: {restante} kcal")

    return "\n".join(lines)


# ── Objetivos ────────────────────────────────────────────────────────────────

def add_goal(chat_id: int, goal: str, target_kcal: int = None):
    """Registra un nuevo objetivo del usuario."""
    ts = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO user_goals (chat_id, goal, target_kcal, created_at) "
            "VALUES (?, ?, ?, ?)",
            (chat_id, goal, target_kcal, ts),
        )
        conn.commit()


def get_goals(chat_id: int) -> list[dict]:
    """Retorna los objetivos del usuario."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT goal, target_kcal, created_at, status "
            "FROM user_goals WHERE chat_id=? ORDER BY id DESC",
            (chat_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Recordatorios personalizados ─────────────────────────────────────────────

def get_user_reminders(chat_id: int) -> dict:
    """Retorna los horarios de recordatorios del usuario."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT breakfast_time, lunch_time, snack_time, "
            "dinner_time, checkin_time, active "
            "FROM user_reminders WHERE chat_id=?",
            (chat_id,),
        ).fetchone()
    if row:
        return {
            "breakfast": row["breakfast_time"],
            "lunch": row["lunch_time"],
            "snack": row["snack_time"],
            "dinner": row["dinner_time"],
            "checkin": row["checkin_time"],
            "active": bool(row["active"]),
        }
    return {
        "breakfast": "07:00", "lunch": "12:30",
        "snack": "17:30", "dinner": "20:00",
        "checkin": "21:30", "active": True,
    }


def save_user_reminders(chat_id: int, reminders: dict):
    """Guarda los horarios de recordatorios del usuario."""
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_reminders "
            "(chat_id, breakfast_time, lunch_time, snack_time, "
            "dinner_time, checkin_time, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                chat_id,
                reminders.get("breakfast", "07:00"),
                reminders.get("lunch", "12:30"),
                reminders.get("snack", "17:30"),
                reminders.get("dinner", "20:00"),
                reminders.get("checkin", "21:30"),
                1 if reminders.get("active", True) else 0,
            ),
        )
        conn.commit()


# ── Settings de conversación ─────────────────────────────────────────────────

def get_user_settings(chat_id: int) -> dict:
    """Retorna las preferencias de estilo de conversación del usuario."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT conv_style, response_length, language, "
            "emoji_level, nickname "
            "FROM user_settings WHERE chat_id=?",
            (chat_id,),
        ).fetchone()
    if row:
        return {
            "conv_style": row["conv_style"],
            "response_length": row["response_length"],
            "language": row["language"],
            "emoji_level": row["emoji_level"],
            "nickname": row["nickname"],
        }
    return {
        "conv_style": "balanceado",
        "response_length": "corto",
        "language": "español",
        "emoji_level": "moderado",
        "nickname": "",
    }


def get_weekly_summary(chat_id: int, weeks: int = 2) -> dict:
    """
    Retorna un dict {fecha: [meals]} de las últimas N semanas.
    Cada meal tiene: meal_type, description, kcal, proteina, carbos, grasas, fibra.
    """
    cutoff = (date.today() - timedelta(weeks=weeks)).isoformat()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT date, meal_type, description, kcal, proteina, "
            "carbos, grasas, fibra "
            "FROM daily_log WHERE chat_id=? AND date>=? "
            "ORDER BY date, id",
            (chat_id, cutoff),
        ).fetchall()

    result = {}
    for r in rows:
        d = r["date"]
        if d not in result:
            result[d] = []
        result[d].append({
            "meal_type": r["meal_type"],
            "description": r["description"],
            "kcal_est": r["kcal"] or 0,
            "proteina": r["proteina"] or 0,
            "carbos": r["carbos"] or 0,
            "grasas": r["grasas"] or 0,
            "fibra": r["fibra"] or 0,
        })
    return result


def save_user_settings(chat_id: int, settings: dict):
    """Guarda las preferencias de estilo de conversación."""
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_settings "
            "(chat_id, conv_style, response_length, language, "
            "emoji_level, nickname, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                chat_id,
                settings.get("conv_style", "balanceado"),
                settings.get("response_length", "corto"),
                settings.get("language", "español"),
                settings.get("emoji_level", "moderado"),
                settings.get("nickname", ""),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
