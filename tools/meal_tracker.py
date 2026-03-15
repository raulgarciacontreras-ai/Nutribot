"""
tools/meal_tracker.py
Detecta reportes de comida y delega el calculo a calocalc_tool.
"""
from tools.calocalc_tool import analizar_texto, analizar_para_nutribot

EATING_TRIGGERS = [
    "comi", "almorce", "desayune",
    "cene", "tome", "me comi",
    "acabo de comer", "acabo de almorzar", "ya comi", "ya desayune",
    "ya almorce", "ya cene", "me tome", "comimos",
    "estoy comiendo", "estoy almorzando", "estoy cenando",
    "estoy desayunando", "me prepare", "prepare",
    "hoy comi", "hoy desayune", "hoy almorce", "hoy cene",
]

MEAL_SLOTS = {
    "desayuno":     ["desayun", "manana", "breakfast"],
    "media_manana": ["media manana", "snack manana"],
    "almuerzo":     ["almuerz", "lunch", "mediodia"],
    "snack":        ["snack", "merienda", "lonche"],
    "cena":         ["cen", "noche", "dinner"],
}


def detectar_reporte_comida(mensaje: str) -> bool:
    """Retorna True si el mensaje indica que Nathalie comio/esta comiendo."""
    return any(t in mensaje.lower() for t in EATING_TRIGGERS)


def detectar_slot_comida(mensaje: str) -> str:
    """Detecta el tipo de comida (desayuno, almuerzo, cena, snack)."""
    msg = mensaje.lower()
    for slot, kws in MEAL_SLOTS.items():
        if any(kw in msg for kw in kws):
            return slot
    return "comida"


def formato_para_prompt(mensaje: str, total_hoy: int, meta: int = 2400) -> str:
    """Genera contexto calorico para inyectar en el prompt del LLM."""
    if not detectar_reporte_comida(mensaje):
        return ""
    return analizar_para_nutribot(mensaje, total_hoy, meta)
