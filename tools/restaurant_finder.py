"""
tools/restaurant_finder.py
Busca restaurantes de delivery cercanos con Google Places API.
Filtra opciones según objetivos nutricionales del usuario.
100% lectura — nunca hace pedidos.
"""
import urllib.request
import urllib.parse
import json
import logging

from config import GOOGLE_PLACES_API_KEY

logger = logging.getLogger(__name__)

PLACES_NEARBY_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
PLACES_TEXT_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"


def buscar_restaurantes_cercanos(
    lat: float,
    lng: float,
    radio_metros: int = 2000,
    tipo_comida: str = "",
    keyword: str = "delivery comida",
) -> list[dict]:
    """
    Busca restaurantes con delivery cercanos a las coordenadas dadas.
    Retorna lista de restaurantes ordenados por rating.
    """
    params = {
        "location": f"{lat},{lng}",
        "radius": radio_metros,
        "type": "restaurant",
        "keyword": keyword + (" " + tipo_comida if tipo_comida else ""),
        "key": GOOGLE_PLACES_API_KEY,
        "language": "es",
        "opennow": "true",
    }

    url = f"{PLACES_NEARBY_URL}?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Nutribot/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        results = data.get("results", [])
        restaurantes = []

        for r in results[:10]:
            restaurantes.append({
                "nombre": r.get("name", ""),
                "place_id": r.get("place_id", ""),
                "rating": r.get("rating", 0),
                "total_ratings": r.get("user_ratings_total", 0),
                "direccion": r.get("vicinity", ""),
                "tipos": r.get("types", []),
                "abierto": r.get("opening_hours", {}).get("open_now", True),
                "precio": r.get("price_level", 0),
            })

        restaurantes.sort(key=lambda x: x["rating"], reverse=True)
        logger.info("Encontrados %d restaurantes cerca de (%s, %s)", len(restaurantes), lat, lng)
        return restaurantes

    except Exception as e:
        logger.error("Error buscando restaurantes: %s", e)
        return []


def buscar_por_texto(
    query: str,
    ubicacion: str = "Lima, Peru",
) -> list[dict]:
    """
    Búsqueda por texto cuando no hay coordenadas GPS.
    Ej: "pollerías delivery Miraflores Lima"
    """
    params = {
        "query": f"{query} delivery {ubicacion}",
        "key": GOOGLE_PLACES_API_KEY,
        "language": "es",
        "type": "restaurant",
    }

    url = f"{PLACES_TEXT_URL}?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Nutribot/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        results = data.get("results", [])
        restaurantes = []

        for r in results[:8]:
            restaurantes.append({
                "nombre": r.get("name", ""),
                "place_id": r.get("place_id", ""),
                "rating": r.get("rating", 0),
                "total_ratings": r.get("user_ratings_total", 0),
                "direccion": r.get("formatted_address", ""),
                "tipos": r.get("types", []),
                "precio": r.get("price_level", 0),
            })

        restaurantes.sort(key=lambda x: x["rating"], reverse=True)
        return restaurantes

    except Exception as e:
        logger.error("Error en búsqueda por texto: %s", e)
        return []


def get_detalles_restaurante(place_id: str) -> dict:
    """
    Obtiene detalles completos de un restaurante incluyendo
    teléfono, horarios y URL de Google Maps.
    """
    params = {
        "place_id": place_id,
        "fields": "name,formatted_phone_number,opening_hours,"
                  "website,url,rating,price_level,editorial_summary",
        "key": GOOGLE_PLACES_API_KEY,
        "language": "es",
    }

    url = f"{PLACES_DETAILS_URL}?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Nutribot/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        return data.get("result", {})
    except Exception as e:
        logger.error("Error obteniendo detalles: %s", e)
        return {}


def seleccionar_mejores_opciones(
    restaurantes: list[dict],
    kcal_objetivo: int,
    tipo_comida_preferido: str = "",
) -> list[dict]:
    """
    Filtra y rankea restaurantes según el objetivo nutricional.
    Prioriza opciones saludables según las kcal necesarias.
    """
    if not restaurantes:
        return []

    saludable_keywords = [
        "pollo", "chicken", "grill", "ensalada", "salad",
        "fitness", "healthy", "natural", "veggie", "sushi",
        "pescado", "fish", "peruano", "criolla",
    ]
    no_saludable_keywords = [
        "pizza", "burger", "hamburguesa", "fast food",
        "fried", "frito", "helado", "dulce", "cake",
    ]

    priorizar_saludable = kcal_objetivo < 700

    scored = []
    for r in restaurantes:
        score = r.get("rating", 0) * 10
        nombre_lower = r["nombre"].lower()

        if tipo_comida_preferido and tipo_comida_preferido.lower() in nombre_lower:
            score += 30

        if priorizar_saludable:
            if any(kw in nombre_lower for kw in saludable_keywords):
                score += 20
            if any(kw in nombre_lower for kw in no_saludable_keywords):
                score -= 10

        if r.get("total_ratings", 0) > 100:
            score += 5
        if r.get("total_ratings", 0) > 500:
            score += 5

        scored.append({**r, "score": score})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:3]


def precio_nivel_a_texto(nivel: int) -> str:
    niveles = {
        0: "precio no disponible", 1: "económico S/",
        2: "moderado S/S/", 3: "caro S/S/S/", 4: "muy caro S/S/S/S/",
    }
    return niveles.get(nivel, "")


def formatear_para_telegram(
    restaurantes: list[dict],
    kcal_objetivo: int,
    distrito: str = "",
) -> str:
    """Formatea los resultados para mostrar en Telegram."""
    if not restaurantes:
        return (
            "No encontré restaurantes con delivery abiertos ahora "
            f"en {'tu zona' if not distrito else distrito}. "
            "¿Quieres que busque en un distrito específico?"
        )

    zona = f" en {distrito}" if distrito else ""
    lines = [
        f"Restaurantes con delivery{zona} (~{kcal_objetivo} kcal):\n"
    ]

    for i, r in enumerate(restaurantes, 1):
        precio = precio_nivel_a_texto(r.get("precio", 0))
        ratings = r.get("total_ratings", 0)

        lines.append(f"*{i}. {r['nombre']}*")
        lines.append(f"   {r.get('rating', '?')}/5 ({ratings} reseñas)")
        lines.append(f"   {r.get('direccion', '?')}")
        if precio:
            lines.append(f"   {precio}")
        lines.append("")

    lines.append(
        "Dime cuál te interesa y busco más detalles "
        "(teléfono, horario, link de Maps)."
    )
    return "\n".join(lines)


DELIVERY_TRIGGERS = [
    "busca delivery", "buscar delivery", "quiero delivery",
    "pedir delivery", "delivery cerca", "restaurante cerca",
    "algo para pedir", "busca restaurante", "comida a domicilio",
    "rappi", "pedidos ya", "qué pido", "que pido",
    "busca comida", "encuentra restaurante",
    "pedir comida", "quiero pedir", "ordenar delivery",
    "restaurantes cerca", "delivery",
]


def es_solicitud_delivery(texto: str) -> bool:
    """Detecta si el texto es una solicitud de delivery."""
    return any(t in texto.lower() for t in DELIVERY_TRIGGERS)
