"""
Scheduler — envía recordatorios proactivos a cada usuario según SUS horarios.
Corre cada minuto y verifica qué usuarios necesitan recordatorio.
"""
import logging
import os
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

from config import TIMEZONE
from memory.store import (
    save_message, get_recent_messages, get_profile,
    format_today_for_prompt, get_today_total_kcal,
    get_all_chat_ids, get_user_reminders,
    get_user_settings, cleanup_old_messages,
    reset_daily_log,
)
from rag.vector_store import retrieve
from llm.llm_client import chat
from tools.sticker_manager import seleccionar_sticker

logger = logging.getLogger(__name__)

REMINDER_PROMPTS = {
    "breakfast": (
        "Es hora del desayuno. Pregúntale al usuario qué va a desayunar hoy. "
        "Si no ha desayunado, sugiérele opciones rápidas y nutritivas. Sé motivador(a)."
    ),
    "lunch": (
        "Es hora del almuerzo. Pregúntale al usuario qué va a almorzar. "
        "Si ya comió algo antes, celébralo. Sugiere opciones con proteína."
    ),
    "snack": (
        "Es hora de un snack. Recuérdale al usuario que comer entre comidas "
        "es importante para mantener energía. Sugiere opciones de snack."
    ),
    "dinner": (
        "Es hora de la cena. Pregúntale al usuario qué va a cenar. "
        "Revisa sus comidas del día y sugiere algo que complemente lo que ya comió."
    ),
    "checkin": (
        "Es el check-in nocturno. Pregúntale al usuario cómo se sintió hoy. "
        "Revisa sus comidas del día y dale feedback positivo. "
        "Si comió poco, anímalo sin culpa para mañana."
    ),
}


async def _send_reminder_to_user(bot, chat_id: int, slot: str):
    """Genera y envía un recordatorio personalizado a un usuario."""
    logger.info("Enviando recordatorio %s a %d", slot, chat_id)

    internal_prompt = REMINDER_PROMPTS.get(slot, REMINDER_PROMPTS["checkin"])
    rag_context = retrieve(internal_prompt)
    today_meals_text = format_today_for_prompt(chat_id)
    profile = get_profile(chat_id)
    total_hoy = get_today_total_kcal(chat_id)

    settings = get_user_settings(chat_id)
    response = chat(
        user_message=internal_prompt,
        rag_context=rag_context,
        history=get_recent_messages(chat_id),
        profile=profile,
        settings=settings,
        today_meals=today_meals_text,
        total_hoy=total_hoy,
    )
    logger.info("Recordatorio %s para %d: %s", slot, chat_id, response[:60])

    save_message(chat_id, "assistant", response)

    try:
        await bot.send_message(chat_id=chat_id, text=response)
    except Exception as e:
        logger.error("Error enviando mensaje a %d: %s", chat_id, e)
        return

    sticker_path = seleccionar_sticker(response)
    if sticker_path and os.path.isfile(sticker_path):
        ext = os.path.splitext(sticker_path)[1].lower()
        try:
            with open(sticker_path, "rb") as f:
                if ext == ".gif":
                    await bot.send_animation(chat_id=chat_id, animation=f)
                elif ext in {".jpg", ".jpeg", ".png", ".webp"}:
                    await bot.send_photo(chat_id=chat_id, photo=f)
                elif ext == ".mp4":
                    await bot.send_video(chat_id=chat_id, video=f)
        except Exception as e:
            logger.warning("Error enviando sticker a %d: %s", chat_id, e)


def setup(app) -> AsyncIOScheduler:
    """Configura el scheduler que revisa recordatorios cada minuto."""
    bot = app.bot
    tz = pytz.timezone(TIMEZONE)
    scheduler = AsyncIOScheduler(timezone=tz)

    async def check_reminders():
        """Corre cada minuto y dispara recordatorios según horario de cada usuario."""
        from llm.time_client import get_lima_time
        try:
            time_str = get_lima_time()
            # Formato: "sabado 15/03/2026 14:30"
            now_hm = time_str.split()[2][:5]  # "HH:MM"
        except (IndexError, Exception):
            return

        chat_ids = get_all_chat_ids()
        for chat_id in chat_ids:
            reminders = get_user_reminders(chat_id)
            if not reminders.get("active", True):
                continue

            slot_map = {
                "breakfast": reminders["breakfast"],
                "lunch": reminders["lunch"],
                "snack": reminders["snack"],
                "dinner": reminders["dinner"],
                "checkin": reminders["checkin"],
            }
            for slot, slot_time in slot_map.items():
                if now_hm == slot_time:
                    await _send_reminder_to_user(bot, chat_id, slot)

    async def hourly_cleanup():
        """Borra mensajes con más de 8 horas."""
        cleanup_old_messages()
        logger.info("Limpieza de mensajes antiguos completada")

    async def midnight_reset():
        """Borra el daily_log del día anterior para todos los usuarios."""
        chat_ids = get_all_chat_ids()
        for cid in chat_ids:
            reset_daily_log(cid)
        logger.info("Reset diario completado para %d usuarios", len(chat_ids))

    async def weekly_context_update():
        """Regenera el contexto de todos los usuarios cada domingo."""
        from tools.context_builder import generate_user_context
        from rag.vector_store import index_user_context

        chat_ids = get_all_chat_ids()
        for cid in chat_ids:
            try:
                context = generate_user_context(cid)
                index_user_context(cid, context)
                logger.info("Contexto actualizado para chat_id: %d", cid)
            except Exception as e:
                logger.error("Error actualizando contexto %d: %s", cid, e)
        logger.info("Contextos semanales actualizados: %d usuarios", len(chat_ids))

    scheduler.add_job(
        weekly_context_update,
        trigger="cron",
        day_of_week="sun",
        hour=3, minute=0,
        id="weekly_context",
        name="Regenerar contextos de usuarios",
        replace_existing=True,
    )
    scheduler.add_job(
        check_reminders,
        trigger="interval",
        minutes=1,
        id="check_reminders",
        name="Verificar recordatorios personalizados",
        replace_existing=True,
    )
    scheduler.add_job(
        hourly_cleanup,
        trigger="interval",
        hours=1,
        id="hourly_cleanup",
        name="Limpieza de mensajes >8h",
        replace_existing=True,
    )
    scheduler.add_job(
        midnight_reset,
        trigger="cron",
        hour=0, minute=5,
        id="midnight_reset",
        name="Reset daily_log a medianoche",
        replace_existing=True,
    )
    logger.info("Scheduler iniciado — recordatorios cada minuto, cleanup cada hora, reset a medianoche")

    return scheduler
