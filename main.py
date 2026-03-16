"""
main.py — Punto de entrada de Nutribot.
Arranca: Telegram bot (polling) + APScheduler + ingesta inicial de RAG.
Multi-usuario: registra automáticamente los usuarios del .env.
"""

import asyncio
import logging
import os

from telegram.ext import Application

from config import TELEGRAM_BOT_TOKEN, GROQ_API_KEY, CONFIGURED_USERS
from bot.telegram_handler import register_handlers
from tools.sticker_manager import ensure_folders
from memory.store import init_db, register_user
from rag.vector_store import is_populated
from scheduler.reminder_scheduler import setup as setup_scheduler

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def bootstrap() -> None:
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not GROQ_API_KEY:
        missing.append("GROQ_API_KEY")
    if missing:
        logger.error("Faltan variables de entorno: %s", ", ".join(missing))
        logger.error("Copia .env.example a .env y complétalo.")
        raise SystemExit(1)

    os.makedirs("./data", exist_ok=True)

    # Migrar datos antiguos si existen
    nathalie_id = int(os.getenv("NATHALIE_CHAT_ID", os.getenv("NATHALIE_ID", "0")))
    init_db(nathalie_chat_id=nathalie_id)
    logger.info("SQLite inicializado: %s (multi-usuario)", "data/nathalie.db")

    ensure_folders()

    # Tests automáticos
    from tests.test_nutribot import run_all as run_tests
    logger.info("Corriendo tests automaticos...")
    resultados = run_tests()
    fallos = {k: v for k, v in resultados.items() if not v.startswith("OK")}
    if fallos:
        logger.warning("Tests con problemas: %s", fallos)
    else:
        logger.info("Todos los tests pasaron (%d tests)", len(resultados))

    # Registrar usuarios configurados en .env
    for chat_id, name in CONFIGURED_USERS.items():
        register_user(chat_id, name)
        logger.info("Usuario configurado: %s (ID: %d)", name, chat_id)

    if not CONFIGURED_USERS:
        logger.info("No hay usuarios pre-configurados en .env (cualquiera puede usar /start)")

    if not is_populated():
        logger.info("ChromaDB vacío — indexando guía nutricional...")
        from scripts.ingest_guide import ingest
        n = ingest()
        if n > 0:
            logger.info("Indexados %d chunks en ChromaDB", n)
        else:
            logger.warning("No se encontraron archivos para indexar en knowledge/ o data/")
    else:
        logger.info("ChromaDB ya tiene datos — OK")


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

    logger.info("Nutribot arrancado. Esperando mensajes...")

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
