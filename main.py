"""
main.py — Punto de entrada de Nutribot.
Arranca: Telegram bot (polling) + APScheduler + ingesta inicial de RAG.
"""

import asyncio
import logging
import os

from telegram.ext import Application

from config import TELEGRAM_BOT_TOKEN, GROQ_API_KEY, NATHALIE_CHAT_ID
from bot.telegram_handler import register_handlers
from tools.sticker_manager import ensure_folders
from memory.store import init_db
from rag.vector_store import is_populated
from scheduler.reminder_scheduler import setup as setup_scheduler

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def bootstrap() -> None:
    # Validar variables obligatorias al arrancar el bot
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not GROQ_API_KEY:
        missing.append("GROQ_API_KEY")
    if not NATHALIE_CHAT_ID:
        missing.append("NATHALIE_CHAT_ID")
    if missing:
        logger.error("Faltan variables de entorno: %s", ", ".join(missing))
        logger.error("Copia .env.example a .env y complétalo.")
        raise SystemExit(1)

    os.makedirs("./data", exist_ok=True)
    init_db()
    logger.info("SQLite inicializado: %s", "data/nathalie.db")
    ensure_folders()

    if not is_populated():
        logger.warning(
            "ChromaDB vacío. Ejecuta primero: python scripts/ingest_guide.py\n"
            "El bot funcionará sin RAG hasta que lo hagas."
        )


async def main() -> None:
    bootstrap()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    register_handlers(app)

    scheduler = setup_scheduler(app)
    scheduler.start()
    logger.info("Scheduler arrancado con %d jobs", len(scheduler.get_jobs()))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=["message"])

    logger.info("Nutribot arrancado. Esperando mensajes de Nathalie...")

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Apagando...")
    finally:
        scheduler.shutdown(wait=False)
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
