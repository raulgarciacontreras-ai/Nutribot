"""
Configuración central — lee variables de entorno desde .env
"""
import os
import re
from dotenv import load_dotenv

load_dotenv()

# ── Identidad ────────────────────────────────────────────────────────────────
BOT_NAME = "Nutribot"

# ── Telegram ─────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# ── Usuarios configurados (formato NOMBRE_ID=chat_id en .env) ────────────────
def get_configured_users() -> dict:
    """
    Lee todas las variables *_ID del .env y retorna
    un dict {chat_id: nombre}.
    Ejemplo: NATHALIE_ID=123 → {123: "Nathalie"}
    También soporta formato antiguo *_CHAT_ID.
    """
    users = {}
    for key, value in os.environ.items():
        # Formato nuevo: NOMBRE_ID=chat_id
        if key == "SUPERADMIN_ID":
            continue
        match = re.match(r'^([A-Z][A-Z0-9]+)_ID$', key)
        if not match:
            # Formato antiguo: NOMBRE_CHAT_ID=chat_id
            match = re.match(r'^([A-Z][A-Z0-9]+)_CHAT_ID$', key)
        if match and value.isdigit() and int(value) > 0:
            name = match.group(1).capitalize()
            users[int(value)] = name
    return users

CONFIGURED_USERS = get_configured_users()

# ── LLM Primary / Fallback ────────────────────────────────────────────────────
PRIMARY_LLM = os.getenv("PRIMARY_LLM", "gemini")
FALLBACK_LLM = os.getenv("FALLBACK_LLM", "groq")

# ── Claude (Anthropic) ────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

# ── Gemini ────────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# ── Groq (OpenAI-compatible) ──────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")

# ── Paths ────────────────────────────────────────────────────────────────────
NUTRITION_GUIDE_PATH = os.getenv("NUTRITION_GUIDE_PATH", "./data/nutrition_guide.txt")
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma_db")
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "./data/nathalie.db")
MEDIA_PATH = os.getenv("MEDIA_PATH", "./media/stickers")

# ── RAG ──────────────────────────────────────────────────────────────────────
RAG_CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "500"))
RAG_CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "50"))
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "4"))

# ── Conversación ─────────────────────────────────────────────────────────────
CONVERSATION_WINDOW = int(os.getenv("CONVERSATION_WINDOW", "10"))

# ── Scheduler (horarios de recordatorio) ─────────────────────────────────────
TIMEZONE = os.getenv("TIMEZONE", "America/Lima")

SCHEDULE = {
    "breakfast": {
        "hour": int(os.getenv("SCHEDULE_BREAKFAST", "07:00").split(":")[0]),
        "minute": int(os.getenv("SCHEDULE_BREAKFAST", "07:00").split(":")[1]),
    },
    "lunch": {
        "hour": int(os.getenv("SCHEDULE_LUNCH", "12:30").split(":")[0]),
        "minute": int(os.getenv("SCHEDULE_LUNCH", "12:30").split(":")[1]),
    },
    "snack": {
        "hour": int(os.getenv("SCHEDULE_SNACK", "18:00").split(":")[0]),
        "minute": int(os.getenv("SCHEDULE_SNACK", "18:00").split(":")[1]),
    },
    "dinner": {
        "hour": int(os.getenv("SCHEDULE_DINNER", "20:30").split(":")[0]),
        "minute": int(os.getenv("SCHEDULE_DINNER", "20:30").split(":")[1]),
    },
    "checkin": {
        "hour": int(os.getenv("SCHEDULE_CHECKIN", "21:30").split(":")[0]),
        "minute": int(os.getenv("SCHEDULE_CHECKIN", "21:30").split(":")[1]),
    },
}

# ── Superadmin ───────────────────────────────────────────────────────────────
SUPERADMIN_ID = int(os.getenv("SUPERADMIN_ID", "0"))

# ── Google Places (delivery) ─────────────────────────────────────────────────
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
