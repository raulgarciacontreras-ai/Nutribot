"""
Scheduler — envía recordatorios proactivos a Nathalie en horarios configurados.
Usa APScheduler con CronTrigger para cada franja horaria.
"""
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from config import NATHALIE_CHAT_ID, SCHEDULE, TIMEZONE, NATHALIE_NAME
from memory.store import save_turn, get_recent_turns, get_profile, get_today_meals
from rag.vector_store import retrieve
from llm.llm_client import chat
from tools.sticker_manager import seleccionar_sticker

logger = logging.getLogger(__name__)

# Mensajes que el scheduler inyecta como si fueran preguntas internas
REMINDER_PROMPTS = {
    "breakfast": (
        f"Es hora del desayuno. Pregúntale a {NATHALIE_NAME} qué va a desayunar hoy. "
        "Si no ha desayunado, sugiérele opciones rápidas y nutritivas. Sé motivadora."
    ),
    "lunch": (
        f"Es hora del almuerzo. Pregúntale a {NATHALIE_NAME} qué va a almorzar. "
        "Si ya comió algo antes, celébralo. Sugiere opciones con proteína."
    ),
    "snack": (
        f"Es hora de un snack. Recuérdale a {NATHALIE_NAME} que comer entre comidas "
        "es importante para mantener energía. Sugiere opciones de snack."
    ),
    "dinner": (
        f"Es hora de la cena. Pregúntale a {NATHALIE_NAME} qué va a cenar. "
        "Revisa sus comidas del día y sugiere algo que complemente lo que ya comió."
    ),
    "checkin": (
        f"Es el check-in nocturno. Pregúntale a {NATHALIE_NAME} cómo se sintió hoy. "
        "Revisa sus comidas del día y dale feedback positivo. "
        "Si comió poco, anímala sin culpa para mañana."
    ),
}


async def _send_reminder(bot, meal_key: str):
    """Genera y envía un recordatorio proactivo."""
    logger.info(f"Disparando recordatorio: {meal_key}")

    internal_prompt = REMINDER_PROMPTS[meal_key]

    # Contexto nutricional relevante
    rag_context = retrieve(internal_prompt)

    # Generar respuesta (el cliente arma los mensajes internamente)
    response = chat(
        user_message=internal_prompt,
        rag_context=rag_context,
        history=get_recent_turns(),
        profile=get_profile(),
        today_meals=get_today_meals(),
    )
    logger.info(f"Recordatorio {meal_key}: {response[:60]}")

    # Guardar como turno del asistente
    save_turn("assistant", response, msg_type="reminder")

    # Enviar mensaje
    await bot.send_message(chat_id=NATHALIE_CHAT_ID, text=response)

    # Enviar sticker (aleatorio, sin llamada LLM extra)
    import os
    sticker_path = seleccionar_sticker(response)
    if sticker_path and os.path.isfile(sticker_path):
        ext = os.path.splitext(sticker_path)[1].lower()
        try:
            with open(sticker_path, "rb") as f:
                if ext == ".gif":
                    await bot.send_animation(chat_id=NATHALIE_CHAT_ID, animation=f)
                elif ext in {".jpg", ".jpeg", ".png", ".webp"}:
                    await bot.send_photo(chat_id=NATHALIE_CHAT_ID, photo=f)
                elif ext == ".mp4":
                    await bot.send_video(chat_id=NATHALIE_CHAT_ID, video=f)
        except Exception as e:
            logger.warning(f"Error enviando sticker: {e}")


def setup(app) -> AsyncIOScheduler:
    """Configura el scheduler con todos los recordatorios. Recibe la Application de Telegram."""
    bot = app.bot
    return _build_scheduler(bot)


def start_scheduler(bot) -> AsyncIOScheduler:
    """Arranca el scheduler con todos los recordatorios configurados."""
    return _build_scheduler(bot)


def _build_scheduler(bot) -> AsyncIOScheduler:
    """Construye y configura el scheduler sin arrancarlo."""
    tz = pytz.timezone(TIMEZONE)
    scheduler = AsyncIOScheduler(timezone=tz)

    for meal_key, time_config in SCHEDULE.items():
        trigger = CronTrigger(
            hour=time_config["hour"],
            minute=time_config["minute"],
            timezone=tz,
        )
        scheduler.add_job(
            _send_reminder,
            trigger=trigger,
            args=[bot, meal_key],
            id=f"reminder_{meal_key}",
            name=f"Recordatorio: {meal_key}",
            replace_existing=True,
        )
        logger.info(
            f"Recordatorio programado: {meal_key} a las "
            f"{time_config['hour']:02d}:{time_config['minute']:02d} ({TIMEZONE})"
        )

    return scheduler
