import os, random, logging
from config import MEDIA_PATH
logger = logging.getLogger(__name__)
STICKER_PROBABILITY = 0.4
EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4"}
EMOTION_MAP = {
    "Felicitaciones": [
        "excelente", "perfecto", "muy bien", "lograste", "cumpliste",
        "✅", "🎉", "lo lograste", "meta alcanzada", "bien hecho",
        "increíble", "fantástico", "sigue así", "orgullosa",
    ],
    "Celebracion": [
        "llegaste", "completaste", "alcanzaste", "2400", "🥳", "🎊",
        "superaste", "celebr", "festej", "mejor día", "récord",
    ],
    "Advertencia": [
        "cuidado", "⚠️", "alerta", "riesgo", "urgente", "muy poco",
        "preocupa", "consulta", "médico", "déficit severo",
        "atención", "importante recordar",
    ],
    "Reproche": [
        "no comiste", "saltaste", "olvidaste", "todavía no",
        "sigues sin", "otra vez", "de nuevo", "falta",
        "insuficiente", "muy baja", "necesitas comer",
        "recuerda que debes",
    ],
    "Falta_de_Respeto": [
        "galleta", "alfajor", "helado", "papas fritas", "gaseosa",
        "chatarra", "😂", "😅", "no puede ser", "en serio",
        "nathalie por favor", "otra vez lo mismo",
    ],
    "Nathalie": [
        "buenos días", "buenas noches", "cómo estás",
        "cómo te sientes", "cómo vas", "qué tal tu día",
    ],
}


def ensure_folders() -> None:
    """Crea las carpetas de categorias si no existen."""
    for cat in EMOTION_MAP:
        os.makedirs(os.path.join(MEDIA_PATH, cat), exist_ok=True)


def _get_files(category):
    folder = os.path.join(MEDIA_PATH, category)
    if not os.path.isdir(folder):
        return []
    return [
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if os.path.splitext(f)[1].lower() in EXTENSIONS
    ]


def _get_all_files():
    files = []
    if not os.path.isdir(MEDIA_PATH):
        return files
    for cat in os.listdir(MEDIA_PATH):
        if os.path.isdir(os.path.join(MEDIA_PATH, cat)):
            files.extend(_get_files(cat))
    return files


def detectar_emocion(text):
    texto = text.lower()
    scores = {
        e: sum(1 for kw in kws if kw.lower() in texto)
        for e, kws in EMOTION_MAP.items()
    }
    scores = {e: s for e, s in scores.items() if s > 0}
    return max(scores, key=scores.get) if scores else None


def seleccionar_sticker(response_text):
    if random.random() > STICKER_PROBABILITY:
        return None
    emocion = detectar_emocion(response_text)
    if emocion:
        files = _get_files(emocion)
        if files:
            return random.choice(files)
    all_files = _get_all_files()
    return random.choice(all_files) if all_files else None


def stats():
    return {
        cat: len(_get_files(cat))
        for cat in os.listdir(MEDIA_PATH)
        if os.path.isdir(os.path.join(MEDIA_PATH, cat))
    } if os.path.isdir(MEDIA_PATH) else {}
