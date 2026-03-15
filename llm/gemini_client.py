"""
Cliente Gemini — texto + visión. Arma el prompt con RAG context, historial y perfil.
"""
import google.generativeai as genai
from PIL import Image
from io import BytesIO

from config import GEMINI_API_KEY, GEMINI_MODEL, BOT_NAME, NATHALIE_NAME

genai.configure(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = f"""Eres {BOT_NAME}, asistente nutricional personal de {NATHALIE_NAME}.
Tu personalidad es cálida, motivadora y cercana — como una amiga que sabe de nutrición.

CONTEXTO IMPORTANTE:
- {NATHALIE_NAME} está comiendo muy poco para su nivel de actividad física y no se siente bien.
- Tu objetivo principal es ayudarla a comer mejor: más cantidad, más variedad, más nutrientes.
- NUNCA le sugieras restricciones, dietas restrictivas o reducir calorías.
- Enfócate en AGREGAR alimentos nutritivos, no en quitar cosas.
- Celebra cada comida que reporte, por pequeña que sea.
- Si ves que no ha comido, pregúntale con cariño, nunca con culpa.

REGLAS:
- Responde SIEMPRE en español casual y cercano.
- Mantén las respuestas cortas y directas (máx 3-4 oraciones).
- Cuando analices una foto de refrigerador, sugiere recetas simples y rápidas con lo que veas.
- Si ella reporta síntomas (mareos, cansancio, etc.), relaciónalo con alimentación insuficiente.
- Usa la guía nutricional proporcionada como base para tus recomendaciones.

CUANDO {NATHALIE_NAME} DIGA QUE NO QUIERE COMER, NO TIENE HAMBRE, O NO SABE QUÉ COMER:
- Nunca la presiones ni la hagas sentir culpable.
- Recuérdale con calma que su cuerpo necesita combustible para funcionar.
- Ofrécele 2-3 opciones MUY simples y rápidas basadas en lo que tiene disponible.
- Si rechaza todas, sugiere algo mínimo (aunque sea un yogur o una banana).
- Usa la información del informe RED-S/LEA para explicar brevemente
  POR QUÉ es importante comer, de forma simple y sin jerga médica.
- Tono: empático, nunca clínico ni alarmista.
"""

_model = genai.GenerativeModel(
    model_name=GEMINI_MODEL,
    system_instruction=SYSTEM_PROMPT,
)


def build_prompt(
    user_message: str,
    rag_context: str = "",
    history: list[dict] = None,
    profile: dict = None,
    today_meals: list[dict] = None,
) -> str:
    """Arma el prompt enriquecido con toda la info disponible."""
    parts = []

    if profile:
        info = ", ".join(f"{k}: {v}" for k, v in profile.items() if v and k != "id")
        parts.append(f"[PERFIL DE {NATHALIE_NAME.upper()}]\n{info}")

    if today_meals:
        meals_str = "\n".join(
            f"- {m['meal_type']}: {m['description']}" for m in today_meals
        )
        parts.append(f"[COMIDAS DE HOY]\n{meals_str}")

    if rag_context:
        parts.append(f"[GUÍA NUTRICIONAL RELEVANTE]\n{rag_context}")

    if history:
        conv = "\n".join(
            f"{NATHALIE_NAME if t['role'] == 'user' else BOT_NAME}: {t['content']}"
            for t in history[-6:]
        )
        parts.append(f"[CONVERSACIÓN RECIENTE]\n{conv}")

    parts.append(f"[MENSAJE ACTUAL DE {NATHALIE_NAME.upper()}]\n{user_message}")

    return "\n\n".join(parts)


def chat(prompt: str) -> str:
    """Genera respuesta de texto."""
    response = _model.generate_content(prompt)
    return response.text


def chat_with_image(image_bytes: bytes, prompt: str) -> str:
    """Genera respuesta analizando una imagen."""
    image = Image.open(BytesIO(image_bytes))
    response = _model.generate_content([prompt, image])
    return response.text


def classify_tone(text: str) -> str:
    """Clasifica el tono para elegir sticker. Usa el modelo flash (rápido y gratis)."""
    classifier = genai.GenerativeModel("gemini-2.0-flash")
    result = classifier.generate_content(
        f"Clasifica el tono de este mensaje en UNA sola palabra "
        f"(motivacional, gracioso, nutricion, felicitacion, empujoncito): "
        f'"{text}"'
    )
    tone = result.text.strip().lower().split()[0] if result.text else "default"
    valid = {"motivacional", "gracioso", "nutricion", "felicitacion", "empujoncito"}
    return tone if tone in valid else "default"
