"""
bot/telegram_handler.py
Todos los handlers de Telegram.
Comandos: /start  /perfil  /help  /resumen  /dieta
Mensajes: texto libre, foto (refri)
"""

import logging
import os

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from llm.gemini_client import generate_text, generate_vision, classify_tone
from rag.vector_store import query as rag_query
from memory.store import (
    save_message,
    get_history,
    format_profile_summary,
    format_today_for_prompt,
    get_weekly_summary,
    log_meal,
)
from media.sticker_picker import pick as pick_sticker
from scheduler.reminder_scheduler import register_chat
from config import NATHALIE_NAME, NATHALIE_TDEE

logger = logging.getLogger(__name__)


# ── Utilidades ────────────────────────────────────────────────────────────────

SYSTEM_PERSONA = f"""Eres la asistente nutricional personal de {NATHALIE_NAME}, 21 años.
Su mayor problema: come MUY POCO para su nivel de actividad (gym 4x/sem + baile + trabajo).
Meta: llegar a ~{NATHALIE_TDEE} kcal/día para recuperar energía, libido y rendimiento.
Tono: cálido, directo, como una amiga que sabe de nutrición. Sin sermones.
Respuestas CORTAS (máx 3 párrafos). En español. Sin listas largas.
Siempre termina con UNA recomendación concreta y accionable."""


def _build_prompt(user_msg: str, rag_ctx: str, today_meals: str, history: list[dict]) -> str:
    hist_text = ""
    for t in history[-8:]:
        label = NATHALIE_NAME if t["role"] == "user" else "Asistente"
        hist_text += f"{label}: {t['content']}\n"

    rag_block = f"\n=== GUÍA NUTRICIONAL (relevante) ===\n{rag_ctx}\n" if rag_ctx else ""

    return f"""{SYSTEM_PERSONA}

=== PERFIL ===
{format_profile_summary()}

=== COMIDAS DE HOY ===
{today_meals}
{rag_block}
=== CONVERSACIÓN RECIENTE ===
{hist_text}
=== MENSAJE ACTUAL ===
{NATHALIE_NAME}: {user_msg}

Asistente:"""


def _build_fridge_prompt(rag_ctx: str) -> str:
    rag_block = f"\n=== GUÍA NUTRICIONAL ===\n{rag_ctx}\n" if rag_ctx else ""
    return f"""{SYSTEM_PERSONA}

=== PERFIL ===
{format_profile_summary()}
{rag_block}
=== TAREA ===
{NATHALIE_NAME} te mandó una foto de su refrigeradora.
1. Lista brevemente lo que ves (máx 4 items).
2. Indica qué le FALTA comprar para los próximos 3 días (máx 5 items concretos con cantidad).
3. Sugiere UNA comida que puede preparar HOY con lo que ya tiene.
Respuesta corta y práctica.

Asistente:"""


async def _send_with_sticker(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    tone: str,
) -> None:
    await update.effective_message.reply_text(text)
    media_path = pick_sticker(tone)
    if media_path and os.path.isfile(media_path):
        ext = os.path.splitext(media_path)[1].lower()
        try:
            with open(media_path, "rb") as f:
                if ext == ".gif":
                    await update.effective_message.reply_animation(animation=f)
                elif ext in {".jpg", ".jpeg", ".png", ".webp"}:
                    await update.effective_message.reply_photo(photo=f)
                elif ext == ".mp4":
                    await update.effective_message.reply_video(video=f)
        except Exception as e:
            logger.warning("No se pudo enviar sticker: %s", e)


# ── Comandos ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_chat(update.effective_chat.id)
    await update.message.reply_text(
        f"¡Hola {NATHALIE_NAME}! 👋 Soy tu asistente nutricional.\n\n"
        "Puedes escribirme sobre lo que comiste, cómo te sientes, "
        "o mandarme una 📸 foto de tu refri para ver qué te falta comprar.\n\n"
        "Comandos disponibles:\n"
        "/perfil → ver tu perfil actual\n"
        "/resumen → resumen semanal de comidas\n"
        "/dieta → ver el plan de 7 días\n"
        "/help → ayuda\n\n"
        "¡Vamos a que te sientas con energía! 💪"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Cómo puedo ayudarte:\n\n"
        "• Escríbeme qué comiste y te digo si vas bien con las calorías.\n"
        "• Mándame una foto de tu refri y te digo qué comprar.\n"
        "• Cuéntame cómo te sientes (cansancio, dolores de cabeza, etc.).\n\n"
        "/perfil → ver tu perfil\n"
        "/resumen → resumen de esta semana\n"
        "/dieta → plan de comidas de 7 días"
    )


async def cmd_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    summary = format_profile_summary()
    today   = format_today_for_prompt()
    await update.message.reply_text(
        f"📋 Tu perfil:\n\n{summary}\n\n"
        f"🍽️ Comidas registradas hoy:\n{today}"
    )


async def cmd_resumen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    weekly = get_weekly_summary()
    if not weekly:
        await update.message.reply_text(
            "Aún no hay comidas registradas esta semana. "
            "Cuéntame qué comiste y las voy anotando 😊"
        )
        return

    lines = [f"📊 Resumen de la semana:\n"]
    for day, meals in sorted(weekly.items()):
        total_kcal = sum(m["kcal_est"] for m in meals if m["kcal_est"])
        lines.append(f"\n📅 {day}")
        for m in meals:
            kcal_str = f" (~{m['kcal_est']} kcal)" if m["kcal_est"] else ""
            lines.append(f"  • {m['meal_type']}: {m['description']}{kcal_str}")
        if total_kcal:
            lines.append(f"  Total: ~{total_kcal} kcal")

    await update.message.reply_text("\n".join(lines))


async def cmd_dieta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.chat.send_action("typing")
    rag_ctx = rag_query("plan de comidas 7 días dieta modelo recuperación déficit calórico")
    prompt  = f"""{SYSTEM_PERSONA}

=== PERFIL ===
{format_profile_summary()}

{f"=== GUÍA NUTRICIONAL ==={chr(10)}{rag_ctx}" if rag_ctx else ""}

=== TAREA ===
Genera un plan de comidas resumido para los próximos 7 días para {NATHALIE_NAME}.
Objetivo: alcanzar ~{NATHALIE_TDEE} kcal/día.
Formato: un párrafo por día con las 4 comidas principales.
Sé específico con alimentos y porciones. Usa ingredientes fáciles de conseguir en Lima, Perú.

Asistente:"""

    response = generate_text(prompt)
    save_message("assistant", response)
    await _send_with_sticker(update, context, response, "motivacional")


# ── Mensajes de texto libre ───────────────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_chat(update.effective_chat.id)
    user_text = update.message.text.strip()
    await update.message.chat.send_action("typing")

    history    = get_history()
    rag_ctx    = rag_query(user_text)
    today      = format_today_for_prompt()
    prompt     = _build_prompt(user_text, rag_ctx, today, history)
    response   = generate_text(prompt)
    tone       = classify_tone(response)

    save_message("user",      user_text)
    save_message("assistant", response)

    await _send_with_sticker(update, context, response, tone)


# ── Fotos ─────────────────────────────────────────────────────────────────────

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_chat(update.effective_chat.id)
    await update.message.chat.send_action("typing")

    photo     = update.message.photo[-1]
    file      = await context.bot.get_file(photo.file_id)
    img_bytes = await file.download_as_bytearray()
    caption   = update.message.caption or ""

    rag_ctx  = rag_query("lista de compras alimentos saludables nevera refrigeradora")
    prompt   = _build_fridge_prompt(rag_ctx)
    response = generate_vision(prompt, bytes(img_bytes), "image/jpeg")
    tone     = classify_tone(response)

    save_message("user",      f"[Foto de refrigeradora] {caption}".strip())
    save_message("assistant", response)

    await _send_with_sticker(update, context, response, tone)


async def handle_photo_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Imagen enviada como archivo (no comprimida)."""
    register_chat(update.effective_chat.id)
    await update.message.chat.send_action("typing")

    doc       = update.message.document
    file      = await context.bot.get_file(doc.file_id)
    img_bytes = await file.download_as_bytearray()
    mime_type = doc.mime_type or "image/jpeg"
    caption   = update.message.caption or ""

    rag_ctx  = rag_query("lista de compras alimentos saludables nevera refrigeradora")
    prompt   = _build_fridge_prompt(rag_ctx)
    response = generate_vision(prompt, bytes(img_bytes), mime_type)
    tone     = classify_tone(response)

    save_message("user",      f"[Foto de refrigeradora] {caption}".strip())
    save_message("assistant", response)

    await _send_with_sticker(update, context, response, tone)


# ── Registro de handlers ──────────────────────────────────────────────────────

def register_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("perfil",  cmd_perfil))
    app.add_handler(CommandHandler("resumen", cmd_resumen))
    app.add_handler(CommandHandler("dieta",   cmd_dieta))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.IMAGE, handle_photo_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
