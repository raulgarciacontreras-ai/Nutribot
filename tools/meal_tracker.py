"""
tools/meal_tracker.py
Detecta reportes de comida y delega el calculo a calocalc_tool.
"""
from tools.calocalc_tool import analizar_texto, analizar_para_nutribot

EATING_TRIGGERS = [
    "comí", "comi", "almorcé", "almorce",
    "desayuné", "desayune", "cené", "cene",
    "me comí", "me comi", "acabo de comer",
    "acabo de almorzar", "acabo de desayunar",
    "ya comí", "ya comi", "ya almorcé", "ya almorce",
    "ya desayuné", "ya desayune", "ya cené", "ya cene",
    "me tomé", "me tome", "tomé", "tome",
    "comimos", "estoy comiendo", "estoy almorzando",
    "estoy cenando", "estoy desayunando",
    "me preparé", "me prepare", "preparé", "prepare",
    "hoy comí", "hoy comi", "hoy desayuné", "hoy desayune",
    "hoy almorcé", "hoy almorce", "hoy cené", "hoy cene",
]

NOT_EATING = [
    "qué como", "que como", "qué puedo", "que puedo",
    "recomienda", "sugieres", "sugiere", "tengo hambre",
    "hora de cenar", "hora de almorzar", "hora de desayunar",
    "qué me recomiendas", "que me recomiendas",
    "qué debería", "que deberia", "qué cocino", "que cocino",
    "ideas para", "opciones para", "dame opciones",
]

MEAL_SLOTS = {
    "desayuno":     ["desayun", "manana", "breakfast"],
    "media_manana": ["media manana", "snack manana"],
    "almuerzo":     ["almuerz", "lunch", "mediodia"],
    "snack":        ["snack", "merienda", "lonche"],
    "cena":         ["cen", "noche", "dinner"],
}


def detectar_reporte_comida(mensaje: str) -> bool:
    """Retorna True solo si el usuario reporta que YA comió algo (pasado)."""
    msg = mensaje.lower()
    if any(t in msg for t in NOT_EATING):
        return False
    return any(t in msg for t in EATING_TRIGGERS)


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
