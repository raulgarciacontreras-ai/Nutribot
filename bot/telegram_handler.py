"""
Telegram Handler — recibe mensajes y fotos, orquesta la respuesta.
Es el puente entre Telegram ↔ LLM ↔ RAG ↔ Memory ↔ Stickers.
"""
import logging
import os
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import NATHALIE_CHAT_ID, BOT_NAME, NATHALIE_NAME
from memory.store import (
    save_turn, get_recent_turns, get_profile, update_profile,
    get_today_meals, log_meal, get_today_total_kcal,
)
from rag.vector_store import retrieve
from llm.llm_client import chat, chat_with_image
from tools.sticker_manager import seleccionar_sticker
from tools.meal_tracker import detectar_reporte_comida, detectar_slot_comida, formato_para_prompt
from tools.calocalc_tool import analizar_texto
from tools.food_search import buscar_en_internet

logger = logging.getLogger(__name__)


def _is_nathalie(update: Update) -> bool:
    """Solo responde a Nathalie. Loguea siempre para diagnóstico."""
    chat_id = update.effective_chat.id
    ok = chat_id == NATHALIE_CHAT_ID
    if not ok:
        logger.warning(
            "Mensaje ignorado: chat_id=%s (esperado=%s)", chat_id, NATHALIE_CHAT_ID
        )
    return ok


# ── Comandos ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    logger.info("cmd_start de chat_id: %s", update.effective_chat.id)
    if not _is_nathalie(update):
        return
    try:
        profile = get_profile()

        # Solo mostrar onboarding si es primera vez (sin perfil)
        if not profile or not profile.get("name") or profile.get("name") == "Nathalie":
            await update.message.reply_text(
                f"Hola! Soy {BOT_NAME}, tu asistente nutricional\n\n"
                f"Ya tengo tu perfil cargado:\n"
                f"  {NATHALIE_NAME}, 21 anos, 58kg, 1.70m\n"
                f"  Meta: ~2,400 kcal/dia\n\n"
                "Puedes escribirme lo que comiste, mandarme foto "
                "de tu refri, o preguntarme lo que quieras. Empecemos!"
            )
        else:
            await update.message.reply_text(
                f"Hola de nuevo {profile.get('name')}! En que te ayudo?"
            )

        sticker_path = seleccionar_sticker("Bienvenida! Felicitacion por empezar!")
        if sticker_path and os.path.isfile(sticker_path):
            ext = os.path.splitext(sticker_path)[1].lower()
            try:
                with open(sticker_path, "rb") as f:
                    if ext == ".gif":
                        await update.message.reply_animation(animation=f)
                    elif ext in {".jpg", ".jpeg", ".png", ".webp"}:
                        await update.message.reply_photo(photo=f)
                    elif ext == ".mp4":
                        await update.message.reply_video(video=f)
            except Exception as e:
                logger.warning("No se pudo enviar sticker: %s", e)
    except Exception as e:
        logger.error("Error en cmd_start: %s", e, exc_info=True)


async def cmd_perfil(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    logger.info("cmd_perfil de chat_id: %s", update.effective_chat.id)
    if not _is_nathalie(update):
        return
    try:
        profile = get_profile()
        today_meals = get_today_meals()

        if not profile:
            logger.info("cmd_perfil: no hay perfil en DB, mostrando mensaje inicial")
            await update.message.reply_text(
                f"Hola {NATHALIE_NAME}! Todavia no tengo tu perfil guardado.\n\n"
                "Cuentame estos datos y los guardo:\n"
                "- Peso (ej: 58 kg)\n"
                "- Altura (ej: 165 cm)\n"
                "- Edad\n"
                "- Nivel de actividad (ej: alta, entreno 5 dias/semana)\n"
                "- Alergias o restricciones\n\n"
                "Escribeme todo junto o de a poco, como quieras!"
            )
            return

        # Formatear perfil sin Markdown para evitar errores de parseo
        field_names = {
            "name": "Nombre",
            "weight_kg": "Peso (kg)",
            "height_cm": "Altura (cm)",
            "age": "Edad",
            "activity": "Actividad",
            "goal": "Objetivo",
            "restrictions": "Restricciones",
            "symptoms": "Sintomas",
            "notes": "Notas",
        }
        lines = []
        for k, v in profile.items():
            if v and k not in ("id", "updated_at"):
                label = field_names.get(k, k)
                lines.append(f"  {label}: {v}")

        text = f"Perfil de {NATHALIE_NAME}:\n\n" + "\n".join(lines)

        if today_meals:
            meals_str = "\n".join(f"  - {m['meal_type']}: {m['description']}" for m in today_meals)
            text += f"\n\nComidas de hoy:\n{meals_str}"
        else:
            text += "\n\nHoy no has registrado comidas aun."

        logger.info("cmd_perfil enviando: %s", text[:100])
        await update.message.reply_text(text)
    except Exception as e:
        logger.error("Error en cmd_perfil: %s", e, exc_info=True)
        await update.message.reply_text(f"Error al cargar perfil: {type(e).__name__}: {e}")


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    logger.info("cmd_help de chat_id: %s", update.effective_chat.id)
    if not _is_nathalie(update):
        return
    await update.message.reply_text(
        "Esto puedo hacer por ti:\n\n"
        "Escribeme cualquier duda de nutricion\n"
        "Mandame foto de tu refri -> te sugiero recetas\n"
        "Cuentame que comiste -> lo registro\n\n"
        "/perfil — Ver tu perfil\n"
        "/start — Bienvenida"
    )


# ── Mensajes de texto ────────────────────────────────────────────────────────

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    logger.info("handle_text de chat_id: %s", update.effective_chat.id)
    if not _is_nathalie(update):
        return

    try:
        user_text = update.message.text.strip()
        logger.info("Nathalie dice: %s", user_text[:80])

        # Indicador de "escribiendo..."
        await update.message.chat.send_action(ChatAction.TYPING)

        # Guardar turno del usuario
        save_turn("user", user_text)

        # Detectar si reporta comida y registrarla con CaloCalc
        meal_context = ""
        if detectar_reporte_comida(user_text):
            resultado = analizar_texto(user_text)
            if resultado["encontro"]:
                slot = detectar_slot_comida(user_text)
                kcal = resultado["totales"]["kcal"]
                log_meal(meal_type=slot, description=user_text[:200], est_cal=kcal)
                total_hoy = get_today_total_kcal()
                meal_context = formato_para_prompt(user_text, total_hoy - kcal, 2400)
                logger.info("Comida registrada: %s, ~%d kcal, total hoy: %d", slot, kcal, total_hoy)
            else:
                # No encontro en DB local — buscar en internet
                internet_result = buscar_en_internet(user_text[:60])
                if internet_result:
                    meal_context = (
                        f"=== ENCONTRADO EN INTERNET ===\n"
                        f"Alimento: {internet_result['nombre']}\n"
                        f"Por 100g: {internet_result['kcal_100g']} kcal | "
                        f"P:{internet_result['proteina']}g C:{internet_result['carbos']}g "
                        f"G:{internet_result['grasas']}g\n"
                        f"Fuente: Open Food Facts\n"
                        f"Pregunta a Nathalie la cantidad para calcular el total."
                    )
                    logger.info("Alimento encontrado en internet: %s", internet_result['nombre'])
                else:
                    meal_context = (
                        "ALIMENTO_DESCONOCIDO: No se encontro en ninguna base de datos.\n"
                        "INSTRUCCION CRITICA: Dile a Nathalie exactamente esto:\n"
                        "'No reconozco ese alimento. Me puedes mandar una foto "
                        "del producto o de la etiqueta nutricional? "
                        "Asi puedo darte la informacion exacta.'"
                    )
                    logger.info("Alimento no encontrado, pidiendo foto")

        # Buscar contexto nutricional relevante
        rag_context = retrieve(user_text)
        logger.info("RAG context: %d chars", len(rag_context))

        # Combinar contextos
        if meal_context:
            rag_context = meal_context + "\n\n" + rag_context

        # Generar respuesta
        logger.info("Llamando a chat()...")
        response = chat(
            user_message=user_text,
            rag_context=rag_context,
            history=get_recent_turns(),
            profile=get_profile(),
            today_meals=get_today_meals(),
        )
        logger.info("%s responde: %s", BOT_NAME, response[:80])

        # Guardar turno del asistente
        save_turn("assistant", response)

        # Enviar respuesta + sticker (aleatorio, sin llamada LLM extra)
        await _send_media(update, ctx, response)

    except Exception as e:
        logger.error("Error COMPLETO en handle_text:", exc_info=True)
        await update.message.reply_text(f"Error: {type(e).__name__}: {e}")


# ── Fotos (refrigerador, platos, etc.) ───────────────────────────────────────

async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    logger.info("handle_photo de chat_id: %s", update.effective_chat.id)
    if not _is_nathalie(update):
        return

    try:
        caption = update.message.caption or ""
        logger.info("Nathalie envio foto: %s", caption[:50])

        await update.message.chat.send_action(ChatAction.TYPING)

        # Descargar la foto en mayor resolucion
        photo = update.message.photo[-1]
        file = await ctx.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()

        save_turn("user", f"[FOTO] {caption}", msg_type="photo")

        # Detectar si es foto de alimento individual vs foto de refri
        palabras_refri = [
            "refri", "nevera", "refrigerador", "heladera",
            "que hay", "comprar", "despensa",
        ]
        es_refri = any(p in caption.lower() for p in palabras_refri)

        # Revisar si el bot pidio foto de un alimento
        history = get_recent_turns(4)
        ultimo_bot = next(
            (t["content"] for t in reversed(history) if t["role"] == "assistant"), ""
        )
        pidio_foto_alimento = (
            "foto del" in ultimo_bot.lower()
            or "etiqueta" in ultimo_bot.lower()
            or "foto de" in ultimo_bot.lower()
        )

        # Armar prompt segun contexto
        prompt_parts = []
        profile = get_profile()
        if profile:
            info = ", ".join(f"{k}: {v}" for k, v in profile.items() if v and k != "id")
            prompt_parts.append(f"[PERFIL] {info}")

        if pidio_foto_alimento and not es_refri:
            # Foto de alimento desconocido
            prompt_parts.append(
                "[TAREA: IDENTIFICAR ALIMENTO EN FOTO]\n"
                "Nathalie te mando una foto de un alimento que no reconociste antes.\n"
                "1. Identifica exactamente que alimento es\n"
                "2. Si ves etiqueta nutricional, lee las calorias por porcion\n"
                "3. Si no hay etiqueta, estima las calorias por 100g\n"
                "4. Preguntale cuanto comio para calcular el total\n"
                "Formato: 'Lo vi! Es [nombre]. Por cada 100g tiene aprox [X] kcal. "
                "Cuanto comiste mas o menos?'"
            )
            prompt_parts.append(caption or "Nathalie te envio esta foto de un alimento. Identificalo.")
            logger.info("Modo: foto de alimento individual")
        else:
            # Foto de refri (comportamiento normal)
            rag_context = retrieve(caption or "analisis de refrigerador alimentos disponibles")
            if rag_context:
                prompt_parts.append(f"[GUIA NUTRICIONAL]\n{rag_context}")
            prompt_parts.append(
                caption or "Nathalie te envio esta foto. Analizala y dale consejos nutricionales."
            )
            logger.info("Modo: foto de refrigerador/general")

        vision_prompt = "\n\n".join(prompt_parts)

        # Groq Vision
        logger.info("Llamando a chat_with_image()...")
        response = chat_with_image(
            prompt=vision_prompt,
            image_bytes=bytes(image_bytes),
            mime_type="image/jpeg",
        )
        logger.info("%s responde (foto): %s", BOT_NAME, response[:80])

        save_turn("assistant", response)

        await _send_media(update, ctx, response)

    except Exception as e:
        logger.error("Error en handle_photo: %s", e, exc_info=True)
        await update.message.reply_text(f"Error procesando foto: {e}")


# ── Envio de sticker/media ───────────────────────────────────────────────────

async def _send_media(update, context, response_text, tone=None):
    await update.effective_message.reply_text(response_text)
    sticker_path = seleccionar_sticker(response_text)
    if sticker_path and os.path.isfile(sticker_path):
        ext = os.path.splitext(sticker_path)[1].lower()
        try:
            with open(sticker_path, "rb") as f:
                if ext == ".gif":
                    await update.effective_message.reply_animation(animation=f)
                elif ext in {".jpg", ".jpeg", ".png", ".webp"}:
                    await update.effective_message.reply_photo(photo=f)
                elif ext == ".mp4":
                    await update.effective_message.reply_video(video=f)
            logger.info("Sticker enviado")
        except Exception as e:
            logger.warning("No se pudo enviar sticker: %s", e)


# ── Registrar handlers ──────────────────────────────────────────────────────

def register_handlers(app: Application):
    """Registra todos los handlers en la aplicacion de Telegram."""
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("perfil", cmd_perfil))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info(
        "%s handlers registrados (NATHALIE_CHAT_ID=%s): /start, /perfil, /help, texto, foto",
        BOT_NAME, NATHALIE_CHAT_ID,
    )
