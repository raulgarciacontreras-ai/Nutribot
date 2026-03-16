"""
bot/admin_handler.py
Comandos de superadmin para monitorear Nutribot en tiempo real.
Solo accesible desde el SUPERADMIN_ID del .env.
"""
import sqlite3
import logging
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from config import SUPERADMIN_ID, SQLITE_DB_PATH
from memory.store import (
    get_all_chat_ids, get_profile, get_recent_messages,
    get_today_meals, get_today_total_kcal, get_goals,
)

logger = logging.getLogger(__name__)


def is_admin(update: Update) -> bool:
    return update.effective_chat.id == SUPERADMIN_ID


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("cmd_admin recibido de chat_id: %s", update.effective_chat.id)
    logger.info("SUPERADMIN_ID configurado: %s", SUPERADMIN_ID)
    if not is_admin(update):
        logger.warning("Acceso denegado — no es admin")
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "🔧 *Panel de Admin Nutribot*\n\n"
            "Comandos disponibles:\n"
            "/admin usuarios — lista todos los usuarios\n"
            "/admin live — últimos mensajes en tiempo real\n"
            "/admin user [nombre] — perfil completo de un usuario\n"
            "/admin chat [nombre] — últimos 10 mensajes de un usuario\n"
            "/admin stats — estadísticas generales\n"
            "/admin alertas — usuarios con déficit calórico crítico\n"
            "/admin calorias — resumen calórico de todos hoy\n"
            "/admin llm — estado del LLM (primario/fallback)\n"
            "/admin contexto [nombre] — generar contexto de usuario",
            parse_mode="Markdown"
        )
        return

    subcmd = args[0].lower()

    if subcmd == "usuarios":
        await _cmd_usuarios(update, context)
    elif subcmd == "live":
        await _cmd_live(update, context)
    elif subcmd == "user" and len(args) > 1:
        await _cmd_user(update, context, args[1])
    elif subcmd == "chat" and len(args) > 1:
        await _cmd_chat(update, context, args[1])
    elif subcmd == "stats":
        await _cmd_stats(update, context)
    elif subcmd == "alertas":
        await _cmd_alertas(update, context)
    elif subcmd == "calorias":
        await _cmd_calorias(update, context)
    elif subcmd == "llm":
        await _cmd_llm_status(update, context)
    elif subcmd == "contexto" and len(args) > 1:
        await _cmd_generar_contexto(update, context, args[1])
    else:
        await update.message.reply_text(
            "Comando no reconocido. Usa /admin para ver la lista."
        )


async def _cmd_usuarios(update, context):
    """Lista todos los usuarios registrados."""
    chat_ids = get_all_chat_ids()
    if not chat_ids:
        await update.message.reply_text("No hay usuarios registrados.")
        return

    lines = [f"👥 *Usuarios registrados ({len(chat_ids)}):*\n"]
    for cid in chat_ids:
        p = get_profile(cid)
        nombre = p.get("name", "?")
        edad = p.get("age", "?")
        peso = p.get("weight_kg", "?")
        distrito = p.get("distrito", "?")
        tdee = p.get("tdee", "?")
        total_hoy = get_today_total_kcal(cid)
        lines.append(
            f"• *{nombre}* | {edad}a {peso}kg | "
            f"{distrito} | meta: {tdee} kcal | hoy: {total_hoy} kcal"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def _cmd_live(update, context):
    """Muestra los últimos mensajes de todos los usuarios."""
    try:
        conn = sqlite3.connect(SQLITE_DB_PATH)
        try:
            rows = conn.execute(
                "SELECT chat_id, role, content, ts "
                "FROM messages ORDER BY id DESC LIMIT 20"
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            await update.message.reply_text("No hay mensajes recientes.")
            return

        lines = ["Últimos 20 mensajes (todos los usuarios):\n"]
        for row in reversed(rows):
            cid, role, content, ts = row
            p = get_profile(cid)
            nombre = p.get("name", f"ID:{cid}")
            hora = ts[11:16] if len(ts) > 16 else ts
            icono = "U" if role == "user" else "B"
            texto = content[:60].replace("*", "").replace("_", "") + ("..." if len(content) > 60 else "")
            lines.append(f"[{icono}] {nombre} [{hora}]: {texto}")

        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        logger.error("Error en _cmd_live: %s", e, exc_info=True)
        await update.message.reply_text(f"Error: {e}")


async def _cmd_user(update, context, nombre_buscar: str):
    """Perfil completo de un usuario por nombre."""
    chat_ids = get_all_chat_ids()

    target_cid = None
    for cid in chat_ids:
        p = get_profile(cid)
        if nombre_buscar.lower() in p.get("name", "").lower():
            target_cid = cid
            break

    if not target_cid:
        await update.message.reply_text(
            f"No encontré usuario '{nombre_buscar}'."
        )
        return

    p = get_profile(target_cid)
    total_hoy = get_today_total_kcal(target_cid)
    meals = get_today_meals(target_cid)
    goals = get_goals(target_cid)

    lines = [f"👤 *Perfil: {p.get('name')}*\n"]
    lines.append(f"Chat ID: `{target_cid}`")
    lines.append(
        f"Edad: {p.get('age')} | Peso: {p.get('weight_kg')}kg | "
        f"Altura: {p.get('height_cm')}cm"
    )
    lines.append(
        f"Sexo: {p.get('sexo', '?')} | "
        f"Actividad: {p.get('actividad', '?')}"
    )
    lines.append(f"Distrito: {p.get('distrito', '?')}")
    lines.append(f"Objetivo: {p.get('objetivo', '?')}")
    lines.append(f"TDEE: {p.get('tdee', '?')} kcal/día")
    lines.append(f"\n📊 *Hoy:* {total_hoy} kcal / {p.get('tdee', '?')} kcal")

    if meals:
        lines.append("\n🍽️ *Comidas de hoy:*")
        for m in meals:
            lines.append(
                f"  • {m['meal_type']}: {m['description'][:50]}"
                f" ({m.get('kcal', '?')} kcal)"
            )

    if goals:
        lines.append("\n🎯 *Objetivos:*")
        for g in goals[:3]:
            lines.append(f"  • {g['goal']}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def _cmd_chat(update, context, nombre_buscar: str):
    """Últimos 10 mensajes de un usuario específico."""
    chat_ids = get_all_chat_ids()

    target_cid = None
    for cid in chat_ids:
        p = get_profile(cid)
        if nombre_buscar.lower() in p.get("name", "").lower():
            target_cid = cid
            break

    if not target_cid:
        await update.message.reply_text(
            f"No encontré usuario '{nombre_buscar}'."
        )
        return

    p = get_profile(target_cid)
    nombre = p.get("name", nombre_buscar)
    turns = get_recent_messages(target_cid)

    if not turns:
        await update.message.reply_text(
            f"No hay mensajes de {nombre} todavía."
        )
        return

    lines = [f"💬 *Últimos mensajes de {nombre}:*\n"]
    for t in turns:
        icono = "👤" if t["role"] == "user" else "🤖"
        texto = t["content"][:80] + "..." if len(t["content"]) > 80 else t["content"]
        lines.append(f"{icono} {texto}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def _cmd_stats(update, context):
    """Estadísticas generales de Nutribot."""
    chat_ids = get_all_chat_ids()
    total_users = len(chat_ids)

    conn = sqlite3.connect(SQLITE_DB_PATH)
    try:
        total_msgs = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        total_meals = conn.execute("SELECT COUNT(*) FROM daily_log").fetchone()[0]
        msgs_hoy = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE date(ts)=date('now')"
        ).fetchone()[0]
    finally:
        conn.close()

    lines = [
        "📊 *Estadísticas de Nutribot*\n",
        f"👥 Usuarios registrados: {total_users}",
        f"💬 Mensajes totales: {total_msgs}",
        f"💬 Mensajes hoy: {msgs_hoy}",
        f"🍽️ Comidas registradas: {total_meals}",
    ]

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def _cmd_alertas(update, context):
    """Usuarios con déficit calórico crítico hoy."""
    chat_ids = get_all_chat_ids()
    alertas = []

    for cid in chat_ids:
        p = get_profile(cid)
        tdee = int(p.get("tdee", "0") or "0")
        if not tdee:
            continue
        total_hoy = get_today_total_kcal(cid)
        pct = (total_hoy / tdee * 100) if tdee else 0
        if pct < 50:
            nombre = p.get("name", "?")
            alertas.append(
                f"⚠️ *{nombre}*: {total_hoy}/{tdee} kcal ({pct:.0f}%)"
            )

    if alertas:
        text = "🚨 *Alertas de déficit calórico:*\n\n" + "\n".join(alertas)
    else:
        text = "✅ Ningún usuario con déficit crítico hoy."

    await update.message.reply_text(text, parse_mode="Markdown")


async def _cmd_calorias(update, context):
    """Resumen calórico de todos los usuarios hoy."""
    chat_ids = get_all_chat_ids()
    if not chat_ids:
        await update.message.reply_text("No hay usuarios registrados.")
        return

    lines = ["🔥 *Resumen calórico de hoy:*\n"]
    for cid in chat_ids:
        p = get_profile(cid)
        nombre = p.get("name", "?")
        tdee = int(p.get("tdee", "0") or "0")
        total_hoy = get_today_total_kcal(cid)
        if tdee:
            pct = total_hoy / tdee * 100
            barra = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
            lines.append(
                f"*{nombre}*: {total_hoy}/{tdee} kcal [{barra}] {pct:.0f}%"
            )
        else:
            lines.append(f"*{nombre}*: {total_hoy} kcal (sin meta)")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def _cmd_llm_status(update, context):
    """Estado del LLM: stack de 3 niveles."""
    await update.message.reply_text(
        "Stack de LLMs (en orden de prioridad)\n\n"
        "1. Claude Haiku (Anthropic) — primario\n"
        "2. Gemini 2.0 Flash (Google) — fallback\n"
        "3. Llama 3.3 70B (Groq) — fallback final\n\n"
        "Si uno falla por cuota -> pasa al siguiente automaticamente."
    )


async def _cmd_generar_contexto(update, context, nombre_buscar: str):
    """Genera y muestra el contexto de un usuario."""
    from tools.context_builder import generate_user_context
    from rag.vector_store import index_user_context

    chat_ids = get_all_chat_ids()
    for cid in chat_ids:
        p = get_profile(cid)
        if nombre_buscar.lower() in p.get("name", "").lower():
            ctx = generate_user_context(cid)
            index_user_context(cid, ctx)
            # Truncar para Telegram (límite ~4096 chars)
            display = ctx[:3500] + "..." if len(ctx) > 3500 else ctx
            await update.message.reply_text(
                f"Contexto generado para {p.get('name')}:\n\n{display}"
            )
            return
    await update.message.reply_text(f"Usuario '{nombre_buscar}' no encontrado.")


def register_admin_handlers(app):
    """Registra el handler de admin."""
    app.add_handler(CommandHandler("admin", cmd_admin))
    logger.info("Admin handler registrado (SUPERADMIN_ID=%s)", SUPERADMIN_ID)
