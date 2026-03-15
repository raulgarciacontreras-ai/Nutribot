"""
Configuración central — lee variables de entorno desde .env
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Identidad ────────────────────────────────────────────────────────────────
BOT_NAME = "Nutribot"
NATHALIE_NAME = "Nathalie"

# ── Telegram (opcionales para scripts auxiliares como ingest_guide.py) ────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
NATHALIE_CHAT_ID = int(os.getenv("NATHALIE_CHAT_ID", "0"))

# ── Groq (OpenAI-compatible) ──────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "llama-3.2-11b-vision-preview")

# ── Embeddings ────────────────────────────────────────────────────────────────
EMBED_MODEL = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")

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

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
