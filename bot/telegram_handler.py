"""
Telegram Handler — recibe mensajes y fotos, orquesta la respuesta.
Es el puente entre Telegram ↔ LLM ↔ RAG ↔ Memory ↔ Stickers.
Multi-usuario: cualquier usuario puede registrarse con /start.
"""
import logging
import os
import re
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import BOT_NAME
from memory.store import (
    save_message, get_recent_messages, get_profile, update_profile,
    get_today_meals, log_meal, get_today_total_kcal, get_today_summary,
    format_today_for_prompt, format_profile_summary,
    register_user, get_goals, add_goal,
    get_user_reminders, save_user_reminders,
    get_user_settings, save_user_settings,
)
from rag.vector_store import retrieve
from llm.llm_client import chat, chat_with_image, _call_with_fallback
from tools.sticker_manager import seleccionar_sticker
from tools.meal_tracker import detectar_reporte_comida, detectar_slot_comida, formato_para_prompt
from tools.calocalc_tool import analizar_texto
from tools.food_search import buscar_en_internet
from bot.admin_handler import register_admin_handlers
from tools.restaurant_finder import (
    buscar_restaurantes_cercanos, buscar_por_texto,
    seleccionar_mejores_opciones, formatear_para_telegram,
    get_detalles_restaurante, es_solicitud_delivery,
)
from tools.context_builder import update_context_if_needed
from rag.vector_store import query_user_context
from config import GOOGLE_PLACES_API_KEY

import json as _json

logger = logging.getLogger(__name__)


# ── Distritos de Lima ────────────────────────────────────────────────────────

DISTRITOS_LIMA = [
    "miraflores", "san isidro", "surco", "santiago de surco", "la molina",
    "barranco", "san borja", "jesús maría", "jesus maria", "lince",
    "pueblo libre", "magdalena", "san miguel", "lima", "callao",
    "san martín de porres", "san martin de porres", "los olivos",
    "independencia", "comas", "ate", "santa anita", "la victoria",
    "breña", "rimac", "rímac", "chorrillos", "villa maría",
    "villa el salvador", "lurín", "lurin", "pachacamac", "carabayllo",
    "puente piedra", "surquillo", "monterrico", "chacarilla",
]


def _detectar_distrito(texto: str) -> str | None:
    """Detecta si el texto menciona un distrito de Lima. Retorna el nombre o None."""
    texto_lower = texto.lower()
    for distrito in sorted(DISTRITOS_LIMA, key=len, reverse=True):
        if distrito in texto_lower:
            return distrito.title()
    return None


# ── Extracción de kcal de respuesta del LLM ──────────────────────────────────

def _extraer_kcal_de_respuesta(response_text: str) -> int | None:
    """Extrae el total de kcal que el LLM menciona en su respuesta."""
    patrones = [
        r'(\d{3,4})\s*kcal\s*consumidas',
        r'total\s+de\s+(\d{3,4})\s*kcal',
        r'llevas\s+(\d{3,4})\s*kcal',
        r'consumido\s+(\d{3,4})\s*kcal',
        r'(\d{3,4})\s*kcal\s*hoy',
        r'registr[eé]\s+(\d{3,4})\s*kcal',
        r'aproximadamente\s+(\d{3,4})\s*kcal',
        r'(\d{3,4})\s*kcal\s*(?:en total|aprox)',
        r'sum[aó]\s+(\d{3,4})\s*kcal',
    ]
    for patron in patrones:
        match = re.search(patron, response_text.lower())
        if match:
            return int(match.group(1))
    return None


# ── Extracción de datos de perfil ────────────────────────────────────────────

def _extraer_perfil(texto: str) -> dict:
    """Extrae edad, peso, altura, sexo, objetivo y actividad de texto libre."""
    datos = {}

    # Edad
    edad = re.search(r'(\d{1,2})\s*(?:años?|anos?)', texto, re.IGNORECASE)
    if edad:
        val = int(edad.group(1))
        if 10 <= val <= 100:
            datos["age"] = str(val)

    # Peso
    peso = re.search(r'(\d{2,3}(?:[.,]\d)?)\s*kg', texto, re.IGNORECASE)
    if peso:
        datos["weight_kg"] = peso.group(1).replace(",", ".")

    # Altura — todos los formatos posibles
    # 1.65m, 1,65m, 1.65cm (error común), 165cm, 165, "altura 1.65"
    altura = re.search(
        r'(?:altura[:\s]+)?'
        r'(?:'
        r'(1[.,][5-9]\d)\s*(?:cm|m)?'
        r'|'
        r'(1[5-9]\d)\s*cm'
        r')',
        texto, re.IGNORECASE,
    )
    if altura:
        if altura.group(1):
            val = altura.group(1).replace(",", ".")
            cm = int(float(val) * 100)
            datos["height_cm"] = str(cm)
        elif altura.group(2):
            datos["height_cm"] = altura.group(2)

    # Sexo
    if re.search(r'\b(mujer|femenino|female)\b', texto, re.IGNORECASE):
        datos["sexo"] = "femenino"
    elif re.search(r'\b(hombre|masculino|male)\b', texto, re.IGNORECASE):
        datos["sexo"] = "masculino"

    # Objetivo
    objetivos = {
        "perder peso": ["perder", "bajar", "adelgazar", "bajar de peso",
                        "deficit", "hipocal", "kilos"],
        "ganar músculo": ["ganar músculo", "masa muscular", "volumen", "bulk"],
        "más energía": ["energía", "energia", "cansancio", "fatiga", "lea", "reds"],
        "mantenimiento": ["mantener", "mantenimiento", "maintenance"],
        "ganar peso": ["ganar peso", "subir de peso", "hipercal"],
    }
    for obj, keywords in objetivos.items():
        if any(kw in texto.lower() for kw in keywords):
            datos["objetivo"] = obj
            break

    # Actividad
    actividades = {
        "sedentario": ["sedentario", "no hago ejercicio", "poco movimiento"],
        "ligeramente activo": ["camino", "1-2 veces", "poco ejercicio"],
        "moderadamente activo": ["3-4 veces", "moderado", "gym 3", "3 veces"],
        "muy activo": ["5-6 veces", "gym 4", "gym 5", "muy activo", "bastante activo", "4 veces", "5 veces"],
        "extremadamente activo": ["todos los días", "atleta", "competencia", "diario"],
    }
    for act, keywords in actividades.items():
        if any(kw in texto.lower() for kw in keywords):
            datos["actividad"] = act
            break

    # Distrito NO se extrae aquí — se maneja por separado con _detectar_distrito()
    # para evitar que menciones casuales de distritos interfieran con el perfil.

    return datos


async def _calcular_y_guardar_tdee(chat_id: int, profile: dict) -> int:
    """Calcula el TDEE usando Mifflin-St Jeor y guarda en perfil."""
    nombre = profile.get("name", "usuario")
    sexo = profile.get("sexo", "masculino")
    edad = profile.get("age", "30")
    peso = profile.get("weight_kg", "70")
    altura = profile.get("height_cm", "170")
    actividad = profile.get("actividad", "sedentario")
    objetivo = profile.get("objetivo", "mantenimiento")

    prompt = (
        f"Calcula la meta calórica diaria para esta persona "
        f"usando Mifflin-St Jeor. Sé muy preciso.\n\n"
        f"DATOS:\n"
        f"- Sexo: {sexo}\n"
        f"- Edad: {edad} años\n"
        f"- Peso: {peso} kg\n"
        f"- Altura: {altura} cm\n"
        f"- Actividad: {actividad}\n"
        f"- Objetivo: {objetivo}\n\n"
        f"FÓRMULAS:\n"
        f"Hombre: TMB = 10×peso + 6.25×altura - 5×edad + 5\n"
        f"Mujer:  TMB = 10×peso + 6.25×altura - 5×edad - 161\n\n"
        f"FACTORES DE ACTIVIDAD:\n"
        f"- Sedentario: × 1.2\n"
        f"- Ligeramente activo (1-2x/sem): × 1.375\n"
        f"- Moderadamente activo (3-4x/sem): × 1.55\n"
        f"- Muy activo (5-6x/sem): × 1.725\n"
        f"- Atleta (2x/día): × 1.9\n\n"
        f"AJUSTE POR OBJETIVO:\n"
        f"- Perder peso lento (0.5kg/sem): TDEE - 500 kcal\n"
        f"- Perder peso (1kg/sem): TDEE - 750 kcal\n"
        f"- Mantenimiento: TDEE sin cambio\n"
        f"- Ganar músculo: TDEE + 300 kcal\n"
        f"- Ganar peso: TDEE + 500 kcal\n\n"
        f"LÍMITES DE SEGURIDAD:\n"
        f"- Mínimo hombre: 1,500 kcal/día\n"
        f"- Mínimo mujer: 1,200 kcal/día\n"
        f"- Máximo déficit: -1,000 kcal del TDEE\n\n"
        f"Responde SOLO con el número entero de kcal/día. Sin texto adicional."
    )
    try:
        tdee_str = _call_with_fallback(prompt)
        tdee = int(''.join(filter(str.isdigit, tdee_str)))

        # Límites de seguridad en Python también
        sexo_lower = sexo.lower()
        minimo = 1500 if "mascul" in sexo_lower or "hombre" in sexo_lower or sexo_lower == "no especificado" else 1200
        tdee = max(tdee, minimo)
        tdee = min(tdee, 4000)

        update_profile(chat_id, "tdee", str(tdee))
        logger.info("TDEE calculado para %s: %d kcal", nombre, tdee)
        return tdee
    except Exception as e:
        logger.error("Error calculando TDEE: %s", e)
        # Fallback manual con Mifflin-St Jeor
        try:
            p = float(peso)
            h = float(altura)
            a = float(edad)
            if "mascul" in sexo.lower() or "hombre" in sexo.lower():
                tmb = 10*p + 6.25*h - 5*a + 5
            else:
                tmb = 10*p + 6.25*h - 5*a - 161

            factor_map = {
                "sedentario": 1.2,
                "ligeramente activo": 1.375,
                "moderadamente activo": 1.55,
                "muy activo": 1.725,
                "extremadamente activo": 1.9,
            }
            factor = factor_map.get(actividad.lower(), 1.2)
            tdee_base = tmb * factor

            if "perder" in objetivo.lower():
                tdee_final = tdee_base - 750
            elif "ganar músculo" in objetivo.lower():
                tdee_final = tdee_base + 300
            elif "ganar peso" in objetivo.lower():
                tdee_final = tdee_base + 500
            else:
                tdee_final = tdee_base

            minimo = 1500 if "mascul" in sexo.lower() or "hombre" in sexo.lower() or sexo.lower() == "no especificado" else 1200
            tdee_final = max(tdee_final, minimo)
            tdee_final = min(int(tdee_final), 4000)

            update_profile(chat_id, "tdee", str(tdee_final))
            return tdee_final
        except Exception:
            return 1800


# ── Comandos ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    first_name = update.effective_user.first_name or "amigo"
    logger.info("cmd_start de chat_id: %s (%s)", chat_id, first_name)

    try:
        es_nuevo = register_user(chat_id, name=first_name)

        if es_nuevo:
            await update.message.reply_text(
                f"¡Hola {first_name}! Soy {BOT_NAME}, tu asistente nutricional 🥗\n\n"
                f"Para crear tu plan personalizado necesito conocerte.\n"
                f"Dime en un solo mensaje:\n\n"
                f"• ¿Cuántos años tienes?\n"
                f"• ¿Cuánto pesas? (kg)\n"
                f"• ¿Cuánto mides? (m o cm)\n"
                f"• ¿Cuál es tu nivel de actividad?\n"
                f"  (sedentario / ligero / moderado / muy activo / atleta)\n"
                f"• ¿Cuál es tu objetivo?\n"
                f"  (perder peso / ganar músculo / mejorar energía / mantenimiento)\n\n"
                f"Ejemplo: '28 años, 75kg, 1.78m, gym 4 veces, ganar músculo'"
            )
        else:
            profile = get_profile(chat_id)
            nombre = profile.get("name", first_name)

            # Verificar si le faltan datos
            faltan = []
            if not profile.get("age") or profile.get("age") == "0":
                faltan.append("edad")
            if not profile.get("weight_kg") or profile.get("weight_kg") == "0":
                faltan.append("peso")
            if not profile.get("height_cm") or profile.get("height_cm") == "0":
                faltan.append("altura")

            if faltan:
                await update.message.reply_text(
                    f"¡Hola de nuevo {nombre}! 😊\n\n"
                    f"Me falta completar tu perfil.\n"
                    f"¿Me dices tu {', '.join(faltan)}?\n"
                    f"Ejemplo: '28 años, 75kg, 1.78m'"
                )
            else:
                tdee = profile.get("tdee", "0")
                if tdee and tdee != "0":
                    await update.message.reply_text(
                        f"¡Hola de nuevo {nombre}! Tu meta es {tdee} kcal/día. ¿En qué te ayudo hoy? 😊"
                    )
                else:
                    await update.message.reply_text(
                        f"¡Hola de nuevo {nombre}! ¿En qué te ayudo hoy? 😊"
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
    chat_id = update.effective_chat.id
    logger.info("cmd_perfil de chat_id: %s", chat_id)

    try:
        profile = get_profile(chat_id)
        today_meals = get_today_meals(chat_id)

        if not profile:
            await update.message.reply_text(
                "¡Hola! Todavía no tengo tu perfil guardado.\n\n"
                "Usa /start para registrarte primero."
            )
            return

        field_labels = {
            "name": "Nombre",
            "sexo": "Sexo",
            "weight_kg": "Peso (kg)",
            "height_cm": "Altura (cm)",
            "age": "Edad",
            "actividad": "Actividad",
            "objetivo": "Objetivo",
            "tdee": "Meta calórica (kcal/día)",
            "symptoms": "Síntomas",
        }
        lines = []
        for k, v in profile.items():
            if v and v not in ("0", "[]"):
                label = field_labels.get(k, k)
                lines.append(f"  {label}: {v}")

        nombre = profile.get("name", "Usuario")
        text = f"Perfil de {nombre}:\n\n" + "\n".join(lines)

        if today_meals:
            meals_str = "\n".join(
                f"  - {m['meal_type']}: {m['description']}" for m in today_meals
            )
            total = get_today_total_kcal(chat_id)
            text += f"\n\nComidas de hoy:\n{meals_str}\n  Total: {total} kcal"
        else:
            text += "\n\nHoy no has registrado comidas aún."

        await update.message.reply_text(text)
    except Exception as e:
        logger.error("Error en cmd_perfil: %s", e, exc_info=True)
        await update.message.reply_text(f"Error al cargar perfil: {type(e).__name__}: {e}")


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    logger.info("cmd_help de chat_id: %s", update.effective_chat.id)
    await update.message.reply_text(
        "Esto puedo hacer por ti:\n\n"
        "Escríbeme cualquier duda de nutrición\n"
        "Mándame foto de tu refri -> te sugiero recetas\n"
        "Cuéntame qué comiste -> lo registro\n\n"
        "/perfil — Ver tu perfil\n"
        "/estilo — Cambiar cómo te hablo\n"
        "/recordatorios — Ver/cambiar horarios\n"
        "/objetivos — Ver tus objetivos\n"
        "/delivery — Buscar restaurantes con delivery\n"
        "/start — Registrarte / Bienvenida"
    )


async def cmd_recordatorios(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Muestra y permite configurar horarios de recordatorios."""
    chat_id = update.effective_chat.id
    logger.info("cmd_recordatorios de chat_id: %s", chat_id)
    reminders = get_user_reminders(chat_id)
    estado = "▶️ Activos" if reminders.get("active", True) else "⏸️ Pausados"

    await update.message.reply_text(
        f"⏰ Tus recordatorios ({estado}):\n\n"
        f"🌅 Desayuno: {reminders['breakfast']}\n"
        f"🥗 Almuerzo: {reminders['lunch']}\n"
        f"🍎 Snack: {reminders['snack']}\n"
        f"🌙 Cena: {reminders['dinner']}\n"
        f"📋 Check-in: {reminders['checkin']}\n\n"
        f"Para cambiar un horario escribe:\n"
        f"'cambiar desayuno a las 8:00'\n"
        f"'cambiar cena a las 21:00'\n\n"
        f"'pausar recordatorios' / 'activar recordatorios'"
    )


async def cmd_objetivos(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Muestra los objetivos del usuario."""
    chat_id = update.effective_chat.id
    logger.info("cmd_objetivos de chat_id: %s", chat_id)
    goals = get_goals(chat_id)
    profile = get_profile(chat_id)
    nombre = profile.get("name", "Usuario")

    if not goals:
        await update.message.reply_text(
            f"{nombre}, aún no tienes objetivos registrados.\n"
            f"Cuéntame qué quieres lograr y lo anotamos 💪"
        )
        return

    lines = [f"🎯 Objetivos de {nombre}:\n"]
    for i, g in enumerate(goals, 1):
        kcal = f" ({g['target_kcal']} kcal/día)" if g.get("target_kcal") else ""
        icon = "✅" if g["status"] == "completado" else "🔄"
        lines.append(f"{icon} {i}. {g['goal']}{kcal}")
        lines.append(f"   Registrado: {g['created_at'][:10]}")

    await update.message.reply_text("\n".join(lines))


async def cmd_estilo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Muestra y permite configurar el estilo de conversación."""
    chat_id = update.effective_chat.id
    logger.info("cmd_estilo de chat_id: %s", chat_id)
    settings = get_user_settings(chat_id)

    await update.message.reply_text(
        f"⚙️ Tu estilo actual:\n"
        f"• Estilo: {settings['conv_style']}\n"
        f"• Longitud: {settings['response_length']}\n"
        f"• Emojis: {settings['emoji_level']}\n\n"
        f"Para cambiar escribe:\n"
        f"'estilo directo' — respuestas de 1-2 líneas\n"
        f"'estilo balanceado' — corto con contexto\n"
        f"'estilo detallado' — explicaciones completas\n"
        f"'estilo coach' — motivacional y energético\n"
        f"'estilo científico' — técnico con datos\n\n"
        f"'sin emojis' / 'pocos emojis' / 'muchos emojis'"
    )


# ── Patrones de detección ────────────────────────────────────────────────────

STYLE_CHANGE_PATTERN = re.compile(
    r'(?:cambiar?\s+)?estilo\s+(directo|balanceado|detallado|coach|cient[íi]fico|cientifico)',
    re.IGNORECASE,
)

_STYLE_LENGTH_MAP = {
    "directo": "muy corto", "balanceado": "corto",
    "detallado": "largo", "coach": "corto", "cientifico": "largo",
}

STYLE_OPTIONS = {
    "1": {"conv_style": "directo", "response_length": "muy corto"},
    "2": {"conv_style": "balanceado", "response_length": "corto"},
    "3": {"conv_style": "detallado", "response_length": "largo"},
    "4": {"conv_style": "coach", "response_length": "corto"},
    "5": {"conv_style": "cientifico", "response_length": "largo"},
}


def _detectar_eleccion_estilo(texto: str) -> dict | None:
    """Detecta si el usuario está eligiendo un estilo (1-5 o palabra clave)."""
    t = texto.strip().lower().rstrip(".")
    if t in STYLE_OPTIONS:
        return STYLE_OPTIONS[t]
    keywords = {
        "directo": STYLE_OPTIONS["1"],
        "corto": STYLE_OPTIONS["2"],
        "balanceado": STYLE_OPTIONS["2"],
        "detallado": STYLE_OPTIONS["3"],
        "coach": STYLE_OPTIONS["4"],
        "motivacional": STYLE_OPTIONS["4"],
        "cientifico": STYLE_OPTIONS["5"],
        "científico": STYLE_OPTIONS["5"],
        "tecnico": STYLE_OPTIONS["5"],
        "técnico": STYLE_OPTIONS["5"],
    }
    if t in keywords:
        return keywords[t]
    return None


REMINDER_CHANGE_PATTERN = re.compile(
    r'cambiar?\s+(desayuno|almuerzo|snack|cena|check.?in)\s+a\s+las?\s+(\d{1,2}:\d{2})',
    re.IGNORECASE,
)

SLOT_NAMES = {
    "desayuno": "breakfast", "almuerzo": "lunch",
    "snack": "snack", "cena": "dinner",
    "checkin": "checkin", "check-in": "checkin",
    "check in": "checkin",
}


# ── Mensajes de texto ────────────────────────────────────────────────────────

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    logger.info("handle_text de chat_id: %s", chat_id)

    try:
        user_text = update.message.text.strip()
        logger.info("Usuario %s dice: %s", chat_id, user_text[:80])

        # Auto-registro si es usuario nuevo
        first_name = update.effective_user.first_name or "usuario"
        es_nuevo = register_user(chat_id, name=first_name)
        if es_nuevo:
            await update.message.reply_text(
                f"¡Hola {update.effective_user.first_name}! 👋 Soy *Nutribot*.\n\n"
                f"Esto es lo que puedo hacer por ti:\n\n"
                f"🍽️ Calcular tus calorías y macros diarios\n"
                f"📸 Analizar fotos de tu refri o tus platos\n"
                f"🔍 Buscar restaurantes de delivery cerca tuyo\n"
                f"⏰ Recordarte comer a tus horas\n"
                f"📊 Llevar tu historial nutricional\n"
                f"🧮 Calcular el índice glucémico de lo que comes\n"
                f"💬 Hablar contigo al estilo que prefieras\n\n"
                f"Para empezar solo dime:\n"
                f"*edad, peso, altura, distrito y objetivo*\n"
                f"Ejemplo: '28 años, 75kg, 1.78m, Miraflores, ganar músculo'",
                parse_mode="Markdown"
            )
            return

        # Si tiene perfil incompleto, intentar extraer datos o pedir
        profile_check = get_profile(chat_id)
        if not profile_check.get("age") or profile_check.get("age") == "0":
            datos = _extraer_perfil(user_text)
            if datos:
                for key, value in datos.items():
                    update_profile(chat_id, key, value)
                profile_actual = get_profile(chat_id)
                tiene_datos = all(
                    profile_actual.get(k, "0") not in ["0", "", None]
                    for k in ["age", "weight_kg", "height_cm"]
                )
                if tiene_datos and profile_actual.get("tdee", "0") == "0":
                    await _calcular_y_guardar_tdee(chat_id, profile_actual)
                    tdee = get_profile(chat_id).get("tdee", "?")
                    nombre = profile_actual.get("name", first_name)
                    await update.message.reply_text(
                        f"¡Perfil creado {nombre}! Tu meta es {tdee} kcal/día.\n"
                        f"Ya puedes preguntarme lo que quieras sobre nutrición 💪"
                    )
                    return
                elif not tiene_datos:
                    faltan = []
                    if not profile_actual.get("age") or profile_actual.get("age") == "0":
                        faltan.append("edad")
                    if not profile_actual.get("weight_kg") or profile_actual.get("weight_kg") == "0":
                        faltan.append("peso")
                    if not profile_actual.get("height_cm") or profile_actual.get("height_cm") == "0":
                        faltan.append("altura")
                    await update.message.reply_text(
                        f"Guardé lo que me diste. Aún me falta: {', '.join(faltan)}.\n"
                        f"Ejemplo: '28 años, 75kg, 1.78m'"
                    )
                    return
            else:
                await update.message.reply_text(
                    f"Antes de continuar necesito conocerte un poco.\n"
                    f"¿Me dices tu edad, peso y altura?\n"
                    f"Ejemplo: '25 años, 70kg, 1.75m'"
                )
                return

        # Detectar cambios de horario de recordatorios
        match_reminder = REMINDER_CHANGE_PATTERN.search(user_text)
        if match_reminder:
            slot_es = match_reminder.group(1).lower()
            new_time = match_reminder.group(2)
            slot_en = SLOT_NAMES.get(slot_es, slot_es)
            reminders = get_user_reminders(chat_id)
            reminders[slot_en] = new_time
            save_user_reminders(chat_id, reminders)
            nombre = get_profile(chat_id).get("name", "")
            await update.message.reply_text(
                f"✅ Listo {nombre}! Tu recordatorio de {slot_es} "
                f"ahora es a las {new_time} 🕐"
            )
            return

        if "pausar recordatorios" in user_text.lower():
            reminders = get_user_reminders(chat_id)
            reminders["active"] = False
            save_user_reminders(chat_id, reminders)
            await update.message.reply_text("⏸️ Recordatorios pausados.")
            return

        if "activar recordatorios" in user_text.lower():
            reminders = get_user_reminders(chat_id)
            reminders["active"] = True
            save_user_reminders(chat_id, reminders)
            await update.message.reply_text("▶️ Recordatorios activados.")
            return

        # Detectar cambio de estilo: "estilo directo", "estilo coach", etc.
        match_style = STYLE_CHANGE_PATTERN.search(user_text)
        if match_style:
            nuevo_estilo = match_style.group(1).lower().replace("í", "i")
            settings = get_user_settings(chat_id)
            settings["conv_style"] = nuevo_estilo
            settings["response_length"] = _STYLE_LENGTH_MAP.get(nuevo_estilo, "corto")
            save_user_settings(chat_id, settings)
            nombre = get_profile(chat_id).get("name", "")
            await update.message.reply_text(
                f"✅ Listo {nombre}! Desde ahora hablo contigo en estilo "
                f"'{nuevo_estilo}'."
            )
            return

        # Detectar cambios de emoji
        lower_text = user_text.lower()
        if "sin emojis" in lower_text or "sin emoji" in lower_text:
            settings = get_user_settings(chat_id)
            settings["emoji_level"] = "ninguno"
            save_user_settings(chat_id, settings)
            await update.message.reply_text("Listo, sin emojis desde ahora.")
            return
        if "pocos emojis" in lower_text or "poco emoji" in lower_text:
            settings = get_user_settings(chat_id)
            settings["emoji_level"] = "poco"
            save_user_settings(chat_id, settings)
            await update.message.reply_text("Listo, pocos emojis desde ahora.")
            return
        if "muchos emojis" in lower_text or "mucho emoji" in lower_text:
            settings = get_user_settings(chat_id)
            settings["emoji_level"] = "mucho"
            save_user_settings(chat_id, settings)
            await update.message.reply_text("Listo, muchos emojis desde ahora! 🎉🥳✨")
            return

        # Detectar elección numérica de estilo (1-5) durante onboarding
        eleccion = _detectar_eleccion_estilo(user_text)
        if eleccion and len(user_text.strip()) <= 15:
            settings = get_user_settings(chat_id)
            settings.update(eleccion)
            save_user_settings(chat_id, settings)
            nombre = get_profile(chat_id).get("name", "")
            await update.message.reply_text(
                f"✅ Perfecto {nombre}! Estilo '{settings['conv_style']}' configurado."
            )
            return

        # Detectar respuesta de distrito pendiente
        profile_pre = get_profile(chat_id)
        esperando = profile_pre.get("esperando_distrito", "")
        if esperando == "delivery":
            # Intentar detectar un distrito en el texto
            distrito_detectado = _detectar_distrito(user_text)
            distrito_nuevo = distrito_detectado or user_text.strip().title()
            update_profile(chat_id, "distrito", distrito_nuevo)
            update_profile(chat_id, "esperando_distrito", "")
            update_profile(chat_id, "buscando_delivery", "")
            await update.message.reply_text(
                f"Perfecto, guardé {distrito_nuevo} como tu zona. "
                f"Buscando delivery ahora..."
            )
            await _handle_delivery_request(update, ctx, chat_id, user_text)
            return

        # Detectar mención de distrito en cualquier mensaje
        distrito_mencionado = _detectar_distrito(user_text)
        buscando_delivery = profile_pre.get("buscando_delivery", "")
        if distrito_mencionado:
            update_profile(chat_id, "distrito", distrito_mencionado)
            logger.info("Distrito actualizado: %s", distrito_mencionado)
            # Si estaba buscando delivery, relanzar búsqueda automáticamente
            if buscando_delivery:
                update_profile(chat_id, "buscando_delivery", "")
                await update.message.reply_text(
                    f"Perfecto, guardé {distrito_mencionado}. "
                    f"Buscando delivery ahora..."
                )
                await _handle_delivery_request(update, ctx, chat_id, user_text)
                return

        # Detectar si pide detalles de un restaurante de búsqueda anterior
        if any(p in user_text.lower() for p in
               ["el 1", "el 2", "el 3", "primero", "segundo", "tercero",
                "más info", "mas info", "detalles", "teléfono", "telefono"]):
            place_ids_str = profile_pre.get("last_restaurant_search", "")
            if place_ids_str:
                try:
                    place_ids = _json.loads(place_ids_str)
                    idx = 0
                    if any(p in user_text.lower() for p in ["2", "segundo"]):
                        idx = 1
                    elif any(p in user_text.lower() for p in ["3", "tercero"]):
                        idx = 2

                    if place_ids and idx < len(place_ids):
                        await update.message.chat.send_action(ChatAction.TYPING)
                        detalles = get_detalles_restaurante(place_ids[idx])
                        if detalles:
                            tel = detalles.get("formatted_phone_number", "no disponible")
                            web = detalles.get("website", "")
                            maps_url = detalles.get("url", "")

                            texto = f"*{detalles.get('name', '')}*\n"
                            texto += f"Tel: {tel}\n"
                            if web:
                                texto += f"Web: {web}\n"
                            if maps_url:
                                texto += f"Maps: {maps_url}\n"

                            await update.message.reply_text(texto, parse_mode="Markdown")
                            return
                except Exception as e:
                    logger.error("Error detalles restaurante: %s", e)

        # Detectar solicitud de delivery
        if es_solicitud_delivery(user_text):
            await _handle_delivery_request(update, ctx, chat_id, user_text)
            return

        await update.message.chat.send_action(ChatAction.TYPING)

        # Detectar comida pendiente (usuario describió qué comió tras "me toca cenar" etc.)
        profile_pre_meal = get_profile(chat_id)
        meal_pending = profile_pre_meal.get("meal_pending", "")
        if meal_pending and not detectar_reporte_comida(user_text):
            resultado_pendiente = analizar_texto(user_text)
            if resultado_pendiente["encontro"]:
                t = resultado_pendiente["totales"]
                log_meal(
                    chat_id, meal_type=meal_pending,
                    description=user_text[:200],
                    kcal=t["kcal"],
                    proteina=t.get("proteina", 0),
                    carbos=t.get("carbos", 0),
                    grasas=t.get("grasas", 0),
                    fibra=t.get("fibra", 0),
                )
                update_profile(chat_id, "meal_pending", "")
                logger.info("Comida pendiente registrada: %s, %d kcal", meal_pending, t["kcal"])

        # Detectar si el mensaje contiene datos de perfil (para actualizaciones)
        perfil_extraido = _extraer_perfil(user_text)
        if perfil_extraido:
            for key, value in perfil_extraido.items():
                update_profile(chat_id, key, value)
            logger.info("Perfil actualizado para %s: %s", chat_id, perfil_extraido)

            # Si tiene datos mínimos, recalcular TDEE
            profile_actual = get_profile(chat_id)
            tiene_datos = all(
                profile_actual.get(k, "0") not in ["0", "", None]
                for k in ["age", "weight_kg", "height_cm"]
            )
            if tiene_datos and profile_actual.get("tdee", "0") == "0":
                await _calcular_y_guardar_tdee(chat_id, profile_actual)

        # Detectar preferencias: "no me gusta X"
        no_gusta = re.search(
            r'no\s+(?:me\s+)?(?:gusta|quiero|como)\s+(?:el\s+|la\s+|los\s+|las\s+)?(\w+)',
            user_text.lower(),
        )
        if no_gusta:
            alimento = no_gusta.group(1)
            no_le_gusta_actual = profile_pre.get("no_le_gusta", "")
            if alimento not in no_le_gusta_actual:
                nuevo = f"{no_le_gusta_actual}, {alimento}".strip(", ")
                update_profile(chat_id, "no_le_gusta", nuevo)
                logger.info("Preferencia guardada: no le gusta %s", alimento)

        save_message(chat_id, "user", user_text)

        # Detectar si reporta comida y registrarla con CaloCalc
        meal_context = ""
        meal_registrada = False
        if detectar_reporte_comida(user_text):
            resultado = analizar_texto(user_text)
            if resultado["encontro"]:
                slot = detectar_slot_comida(user_text)
                totales = resultado["totales"]
                kcal = totales["kcal"]
                log_meal(
                    chat_id, meal_type=slot, description=user_text[:200],
                    kcal=kcal,
                    proteina=totales.get("proteina", 0),
                    carbos=totales.get("carbos", 0),
                    grasas=totales.get("grasas", 0),
                    fibra=totales.get("fibra", 0),
                )
                meal_registrada = True
                total_hoy = get_today_total_kcal(chat_id)
                profile_tdee = get_profile(chat_id).get("tdee", "2400")
                meal_context = formato_para_prompt(user_text, total_hoy - kcal, int(profile_tdee or "2400"))
                logger.info("Comida registrada: %s, ~%d kcal, total hoy: %d", slot, kcal, total_hoy)
            else:
                # No encontró alimentos — guardar pendiente y preguntar
                update_profile(chat_id, "meal_pending", detectar_slot_comida(user_text))
                logger.warning("CaloCalc no encontró alimentos en: %s", user_text[:60])
                internet_result = buscar_en_internet(user_text[:60])
                if internet_result:
                    meal_context = (
                        f"=== ENCONTRADO EN INTERNET ===\n"
                        f"Alimento: {internet_result['nombre']}\n"
                        f"Por 100g: {internet_result['kcal_100g']} kcal | "
                        f"P:{internet_result['proteina']}g C:{internet_result['carbos']}g "
                        f"G:{internet_result['grasas']}g\n"
                        f"Fuente: Open Food Facts\n"
                        f"Pregunta al usuario la cantidad para calcular el total."
                    )
                    logger.info("Alimento encontrado en internet: %s", internet_result['nombre'])
                else:
                    meal_context = (
                        "COMIDA_PENDIENTE: El usuario dijo que comió pero no especificó qué.\n"
                        "INSTRUCCIÓN CRÍTICA: Pregúntale exactamente qué comió "
                        "para poder registrar sus calorías."
                    )
                    logger.info("Comida pendiente, esperando descripción")

        # Actualizar contexto del usuario si tiene más de 7 días
        update_context_if_needed(chat_id)

        # Buscar contexto relevante del usuario
        user_context = query_user_context(chat_id, user_text)

        rag_context = retrieve(user_text)
        logger.info("RAG context: %d chars", len(rag_context))

        # Combinar contexto del usuario + meal + RAG nutricional
        if user_context:
            rag_context = user_context + "\n\n" + rag_context
        if meal_context:
            rag_context = meal_context + "\n\n" + rag_context

        today_meals_text = format_today_for_prompt(chat_id)
        total_hoy = get_today_total_kcal(chat_id)
        profile = get_profile(chat_id)
        settings = get_user_settings(chat_id)
        logger.info("Llamando a chat() — total hoy: %d kcal, estilo: %s...",
                     total_hoy, settings.get("conv_style", "balanceado"))
        response = chat(
            user_message=user_text,
            rag_context=rag_context,
            history=get_recent_messages(chat_id),
            profile=profile,
            settings=settings,
            today_meals=today_meals_text,
            total_hoy=total_hoy,
        )
        logger.info("%s responde: %s", BOT_NAME, response[:80])

        # Si fue reporte de comida pero CaloCalc no lo registró, usar lo que dijo Claude
        if detectar_reporte_comida(user_text) and not meal_registrada:
            kcal_claude = _extraer_kcal_de_respuesta(response)
            if kcal_claude and kcal_claude > 50:
                slot = detectar_slot_comida(user_text)
                log_meal(
                    chat_id, meal_type=slot,
                    description=user_text[:200],
                    kcal=kcal_claude,
                    proteina=0, carbos=0, grasas=0, fibra=0,
                )
                update_profile(chat_id, "meal_pending", "")
                logger.info("Registrado por estimacion LLM: %d kcal", kcal_claude)

        save_message(chat_id, "assistant", response)

        await _send_media(update, ctx, response)

    except Exception as e:
        logger.error("Error COMPLETO en handle_text:", exc_info=True)
        await update.message.reply_text(f"Error: {type(e).__name__}: {e}")


# ── Fotos (refrigerador, platos, etc.) ───────────────────────────────────────

async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    logger.info("handle_photo de chat_id: %s", chat_id)

    try:
        first_name = update.effective_user.first_name or "usuario"
        es_nuevo = register_user(chat_id, name=first_name)
        if es_nuevo:
            await update.message.reply_text(
                f"¡Hola {update.effective_user.first_name}! 👋 Soy *Nutribot*.\n\n"
                f"Esto es lo que puedo hacer por ti:\n\n"
                f"🍽️ Calcular tus calorías y macros diarios\n"
                f"📸 Analizar fotos de tu refri o tus platos\n"
                f"🔍 Buscar restaurantes de delivery cerca tuyo\n"
                f"⏰ Recordarte comer a tus horas\n"
                f"📊 Llevar tu historial nutricional\n"
                f"🧮 Calcular el índice glucémico de lo que comes\n"
                f"💬 Hablar contigo al estilo que prefieras\n\n"
                f"Para empezar solo dime:\n"
                f"*edad, peso, altura, distrito y objetivo*\n"
                f"Ejemplo: '28 años, 75kg, 1.78m, Miraflores, ganar músculo'",
                parse_mode="Markdown"
            )
            return

        # Si perfil incompleto, pedir datos antes de procesar foto
        profile_check = get_profile(chat_id)
        if not profile_check.get("age") or profile_check.get("age") == "0":
            await update.message.reply_text(
                f"Antes de analizar fotos necesito conocerte.\n"
                f"¿Me dices tu edad, peso y altura?\n"
                f"Ejemplo: '25 años, 70kg, 1.75m'"
            )
            return

        caption = update.message.caption or ""
        logger.info("Usuario %s envió foto: %s", chat_id, caption[:50])

        await update.message.chat.send_action(ChatAction.TYPING)

        photo = update.message.photo[-1]
        file = await ctx.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()

        save_message(chat_id, "user", f"[FOTO] {caption}")

        palabras_refri = [
            "refri", "nevera", "refrigerador", "heladera",
            "que hay", "comprar", "despensa",
        ]
        es_refri = any(p in caption.lower() for p in palabras_refri)

        history = get_recent_messages(chat_id)
        ultimo_bot = next(
            (t["content"] for t in reversed(history) if t["role"] == "assistant"), ""
        )
        pidio_foto_alimento = (
            "foto del" in ultimo_bot.lower()
            or "etiqueta" in ultimo_bot.lower()
            or "foto de" in ultimo_bot.lower()
        )

        prompt_parts = []
        profile = get_profile(chat_id)
        if profile:
            info = ", ".join(f"{k}: {v}" for k, v in profile.items() if v and v not in ("0", "[]"))
            prompt_parts.append(f"[PERFIL] {info}")

        if pidio_foto_alimento and not es_refri:
            prompt_parts.append(
                "[TAREA: IDENTIFICAR ALIMENTO EN FOTO]\n"
                "El usuario te mandó una foto de un alimento que no reconociste antes.\n"
                "1. Identifica exactamente qué alimento es\n"
                "2. Si ves etiqueta nutricional, lee las calorías por porción\n"
                "3. Si no hay etiqueta, estima las calorías por 100g\n"
                "4. Pregúntale cuánto comió para calcular el total\n"
                "Formato: 'Lo vi! Es [nombre]. Por cada 100g tiene aprox [X] kcal. "
                "¿Cuánto comiste más o menos?'"
            )
            prompt_parts.append(caption or "El usuario te envió esta foto de un alimento. Identifícalo.")
            logger.info("Modo: foto de alimento individual")
        else:
            rag_context = retrieve(caption or "analisis de refrigerador alimentos disponibles")
            if rag_context:
                prompt_parts.append(f"[GUIA NUTRICIONAL]\n{rag_context}")
            prompt_parts.append(
                caption or "El usuario te envió esta foto. Analízala y dale consejos nutricionales."
            )
            logger.info("Modo: foto de refrigerador/general")

        vision_prompt = "\n\n".join(prompt_parts)

        settings = get_user_settings(chat_id)
        logger.info("Llamando a chat_with_image()...")
        response = chat_with_image(
            prompt=vision_prompt,
            image_bytes=bytes(image_bytes),
            mime_type="image/jpeg",
            profile_dict=profile,
            settings=settings,
        )
        logger.info("%s responde (foto): %s", BOT_NAME, response[:80])

        save_message(chat_id, "assistant", response)

        await _send_media(update, ctx, response)

    except Exception as e:
        logger.error("Error en handle_photo: %s", e, exc_info=True)
        await update.message.reply_text(f"Error procesando foto: {e}")


# ── Delivery / Restaurantes ──────────────────────────────────────────────────

async def _handle_delivery_request(update, context, chat_id, user_text):
    """Busca restaurantes de delivery según macros del usuario."""
    if not GOOGLE_PLACES_API_KEY:
        await update.message.reply_text(
            "La búsqueda de delivery no está configurada aún.\n"
            "Se necesita una API key de Google Places en el .env."
        )
        return

    profile = get_profile(chat_id)
    nombre = profile.get("name", "usuario")
    total_hoy = get_today_total_kcal(chat_id)
    tdee = int(profile.get("tdee", "2000") or "2000")
    kcal_rest = max(tdee - total_hoy, 300)
    distrito = profile.get("distrito", "")

    # Si no tiene distrito guardado, preguntarlo
    if not distrito:
        await update.message.reply_text(
            f"Para buscar delivery cerca tuyo, "
            f"¿en qué distrito de Lima estás? "
            f"(ej: Miraflores, San Isidro, Surco, etc.)"
        )
        update_profile(chat_id, "esperando_distrito", "delivery")
        update_profile(chat_id, "buscando_delivery", "1")
        return

    # Detectar tipo de comida en el mensaje
    comidas = [
        "pollo", "pizza", "sushi", "hamburguesa", "ensalada",
        "peruana", "criolla", "china", "italiana", "mexicana",
        "vegana", "vegetariana", "mariscos", "ceviche", "chifa",
    ]
    tipo_detectado = next(
        (c for c in comidas if c in user_text.lower()), ""
    )

    await update.message.chat.send_action(ChatAction.TYPING)
    await update.message.reply_text(
        f"Buscando restaurantes en {distrito}...\n"
        f"Necesitas ~{kcal_rest} kcal más hoy."
    )

    # Buscar restaurantes
    query = f"{tipo_detectado or 'comida'} {distrito} Lima Peru"
    restaurantes = buscar_por_texto(query, f"{distrito} Lima")

    if not restaurantes:
        await update.message.reply_text(
            f"No encontré resultados en {distrito}. "
            f"¿Quieres que busque en otro distrito?"
        )
        return

    # Seleccionar los mejores según macros
    mejores = seleccionar_mejores_opciones(
        restaurantes, kcal_rest, tipo_detectado
    )

    # Formatear y enviar
    texto = formatear_para_telegram(mejores, kcal_rest, distrito)
    await update.message.reply_text(texto, parse_mode="Markdown")

    # Guardar place_ids para cuando pida detalles
    place_ids = [r.get("place_id") for r in mejores if r.get("place_id")]
    update_profile(chat_id, "last_restaurant_search", _json.dumps(place_ids))


async def handle_location(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Recibe ubicación del usuario y busca restaurantes cercanos."""
    chat_id = update.effective_chat.id
    logger.info("handle_location de chat_id: %s", chat_id)

    try:
        first_name = update.effective_user.first_name or "Usuario"
        register_user(chat_id, name=first_name)

        lat = update.message.location.latitude
        lng = update.message.location.longitude
        logger.info("Ubicación recibida: %s, %s", lat, lng)

        # Guardar ubicación en perfil
        update_profile(chat_id, "lat", str(lat))
        update_profile(chat_id, "lng", str(lng))

        if not GOOGLE_PLACES_API_KEY:
            await update.message.reply_text(
                "Ubicación guardada. La búsqueda de delivery necesita "
                "una API key de Google Places en el .env."
            )
            return

        profile = get_profile(chat_id)
        total_hoy = get_today_total_kcal(chat_id)
        tdee = int(profile.get("tdee", "2000") or "2000")
        kcal_rest = max(tdee - total_hoy, 300)
        objetivo = profile.get("objetivo", "")

        await update.message.reply_text("Ubicación recibida. Buscando restaurantes cerca de ti...")
        await update.message.chat.send_action(ChatAction.TYPING)

        restaurantes = buscar_restaurantes_cercanos(lat=lat, lng=lng)
        texto = formato_restaurantes_telegram(restaurantes, kcal_rest, objetivo)
        await update.message.reply_text(texto, parse_mode="Markdown")

    except Exception as e:
        logger.error("Error en handle_location: %s", e, exc_info=True)
        await update.message.reply_text(f"Error procesando ubicación: {e}")


async def cmd_delivery(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Comando /delivery — busca restaurantes de delivery."""
    chat_id = update.effective_chat.id
    logger.info("cmd_delivery de chat_id: %s", chat_id)
    profile = get_profile(chat_id)
    distrito = profile.get("distrito", "")

    if distrito:
        await update.message.reply_text(
            f"¿Qué tipo de comida quieres pedir?\n\n"
            f"Ejemplos:\n"
            f"'busca pollo cerca'\n"
            f"'delivery de sushi en {distrito}'\n"
            f"'algo saludable para cenar'\n"
            f"'busca restaurante peruano'\n\n"
            f"Tu zona actual: {distrito}\n"
            f"(Escribe 'cambiar zona' para actualizarla)"
        )
    else:
        await update.message.reply_text(
            f"Para buscar delivery, ¿en qué distrito de Lima estás?\n"
            f"(ej: Miraflores, San Isidro, Surco, La Molina, etc.)"
        )
        update_profile(chat_id, "esperando_distrito", "delivery")
        update_profile(chat_id, "buscando_delivery", "1")


# ── Envío de sticker/media ───────────────────────────────────────────────────

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
    """Registra todos los handlers en la aplicación de Telegram."""
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("perfil", cmd_perfil))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("recordatorios", cmd_recordatorios))
    app.add_handler(CommandHandler("objetivos", cmd_objetivos))
    app.add_handler(CommandHandler("estilo", cmd_estilo))
    app.add_handler(CommandHandler("delivery", cmd_delivery))
    register_admin_handlers(app)
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info(
        "%s handlers registrados (multi-usuario): "
        "/start, /perfil, /help, /estilo, /recordatorios, /objetivos, /delivery, texto, foto, ubicación",
        BOT_NAME,
    )
