"""
Cliente LLM — Groq (API compatible con OpenAI).
Texto + vision. Arma mensajes con RAG context, historial y perfil.
Integra: hora real (WorldTimeAPI), clima (Open-Meteo), GlucoCalc.
"""
import base64
import logging
import time
from openai import OpenAI

from config import (
    GROQ_API_KEY, GROQ_BASE_URL,
    GROQ_MODEL, GROQ_VISION_MODEL,
    BOT_NAME, NATHALIE_NAME, TIMEZONE,
)
from llm.time_client import get_lima_time
from llm.weather_client import get_lima_weather, format_for_prompt as format_weather
from tools.glucocalc_tool import analizar_para_nathalie, FOODS

logger = logging.getLogger(__name__)

_client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url=GROQ_BASE_URL,
)

SYSTEM_PROMPT = f"""Eres {BOT_NAME}, asistente nutricional personal de {NATHALIE_NAME}.
Tu personalidad es calida, motivadora y cercana — como una amiga que sabe de nutricion.

CONTEXTO IMPORTANTE:
- {NATHALIE_NAME} esta comiendo muy poco para su nivel de actividad fisica y no se siente bien.
- Tu objetivo principal es ayudarla a comer mejor: mas cantidad, mas variedad, mas nutrientes.
- NUNCA le sugieras restricciones, dietas restrictivas o reducir calorias.
- Enfocate en AGREGAR alimentos nutritivos, no en quitar cosas.
- Celebra cada comida que reporte, por pequena que sea.
- Si ves que no ha comido, preguntale con carino, nunca con culpa.

REGLAS:
- Responde SIEMPRE en espanol casual y cercano.
- Manten las respuestas cortas y directas (max 3-4 oraciones).
- Cuando analices una foto de refrigerador, sugiere recetas simples y rapidas con lo que veas.
- Si ella reporta sintomas (mareos, cansancio, etc.), relacionalo con alimentacion insuficiente.
- Usa la guia nutricional proporcionada como base para tus recomendaciones.

CUANDO {NATHALIE_NAME} DIGA QUE NO QUIERE COMER, NO TIENE HAMBRE, O NO SABE QUE COMER:
- Nunca la presiones ni la hagas sentir culpable.
- Recuerdale con calma que su cuerpo necesita combustible para funcionar.
- Ofrecele 2-3 opciones MUY simples y rapidas basadas en lo que tiene disponible.
- Si rechaza todas, sugiere algo minimo (aunque sea un yogur o una banana).
- Usa la informacion del informe RED-S/LEA para explicar brevemente
  POR QUE es importante comer, de forma simple y sin jerga medica.
- Tono: empatico, nunca clinico ni alarmista.

HIDRATACION:
- Cuando el clima este por encima de 24C, recuerdale beber agua con cada comida.
- Si hace mas de 28C, enfatiza la hidratacion como prioridad.
- Puedes sugerir aguas saborizadas, infusiones frias, o frutas con alto contenido de agua.
- Si el clima es frio, sugiere infusiones calientes o sopas como forma de hidratarse.

ANALISIS GLUCEMICO (GlucoCalc):
- Cuando {NATHALIE_NAME} mencione un alimento especifico, tienes acceso a su
  indice glucemico (IG) y carga glucemica (CG) exactos.
- IG bajo (<=55) = ideal para ella, absorcion lenta, energia estable.
- IG medio (56-69) = aceptable en combinacion con proteina o grasa.
- IG alto (>=70) = explicale que genera pico de glucosa rapido y caida
  de energia — especialmente problematico con su deficit calorico.
- Siempre contextualiza: no es prohibir, es explicar el efecto en su cuerpo.
- IMPORTANTE: si ella quiere comer algo, CELEBRALO. Cualquier comida es mejor que no comer.

REGISTRO DE COMIDAS:
- Cuando {NATHALIE_NAME} reporte que comio algo, el sistema lo registra automaticamente.
- Veras un bloque [COMIDA REGISTRADA] con la descripcion, calorias estimadas y meta diaria.
- SIEMPRE celebra que comio. Usa frases como "que bien!", "me encanta!", "genial!".
- Menciona brevemente las calorias estimadas y cuantas lleva del total diario.
- Si va muy por debajo de la meta (menos del 50% al final del dia), animala con carino a comer algo mas.
- Si va bien encaminada, felicitala y motivala a seguir asi.
- NUNCA la hagas sentir culpable por comer poco. Siempre con tono positivo y de apoyo.
- Meta diaria aproximada: 2400 kcal (segun su nivel de actividad fisica).

ALIMENTOS DESCONOCIDOS:
- Si ves 'ALIMENTO_DESCONOCIDO' en el contexto, pidele SIEMPRE una foto del alimento o su etiqueta nutricional.
- Cuando {NATHALIE_NAME} mande foto de un alimento (no de la refri), describe lo que ves y analiza sus calorias.
- Para fotos de alimentos individuales usa este formato:
  'Lo vi! Es [nombre]. Por cada 100g tiene aprox [X] kcal. Cuanto comiste mas o menos?'
- Si ves 'ENCONTRADO EN INTERNET' usa esos datos para responder.
"""


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

    # Buscar alimentos conocidos en el mensaje — revisar TODAS las variantes (split por /)
    best_match = None
    best_score = 0
    for food in FOODS:
        food_name = food[0].lower()
        # Extraer todas las variantes: "Platano / banana" -> ["platano", "banana"]
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


# ── Build messages ────────────────────────────────────────────────────────────

def _build_messages(
    user_message: str,
    rag_context: str = "",
    history: list[dict] = None,
    profile: dict = None,
    today_meals: list[dict] = None,
) -> list[dict]:
    """Arma la lista de mensajes OpenAI-format con todo el contexto."""
    fecha_hora = get_lima_time()
    weather = get_lima_weather()
    weather_block = format_weather(weather) if weather.get("ok") else ""

    system_full = f"{SYSTEM_PROMPT}\n\n[FECHA Y HORA ACTUAL ({TIMEZONE})]\n{fecha_hora}"
    if weather_block:
        system_full += f"\n\n[CLIMA LIMA AHORA]\n{weather_block}"
    messages = [{"role": "system", "content": system_full}]

    # Inyectar contexto como mensaje de sistema adicional
    context_parts = []

    if profile:
        info = ", ".join(f"{k}: {v}" for k, v in profile.items() if v and k != "id")
        context_parts.append(f"[PERFIL DE {NATHALIE_NAME.upper()}]\n{info}")

    if today_meals:
        meals_str = "\n".join(
            f"- {m['meal_type']}: {m['description']}" for m in today_meals
        )
        context_parts.append(f"[COMIDAS DE HOY]\n{meals_str}")

    if rag_context:
        context_parts.append(f"[GUIA NUTRICIONAL RELEVANTE]\n{rag_context}")

    if context_parts:
        messages.append({
            "role": "system",
            "content": "\n\n".join(context_parts),
        })

    # Historial de conversacion
    if history:
        for turn in history[-6:]:
            role = "user" if turn["role"] == "user" else "assistant"
            messages.append({"role": role, "content": turn["content"]})

    # Mensaje actual
    messages.append({"role": "user", "content": user_message})

    return messages


# ── Chat (texto) ──────────────────────────────────────────────────────────────

def chat(
    user_message: str,
    rag_context: str = "",
    history: list[dict] = None,
    profile: dict = None,
    today_meals: list[dict] = None,
) -> str:
    """Genera respuesta de texto usando Groq con retry para rate limits."""
    # Enriquecer con GlucoCalc si detecta alimentos
    food_context = _extract_food_context(user_message)
    if food_context:
        rag_context = food_context + "\n\n" + rag_context

    messages = _build_messages(user_message, rag_context, history, profile, today_meals)

    # Retry hasta 3 veces si hay rate limit
    for intento in range(3):
        try:
            response = _client.chat.completions.create(
                model=GROQ_MODEL,
                messages=messages,
                temperature=0.7,
                max_tokens=512,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            error_str = str(e).lower()
            if "429" in error_str or "rate" in error_str:
                if intento < 2:
                    tiempo = (intento + 1) * 3  # 3s, 6s
                    logger.warning(
                        "Rate limit Groq, reintentando en %ds (intento %d/3)...",
                        tiempo, intento + 1,
                    )
                    time.sleep(tiempo)
                else:
                    logger.error("Rate limit agotado despues de 3 intentos")
                    return (
                        "Uy, tuve un pequeno problema tecnico. "
                        "Puedes repetirme eso en un momento?"
                    )
            else:
                logger.error("Error en chat Groq: %s", e, exc_info=True)
                return (
                    "Algo salio mal de mi lado. "
                    "Puedes intentarlo de nuevo?"
                )


# ── Chat con imagen (vision) ─────────────────────────────────────────────────

def chat_with_image(
    prompt: str,
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
) -> str:
    """Genera respuesta analizando una imagen usando Groq Vision."""
    b64_image = base64.b64encode(image_bytes).decode("utf-8")
    fecha_hora = get_lima_time()
    weather = get_lima_weather()
    weather_block = format_weather(weather) if weather.get("ok") else ""

    system_full = f"{SYSTEM_PROMPT}\n\n[FECHA Y HORA ACTUAL ({TIMEZONE})]\n{fecha_hora}"
    if weather_block:
        system_full += f"\n\n[CLIMA LIMA AHORA]\n{weather_block}"
    messages = [
        {"role": "system", "content": system_full},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{b64_image}",
                    },
                },
            ],
        },
    ]
    try:
        logger.info("chat_with_image: modelo=%s, imagen=%d bytes, mime=%s",
                     GROQ_VISION_MODEL, len(image_bytes), mime_type)
        response = _client.chat.completions.create(
            model=GROQ_VISION_MODEL,
            messages=messages,
            temperature=0.7,
            max_tokens=512,
        )
        result = response.choices[0].message.content.strip()
        logger.info("Vision OK: %s", result[:80])
        return result
    except Exception as e:
        logger.error("Error en vision Groq (modelo=%s): %s",
                     GROQ_VISION_MODEL, e, exc_info=True)
        return f"No pude analizar la imagen ({e}). Intenta de nuevo."


# ── Clasificar tono ──────────────────────────────────────────────────────────

def classify_tone(text: str) -> str:
    """Clasifica el tono para elegir sticker. Retry silencioso, nunca muestra error."""
    for intento in range(2):
        try:
            response = _client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Clasifica el tono del mensaje en UNA sola palabra. "
                            "Opciones: motivacional, gracioso, nutricion, felicitacion, empujoncito. "
                            "Responde SOLO con la palabra."
                        ),
                    },
                    {"role": "user", "content": text},
                ],
                temperature=0.0,
                max_tokens=10,
            )
            tone = response.choices[0].message.content.strip().lower().split()[0]
            valid = {"motivacional", "gracioso", "nutricion", "felicitacion", "empujoncito"}
            return tone if tone in valid else "default"
        except Exception as e:
            error_str = str(e).lower()
            if ("429" in error_str or "rate" in error_str) and intento < 1:
                logger.warning("Rate limit en classify_tone, reintentando en 3s...")
                time.sleep(3)
            else:
                logger.warning("classify_tone fallo, usando default: %s", e)
                return "default"
    return "default"
