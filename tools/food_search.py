"""
tools/food_search.py
Busca informacion nutricional de alimentos desconocidos en internet.
Usa Open Food Facts API (gratis, sin API key).
"""
import urllib.request
import urllib.parse
import json
import logging

logger = logging.getLogger(__name__)

OPEN_FOOD_FACTS_URL = "https://world.openfoodfacts.org/cgi/search.pl"


def buscar_en_internet(nombre: str) -> dict | None:
    """
    Busca un alimento en Open Food Facts (gratis, sin API key).
    Retorna dict con info nutricional o None si no encuentra.
    """
    try:
        params = urllib.parse.urlencode({
            "search_terms": nombre,
            "search_simple": 1,
            "action": "process",
            "json": 1,
            "page_size": 3,
            "fields": "product_name,nutriments,serving_size",
        })
        url = f"{OPEN_FOOD_FACTS_URL}?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Nutribot/1.0"})

        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())

        productos = data.get("products", [])
        if not productos:
            return None

        # Tomar el primer resultado con datos nutricionales
        for producto in productos:
            nut = producto.get("nutriments", {})
            kcal = nut.get("energy-kcal_100g") or nut.get("energy_100g", 0)
            if kcal and float(kcal) > 0:
                return {
                    "nombre":    producto.get("product_name", nombre),
                    "kcal_100g": round(float(kcal)),
                    "proteina":  round(float(nut.get("proteins_100g", 0)), 1),
                    "carbos":    round(float(nut.get("carbohydrates_100g", 0)), 1),
                    "grasas":    round(float(nut.get("fat_100g", 0)), 1),
                    "fibra":     round(float(nut.get("fiber_100g", 0)), 1),
                    "fuente":    "Open Food Facts",
                }

        return None
    except Exception as e:
        logger.warning("Error buscando '%s' en internet: %s", nombre, e)
        return None
