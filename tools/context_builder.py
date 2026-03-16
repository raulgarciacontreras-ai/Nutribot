"""
tools/context_builder.py
Genera y mantiene contexto enriquecido por usuario.
Se actualiza automáticamente cada semana.
"""
import os
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

CONTEXT_DIR = "./data/context"


def get_context_path(chat_id: int) -> str:
    os.makedirs(CONTEXT_DIR, exist_ok=True)
    return os.path.join(CONTEXT_DIR, f"user_{chat_id}.txt")


def generate_user_context(chat_id: int) -> str:
    """
    Genera un resumen de contexto del usuario basado en:
    - Su perfil
    - Sus patrones de comida de las últimas 2 semanas
    - Sus objetivos
    - Sus preferencias
    """
    from memory.store import (
        get_profile, get_goals, get_user_settings,
        get_weekly_summary,
    )

    profile = get_profile(chat_id)
    goals = get_goals(chat_id)
    settings = get_user_settings(chat_id)
    weekly = get_weekly_summary(chat_id)

    nombre = profile.get("name", "usuario")
    edad = profile.get("age", "?")
    peso = profile.get("weight_kg", "?")
    altura = profile.get("height_cm", "?")
    sexo = profile.get("sexo", "?")
    tdee = profile.get("tdee", "?")
    objetivo = profile.get("objetivo", "?")
    distrito = profile.get("distrito", "?")
    actividad = profile.get("actividad", "?")

    # Parsear síntomas
    try:
        sintomas_raw = json.loads(profile.get("symptoms", "[]"))
    except (json.JSONDecodeError, TypeError):
        sintomas_raw = []

    # Calcular promedio calórico semanal
    kcal_dias = []
    for dia, meals in weekly.items():
        total = sum(m.get("kcal_est", 0) or 0 for m in meals)
        if total > 0:
            kcal_dias.append(total)

    promedio_kcal = round(sum(kcal_dias) / len(kcal_dias)) if kcal_dias else 0
    dias_con_datos = len(kcal_dias)

    # Detectar patrones
    patrones = []
    try:
        tdee_num = int(tdee) if tdee and tdee != "?" else 2000
    except (ValueError, TypeError):
        tdee_num = 2000

    if promedio_kcal > 0 and promedio_kcal < tdee_num * 0.7:
        patrones.append("Tiende a comer menos de su meta calorica")
    if promedio_kcal > 0 and promedio_kcal > tdee_num * 1.2:
        patrones.append("Tiende a exceder su meta calorica")
    if dias_con_datos < 5:
        patrones.append("No registra todas las comidas del dia")

    # Detectar comidas frecuentes
    comidas_freq = {}
    for dia, meals in weekly.items():
        for m in meals:
            desc = m.get("description", "").lower().strip()[:40]
            if desc:
                comidas_freq[desc] = comidas_freq.get(desc, 0) + 1
    top_comidas = sorted(comidas_freq.items(), key=lambda x: -x[1])[:5]

    # Síntomas recientes
    if isinstance(sintomas_raw, list) and sintomas_raw:
        if isinstance(sintomas_raw[0], dict):
            sintomas_recientes = [s.get("symptom", str(s)) for s in sintomas_raw[-5:]]
        else:
            sintomas_recientes = [str(s) for s in sintomas_raw[-5:]]
    else:
        sintomas_recientes = []

    # Objetivos activos
    objetivos_texto = "\n".join(
        f"- {g['goal']}" for g in goals[:3]
    ) if goals else "- Sin objetivos especificos registrados"

    # Comidas frecuentes texto
    if top_comidas:
        comidas_texto = "\n".join(
            f"- {desc} ({count}x)" for desc, count in top_comidas
        )
    else:
        comidas_texto = "- Sin datos suficientes aun"

    contexto = f"""=== CONTEXTO PERMANENTE DE {nombre.upper()} ===
Generado: {datetime.now().strftime('%Y-%m-%d')}

PERFIL BASICO:
- Nombre: {nombre} | Sexo: {sexo} | Edad: {edad} anos
- Peso: {peso}kg | Altura: {altura}cm
- Distrito: {distrito} | Actividad: {actividad}
- Meta calorica: {tdee} kcal/dia
- Objetivo principal: {objetivo}

ESTILO DE CONVERSACION:
- Estilo preferido: {settings.get('conv_style', 'balanceado')}
- Longitud de respuestas: {settings.get('response_length', 'corto')}
- Emojis: {settings.get('emoji_level', 'moderado')}

PATRONES ALIMENTICIOS (ultimas 2 semanas):
- Promedio calorico diario: {promedio_kcal} kcal
- Dias con registro: {dias_con_datos}/14
- Patrones detectados:
{chr(10).join(f'  - {p}' for p in patrones) if patrones else '  - Sin patrones detectados aun'}

COMIDAS FRECUENTES:
{comidas_texto}

SINTOMAS RECIENTES:
{chr(10).join(f'- {s}' for s in sintomas_recientes) if sintomas_recientes else '- Ninguno reportado'}

OBJETIVOS ACTIVOS:
{objetivos_texto}

PREFERENCIAS ALIMENTICIAS:
{profile.get('preferencias', 'No especificadas aun')}

ALIMENTOS QUE NO LE GUSTAN:
{profile.get('no_le_gusta', 'No especificado aun')}

NOTAS CLINICAS:
{profile.get('notas_clinicas', 'Sin notas adicionales')}
"""

    # Guardar en archivo
    path = get_context_path(chat_id)
    with open(path, "w", encoding="utf-8") as f:
        f.write(contexto)

    logger.info("Contexto generado para %s: %d chars", nombre, len(contexto))
    return contexto


def get_user_context(chat_id: int) -> str:
    """
    Lee el contexto guardado del usuario.
    Si no existe, lo genera.
    """
    path = get_context_path(chat_id)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return generate_user_context(chat_id)


def update_context_if_needed(chat_id: int) -> None:
    """
    Actualiza el contexto si tiene más de 7 días.
    """
    path = get_context_path(chat_id)
    if os.path.exists(path):
        mod_time = datetime.fromtimestamp(os.path.getmtime(path))
        if (datetime.now() - mod_time).days < 7:
            return  # No necesita actualización
    generate_user_context(chat_id)
