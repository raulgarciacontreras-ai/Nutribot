"""
Cliente LLM — Claude Haiku (primario) + Gemini (fallback) + Groq (fallback final).
Texto + vision. Arma mensajes con RAG context, historial y perfil.
Integra: hora real (WorldTimeAPI), clima (Open-Meteo), GlucoCalc.
Multi-usuario: system prompt dinámico según perfil de cada usuario.
Fallback automático: Claude → Gemini → Groq.
"""
import base64
import io
import logging
import time

import anthropic as _anthropic
from google import genai
from google.genai import types
from openai import OpenAI

from config import (
    CLAUDE_MODEL, GEMINI_MODEL,
    GROQ_MODEL, GROQ_VISION_MODEL,
    PRIMARY_LLM, FALLBACK_LLM,
    TIMEZONE,
)
from llm.time_client import get_lima_time
from llm.weather_client import get_lima_weather, format_for_prompt as format_weather
from tools.glucocalc_tool import analizar_para_nathalie, FOODS

logger = logging.getLogger(__name__)

# ── Lazy client initialization ───────────────────────────────────────────────

def _get_claude_client():
    from config import ANTHROPIC_API_KEY
    return _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _get_gemini_client():
    from config import GEMINI_API_KEY
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY no configurada")
    return genai.Client(api_key=GEMINI_API_KEY)


def _get_groq_client():
    from config import GROQ_API_KEY, GROQ_BASE_URL
    return OpenAI(api_key=GROQ_API_KEY, base_url=GROQ_BASE_URL)


TONES = {"motivacional", "gracioso", "nutricion", "felicitacion", "empujoncito", "default"}


# ── Embeddings con Gemini ─────────────────────────────────────────────────────

def embed(text: str) -> list[float]:
    """Genera embeddings usando Gemini gemini-embedding-001."""
    client = _get_gemini_client()
    result = client.models.embed_content(
        model="gemini-embedding-001",
        contents=text,
    )
    return result.embeddings[0].values

# ── Estado del fallback ──────────────────────────────────────────────────────

_current_llm = PRIMARY_LLM
_fallback_until = 0


def _should_use_fallback() -> bool:
    return time.time() < _fallback_until


def _activate_fallback(minutes: int = 30):
    global _fallback_until, _current_llm
    _fallback_until = time.time() + (minutes * 60)
    _current_llm = FALLBACK_LLM
    logger.warning(
        "LLM primario no disponible — fallback por %d minutos", minutes,
    )


def _deactivate_fallback():
    global _fallback_until, _current_llm
    _fallback_until = 0
    _current_llm = PRIMARY_LLM


def _active_llm() -> str:
    return FALLBACK_LLM if _should_use_fallback() else PRIMARY_LLM


# ── Claude calls ─────────────────────────────────────────────────────────────

def _claude_chat(full_prompt: str) -> str:
    client = _get_claude_client()
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": full_prompt}],
    )
    return resp.content[0].text.strip()


def _claude_vision(full_prompt: str, image_bytes: bytes,
                   mime_type: str = "image/jpeg") -> str:
    client = _get_claude_client()
    b64 = base64.b64encode(image_bytes).decode()
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": b64,
                    },
                },
                {"type": "text", "text": full_prompt},
            ],
        }],
    )
    return resp.content[0].text.strip()


# ── Gemini calls ─────────────────────────────────────────────────────────────

def _gemini_chat(full_prompt: str) -> str:
    client = _get_gemini_client()
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=full_prompt,
    )
    return response.text.strip()


def _gemini_vision(full_prompt: str, image_bytes: bytes) -> str:
    import PIL.Image
    client = _get_gemini_client()
    image = PIL.Image.open(io.BytesIO(image_bytes))
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[full_prompt, image],
    )
    return response.text.strip()


# ── Groq calls ───────────────────────────────────────────────────────────────

def _groq_chat(full_prompt: str) -> str:
    client = _get_groq_client()
    messages = [{"role": "user", "content": full_prompt}]
    resp = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        max_tokens=512,
        temperature=0.7,
    )
    return resp.choices[0].message.content.strip()


def _groq_vision(full_prompt: str, image_bytes: bytes,
                 mime_type: str = "image/jpeg") -> str:
    client = _get_groq_client()
    b64 = base64.b64encode(image_bytes).decode()
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": full_prompt},
            {"type": "image_url",
             "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
        ],
    }]
    resp = client.chat.completions.create(
        model=GROQ_VISION_MODEL,
        messages=messages,
        max_tokens=512,
        temperature=0.7,
    )
    return resp.choices[0].message.content.strip()


# ── Router con fallback de 3 niveles ─────────────────────────────────────────

def _is_quota_error(e: Exception) -> bool:
    error = str(e).lower()
    return any(k in error for k in ["429", "quota", "rate", "exhausted", "limit", "overloaded"])


def _call_with_fallback(prompt: str, image_bytes: bytes = None,
                        mime_type: str = "image/jpeg") -> str:
    """Intenta Claude → Gemini → Groq en ese orden."""
    providers = [
        ("claude",
         lambda: _claude_vision(prompt, image_bytes, mime_type)
         if image_bytes else _claude_chat(prompt)),
        ("gemini",
         lambda: _gemini_vision(prompt, image_bytes)
         if image_bytes else _gemini_chat(prompt)),
        ("groq",
         lambda: _groq_vision(prompt, image_bytes, mime_type)
         if image_bytes else _groq_chat(prompt)),
    ]

    for nombre, fn in providers:
        try:
            logger.info("Intentando LLM: %s", nombre)
            result = fn()
            if _sanitize_response(result) is not None:
                return result
            logger.warning("%s devolvio respuesta tecnica, siguiente...", nombre)
        except Exception as e:
            if _is_quota_error(e):
                logger.warning("%s cuota agotada, siguiente...", nombre)
                continue
            else:
                logger.error("Error en %s: %s", nombre, e)
                continue

    return "Estoy teniendo problemas tecnicos. Intentas de nuevo en un momento?"


# ── System prompt dinámico ───────────────────────────────────────────────────

_STYLE_INSTRUCTIONS = {
    "directo": (
        "ESTILO: Extremadamente directo. "
        "MAXIMO 2 lineas por respuesta. Sin introduccion. "
        "Sin explicaciones a menos que las pidan. "
        "Responde como un mensaje de WhatsApp."
    ),
    "balanceado": (
        "ESTILO: Respuestas cortas de 2-3 lineas. "
        "Un poco de contexto pero sin extenderte. "
        "Natural y conversacional."
    ),
    "detallado": (
        "ESTILO: Respuestas completas con contexto y razonamiento. "
        "Explica el porque de cada recomendacion. "
        "Puedes usar hasta 4-5 parrafos cuando sea necesario."
    ),
    "coach": (
        "ESTILO: Coach motivacional. Energetico y positivo. "
        "Celebra cada logro. Usa lenguaje de empuje. "
        "Respuestas cortas pero con mucha energia. "
        "Trata al usuario como atleta."
    ),
    "cientifico": (
        "ESTILO: Tecnico y preciso. Cita datos especificos. "
        "Menciona formulas y referencias cuando aplique. "
        "Respuestas estructuradas con datos concretos."
    ),
}

_LENGTH_INSTRUCTIONS = {
    "muy corto": "LONGITUD: Maximo 1-2 lineas. Sin excepcion.",
    "corto": "LONGITUD: Maximo 3-4 lineas.",
    "largo": "LONGITUD: Tan largo como necesites para explicar bien.",
}

_EMOJI_INSTRUCTIONS = {
    "ninguno": "EMOJIS: No uses emojis en ninguna respuesta.",
    "poco": "EMOJIS: Maximo 1 emoji por respuesta.",
    "moderado": "EMOJIS: 2-3 emojis por respuesta maximo.",
    "mucho": "EMOJIS: Usa emojis libremente para hacer las respuestas vivas.",
}


def _build_system_prompt(profile: dict, settings: dict = None) -> str:
    """Construye el system prompt personalizado segun perfil y estilo."""
    settings = settings or {}
    nombre = profile.get("name", "usuario")
    edad = profile.get("age", "?")
    peso = profile.get("weight_kg", "?")
    altura = profile.get("height_cm", "?")
    sexo = profile.get("sexo", "no especificado")
    meta = profile.get("tdee", "0")
    objetivo = profile.get("objetivo", "mejorar alimentacion")
    actividad = profile.get("actividad", "?")
    sintomas = profile.get("symptoms", "[]")
    distrito = profile.get("distrito", "Lima")
    no_le_gusta = profile.get("no_le_gusta", "")
    preferencias = profile.get("preferencias", "")

    style = settings.get("conv_style", "balanceado")
    length = settings.get("response_length", "corto")
    emojis = settings.get("emoji_level", "moderado")
    nickname = settings.get("nickname", "") or nombre

    style_text = _STYLE_INSTRUCTIONS.get(style, _STYLE_INSTRUCTIONS["balanceado"])
    length_text = _LENGTH_INSTRUCTIONS.get(length, _LENGTH_INSTRUCTIONS["corto"])
    emoji_text = _EMOJI_INSTRUCTIONS.get(emojis, _EMOJI_INSTRUCTIONS["moderado"])

    if not meta or meta == "0":
        meta_texto = "desconocida — preguntale su peso, altura, edad y nivel de actividad para calcularla"
    else:
        meta_texto = f"{meta} kcal/dia"

    return f"""Eres Nutribot, asistente nutricional personal de {nickname}.

=== ESTILO DE RESPUESTA ===
{style_text}
{length_text}
{emoji_text}

=== PERFIL DEL USUARIO ===
Nombre: {nickname}
Sexo: {sexo} | Edad: {edad} | Peso: {peso} kg | Altura: {altura} cm
Actividad: {actividad}
Objetivo: {objetivo}
Distrito: {distrito}
Sintomas reportados: {sintomas}
Meta calorica diaria: {meta_texto}
{f"Alimentos que NO le gustan: {no_le_gusta}" if no_le_gusta else ""}
{f"Preferencias alimenticias: {preferencias}" if preferencias else ""}

PERSONALIDAD:
- Calido y cercano, como un amigo que sabe de nutricion
- Nunca sermones ni culpa, siempre empatico
- Celebra cada logro, por pequeno que sea
- Cuando no quiere comer: ofrece opciones simples y explica el porque

REGLAS:
- SIEMPRE llama al usuario por su nombre: {nickname}
- Responde SIEMPRE en espanol
- Termina con UNA recomendacion concreta
- Nunca inventes calorias sin base, si estimas dilo
- Si no conoces el perfil completo, pregunta para completarlo
- NUNCA le sugieras restricciones, dietas restrictivas o reducir calorias
- Enfocate en AGREGAR alimentos nutritivos, no en quitar cosas
- Si reporta sintomas (mareos, cansancio, etc.), relacionalo con alimentacion insuficiente
- REGLA CRITICA: Respeta SIEMPRE el estilo y longitud definidos arriba

HIDRATACION:
- Cuando el clima este por encima de 24C, recuerdale beber agua con cada comida
- Si hace mas de 28C, enfatiza la hidratacion como prioridad

ANALISIS GLUCEMICO (GlucoCalc):
- Cuando {nickname} mencione un alimento especifico, tienes acceso a su
  indice glucemico (IG) y carga glucemica (CG) exactos
- IG bajo (<=55) = ideal | IG medio (56-69) = aceptable | IG alto (>=70) = pico rapido
- IMPORTANTE: si quiere comer algo, CELEBRALO. Cualquier comida es mejor que no comer

REGLA CRITICA DE CALORIAS:
- SOLO registra calorias cuando {nickname} dice explicitamente que YA comio algo
  (pasado: comi, almorce, cene, desayune, me tome, etc.)
- NUNCA registres calorias de sugerencias tuyas o preguntas del usuario
- Cuando {nickname} confirme que comio lo que sugeriste, ENTONCES registra y actualiza el total
- Al dar el total diario, usa SOLO lo efectivamente registrado

REGISTRO DE COMIDAS:
- Cuando {nickname} reporte que comio algo, el sistema lo registra automaticamente
- SIEMPRE celebra que comio
- Menciona brevemente las calorias estimadas y cuantas lleva del total diario

REGLA DE TRACKING:
- Si {nickname} dice que va a cenar/almorzar/desayunar pero NO dice QUE comio,
  preguntale que comio exactamente. Ejemplo: 'me toca cenar' -> 'Que vas a cenar {nickname}?'
- Solo registra cuando confirme que comio exactamente
- Cuando registres una comida, confirma: 'Registre X kcal. Llevas Y kcal de Z kcal hoy.'
- Si dice "ya desayune, almorce y cene" sin decir QUE comio en cada una,
  preguntale UNA comida a la vez. Ejemplo: 'Que desayunaste {nickname}?'
  Cuando responda, registra esa y pregunta la siguiente.

ALIMENTOS DESCONOCIDOS:
- Si ves 'COMIDA_PENDIENTE', preguntale que comio exactamente
- Si ves 'ENCONTRADO EN INTERNET' usa esos datos para responder"""


# ── Deteccion de alimentos (GlucoCalc) ────────────────────────────────────────

_FOOD_TRIGGERS = [
    "me provoca", "quiero comer", "puedo comer", "es bueno",
    "esta bien comer", "que tal", "calorias", "engorda",
    "galleta", "chocolate", "alfajor", "pizza", "hamburguesa",
    "helado", "cereal", "snack", "dulce", "postre", "fruta",
    "arroz", "papa", "pan", "avena", "yogur", "leche",
    "banana", "platano", "manzana", "naranja", "mango",
    "quinoa", "pasta", "lentejas", "garbanzos", "frijoles",
    "camote", "batata", "yuca", "sandia", "pera", "uvas",
]


def _extract_food_context(user_message: str) -> str:
    """Detecta alimentos en el mensaje y consulta GlucoCalc."""
    msg_lower = user_message.lower()
    if not any(t in msg_lower for t in _FOOD_TRIGGERS):
        return ""

    best_match = None
    best_score = 0
    for food in FOODS:
        food_name = food[0].lower()
        variantes = [v.strip() for v in food_name.split("/")]
        for variante in variantes:
            palabras = variante.split()
            matches = sum(1 for p in palabras if len(p) > 3 and p in msg_lower)
            if matches > best_score:
                best_score = matches
                best_match = food[0]

    if best_match and best_score > 0:
        result = analizar_para_nathalie(best_match)
        logger.info("GlucoCalc detectado: %s (score=%d)", best_match, best_score)
        return result

    return ""


# ── Build caloric context ────────────────────────────────────────────────────

def _build_caloric_context(fecha_hora: str, today_meals_text: str,
                           total_hoy: int = 0, tdee: int = 2000) -> str:
    """Construye el bloque de estado calorico dinamico segun hora y consumo."""
    if tdee <= 0:
        tdee = 2000
    restante = tdee - total_hoy
    pct = round((total_hoy / tdee) * 100)

    try:
        hora = int(fecha_hora.split()[2].split(":")[0])
    except (IndexError, ValueError):
        hora = 12

    if hora < 10:
        franja = "manana temprano — tiene todo el dia por delante para comer"
        urgencia = "baja"
    elif hora < 13:
        franja = "media manana — debe almorzar pronto"
        urgencia = "media"
    elif hora < 16:
        franja = "tarde del mediodia — ya deberia haber almorzado"
        urgencia = "media"
    elif hora < 19:
        franja = "tarde — se acerca la cena, snack pre-gym si corresponde"
        urgencia = "media-alta"
    elif hora < 21:
        franja = "noche — hora de cenar, pocas horas para completar calorias"
        urgencia = "alta"
    else:
        franja = "noche tarde — ultima oportunidad de comer algo"
        urgencia = "muy alta"

    if restante <= 0:
        estado = f"Meta alcanzada: {total_hoy} kcal / {tdee} kcal"
    elif urgencia in ("alta", "muy alta") and restante > 800:
        estado = (f"DEFICIT CRITICO: Solo {total_hoy} kcal de {tdee}. "
                  f"Le faltan {restante} kcal y ya es {franja}.")
    elif urgencia == "media-alta" and restante > 500:
        estado = (f"DEFICIT: {total_hoy} kcal de {tdee}. "
                  f"Faltan {restante} kcal. Es {franja}.")
    else:
        estado = (f"Hoy: {total_hoy} kcal / {tdee} kcal ({pct}%). "
                  f"Faltan {restante} kcal. Es {franja}.")

    return (
        f"=== FECHA Y HORA ACTUAL (Lima) ===\n"
        f"{fecha_hora} — {franja}\n\n"
        f"=== ESTADO CALORICO DE HOY ===\n"
        f"{estado}\n"
        f"Comidas registradas hoy:\n"
        f"{today_meals_text}\n\n"
        f"=== INSTRUCCIONES CRITICAS PARA ESTA RESPUESTA ===\n"
        f"- SIEMPRE menciona cuantas calorias lleva hoy y cuanto le falta\n"
        f"- Si es noche (despues de las 7pm) y le faltan mas de 500 kcal:\n"
        f"  URGE que coma algo calorico AHORA antes de dormir\n"
        f"- Si reporta haber comido algo, calcula las calorias con CaloCalc\n"
        f"  y actualiza el total\n"
        f"- Sugiere comidas especificas segun las calorias que le faltan:\n"
        f"  * Mas de 800 kcal: comida completa (proteina + carbo + grasa)\n"
        f"  * 400-800 kcal: comida mediana o 2 snacks\n"
        f"  * Menos de 400 kcal: snack liviano o postre saludable\n"
        f"- NUNCA sugiera 4 kilos de nada — las porciones deben ser realistas"
    )


# ── Build full prompt ────────────────────────────────────────────────────────

def _build_full_prompt(
    user_message: str,
    rag_context: str = "",
    history: list[dict] = None,
    profile_dict: dict = None,
    settings: dict = None,
    today_meals: str = "",
    total_hoy: int = 0,
) -> str:
    """Arma el prompt completo con todo el contexto."""
    profile_dict = profile_dict or {}
    fecha_hora = get_lima_time()
    weather = get_lima_weather()
    weather_block = format_weather(weather) if weather.get("ok") else ""

    tdee = int(profile_dict.get("tdee", "0") or "0")
    system_prompt = _build_system_prompt(profile_dict, settings)
    caloric_block = _build_caloric_context(
        fecha_hora, today_meals or "Ninguna registrada aun.", total_hoy, tdee
    )

    parts = [system_prompt, caloric_block]
    if weather_block:
        parts.append(f"[CLIMA LIMA AHORA]\n{weather_block}")
    if rag_context:
        parts.append(f"[GUIA NUTRICIONAL RELEVANTE]\n{rag_context}")

    if history:
        hist_lines = []
        for turn in history[-20:]:
            role = turn["role"].upper() if turn["role"] in ("user", "assistant") else "USER"
            hist_lines.append(f"{role}: {turn['content']}")
        parts.append("=== CONVERSACION RECIENTE ===\n" + "\n".join(hist_lines))

    parts.append(f"=== MENSAJE ACTUAL DEL USUARIO ===\n{user_message}")

    return "\n\n".join(parts)


# ── Filtro de respuestas tecnicas ────────────────────────────────────────────

_BAD_PHRASES = [
    "ejecuta el codigo", "ejecutar el codigo",
    "run the code", "traceback", "error:",
    "```python", "```", "import ", "def ",
    "podrias ejecutar", "could you run",
]


def _sanitize_response(text: str) -> str | None:
    """Elimina cualquier texto tecnico que no debe ver el usuario."""
    text_lower = text.lower()
    if any(phrase in text_lower for phrase in _BAD_PHRASES):
        logger.warning("Respuesta tecnica detectada, reintentando")
        return None
    return text


# ── Chat (texto) — interfaz publica ──────────────────────────────────────────

def chat(
    user_message: str,
    rag_context: str = "",
    history: list[dict] = None,
    profile: dict = None,
    settings: dict = None,
    today_meals: str = "",
    total_hoy: int = 0,
) -> str:
    """Genera respuesta de texto con fallback Claude -> Gemini -> Groq."""
    food_context = _extract_food_context(user_message)
    if food_context:
        rag_context = food_context + "\n\n" + rag_context

    full_prompt = _build_full_prompt(
        user_message, rag_context, history, profile, settings, today_meals, total_hoy
    )

    return _call_with_fallback(full_prompt)


# ── Chat con imagen (vision) ─────────────────────────────────────────────────

def chat_with_image(
    prompt: str,
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    profile_dict: dict = None,
    settings: dict = None,
) -> str:
    """Genera respuesta analizando una imagen con fallback Claude -> Gemini -> Groq."""
    profile_dict = profile_dict or {}

    fecha_hora = get_lima_time()
    weather = get_lima_weather()
    weather_block = format_weather(weather) if weather.get("ok") else ""

    system_prompt = _build_system_prompt(profile_dict, settings)
    full_prompt = f"{system_prompt}\n\n[FECHA Y HORA ACTUAL ({TIMEZONE})]\n{fecha_hora}"
    if weather_block:
        full_prompt += f"\n\n[CLIMA LIMA AHORA]\n{weather_block}"
    full_prompt += f"\n\n{prompt}"

    return _call_with_fallback(full_prompt, image_bytes, mime_type)


# ── Clasificador de tono (para stickers) ─────────────────────────────────────

def classify_tone(response_text: str) -> str:
    prompt = (
        f"Clasifica en UNA palabra: "
        f"motivacional|gracioso|nutricion|felicitacion|empujoncito|default\n"
        f"Mensaje: {response_text[:300]}\n"
        f"Responde SOLO la palabra:"
    )
    try:
        result = _call_with_fallback(prompt)
        tone = result.strip().lower()
        return tone if tone in TONES else "default"
    except Exception:
        return "default"
