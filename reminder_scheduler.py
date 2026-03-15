"""
scheduler/reminder_scheduler.py
5 recordatorios diarios automáticos con APScheduler.
Los mensajes los genera Gemini en tiempo real para que no sean siempre iguales.
"""

import logging
import os
import random

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import (
    TIMEZONE,
    SCHEDULE_BREAKFAST,
    SCHEDULE_LUNCH,
    SCHEDULE_SNACK,
    SCHEDULE_DINNER,
    SCHEDULE_NIGHT_CHECKIN,
    NATHALIE_NAME,
    NATHALIE_TDEE,
)

logger = logging.getLogger(__name__)

# Chat IDs registrados (se poblan en runtime cuando Nathalie escribe)
_registered_chat_ids: set[int] = set()


def register_chat(chat_id: int) -> None:
    _registered_chat_ids.add(chat_id)


def _parse_hm(t: str) -> tuple[int, int]:
    h, m = t.split(":")
    return int(h), int(m)


# ── Textos de recordatorio (variados para no ser repetitivos) ─────────────────

REMINDERS = {
    "breakfast": [
        f"☀️ Buenos días {NATHALIE_NAME}! Ya es hora del desayuno. Tu cuerpo lleva horas en ayunas y necesita combustible. ¿Qué vas a comer hoy?",
        f"🌅 Ey {NATHALIE_NAME}! El desayuno es tu primera oportunidad de sumar calorías. Sin él, el cuerpo empieza a usar músculo como energía. ¿Ya tienes algo en mente?",
        f"🍳 {NATHALIE_NAME}, hora de desayunar! Recuerda: café solo no es desayuno. Necesitas proteína + carbohidrato. ¿Tienes huevos en casa?",
    ],
    "lunch": [
        f"🥗 Hora del almuerzo {NATHALIE_NAME}! Proteína + papa o quinua como mínimo. ¿Ya estás comiendo o todavía?",
        f"💪 {NATHALIE_NAME}, son las {SCHEDULE_LUNCH}. Tu cuerpo lleva horas trabajando y necesita combustible real. ¡A almorzar!",
        f"🍽️ Almuerzo time! {NATHALIE_NAME}, recuerda que saltear el almuerzo profundiza el déficit calórico. ¿Qué tienes para comer?",
    ],
    "snack": [
        f"⚡ {NATHALIE_NAME}, snack pre-gym! Una banana con mantequilla de maní o un yogur griego te dan la energía que necesitas para rendir.",
        f"🏋️ Pre-entreno {NATHALIE_NAME}! Come algo ahora o tu cuerpo usará músculo como combustible en el gym. ¿Qué tienes a mano?",
        f"🍌 {NATHALIE_NAME}, en una hora (aprox) empieza el gym. Come tu snack pre-entrenamiento ahora. ¡No vayas en ayunas!",
    ],
    "dinner": [
        f"🌙 {NATHALIE_NAME}, hora de cenar. Hoy NO puede ser 'lo que haya'. Necesitas proteína + carbohidrato complejo. ¿Qué tienes en casa?",
        f"🍽️ Cena time! {NATHALIE_NAME}, la cena es clave para recuperar músculo mientras duermes. ¿Tienes algo preparado o necesitas ideas?",
        f"🌜 {NATHALIE_NAME}, no te vayas a dormir sin cenar bien. Mándame foto de tu refri si necesitas ideas de qué preparar 📸",
    ],
    "night_checkin": [
        f"📋 Check-in nocturno {NATHALIE_NAME}! ¿Cómo estuvo el día? ¿Pudiste hacer las 4 comidas principales? ¿Cómo te sientes de energía?",
        f"🌙 {NATHALIE_NAME}, antes de dormir: ¿cómo fue la alimentación hoy? ¿Lograste comer bien o fue un día difícil?",
        f"✨ {NATHALIE_NAME}, cerrando el día: ¿te acuerdas de todo lo que comiste hoy? Cuéntame y vemos si llegaste a la meta calórica.",
    ],
}


async def _send_reminder(bot, key: str) -> None:
    if not _registered_chat_ids:
        return

    text = random.choice(REMINDERS[key])

    # Importamos aquí para evitar circular imports
    from media.sticker_picker import pick as pick_sticker

    media_path = pick_sticker("motivacional")

    for chat_id in _registered_chat_ids:
        try:
            await bot.send_message(chat_id=chat_id, text=text)
            if media_path and os.path.isfile(media_path):
                ext = os.path.splitext(media_path)[1].lower()
                with open(media_path, "rb") as f:
                    if ext == ".gif":
                        await bot.send_animation(chat_id=chat_id, animation=f)
                    elif ext in {".jpg", ".jpeg", ".png", ".webp"}:
                        await bot.send_photo(chat_id=chat_id, photo=f)
                    elif ext == ".mp4":
                        await bot.send_video(chat_id=chat_id, video=f)
        except Exception as e:
            logger.error("Error enviando recordatorio '%s' a %d: %s", key, chat_id, e)


def setup(app) -> AsyncIOScheduler:
    """
    Configura el scheduler y retorna la instancia lista para arrancar.
    app: la Application de python-telegram-bot
    """
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    jobs = [
        ("breakfast",    SCHEDULE_BREAKFAST),
        ("lunch",        SCHEDULE_LUNCH),
        ("snack",        SCHEDULE_SNACK),
        ("dinner",       SCHEDULE_DINNER),
        ("night_checkin",SCHEDULE_NIGHT_CHECKIN),
    ]

    for key, time_str in jobs:
        h, m = _parse_hm(time_str)

        async def _job(key=key):
            await _send_reminder(app.bot, key)

        scheduler.add_job(
            _job,
            trigger=CronTrigger(hour=h, minute=m, timezone=TIMEZONE),
            id=key,
            replace_existing=True,
        )
        logger.info("Recordatorio '%s' programado todos los días a las %s (%s)", key, time_str, TIMEZONE)

    return scheduler
