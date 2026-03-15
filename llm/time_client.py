"""
time_client.py — Hora real de Lima via WorldTimeAPI (gratis, sin API key).
Fallback: hora local del sistema con pytz si la API no responde.
"""
import urllib.request
import json
from datetime import datetime


def get_lima_time() -> str:
    """
    Obtiene la hora actual de Lima via WorldTimeAPI.
    Gratis, sin API key, sin limites agresivos.
    Fallback: hora local del sistema si falla.
    """
    try:
        url = "http://worldtimeapi.org/api/timezone/America/Lima"
        with urllib.request.urlopen(url, timeout=3) as r:
            data = json.loads(r.read())

        # datetime string viene como: 2026-03-14T17:45:32.123456-05:00
        dt_str = data["datetime"][:19]
        now = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S")

        dias = ["lunes", "martes", "miercoles", "jueves",
                "viernes", "sabado", "domingo"]
        dia = dias[now.weekday()]
        return now.strftime(f"{dia} %d/%m/%Y %H:%M")

    except Exception:
        # Fallback seguro si WorldTimeAPI no responde
        import pytz
        tz = pytz.timezone("America/Lima")
        now = datetime.now(pytz.utc).astimezone(tz)
        dias = ["lunes", "martes", "miercoles", "jueves",
                "viernes", "sabado", "domingo"]
        dia = dias[now.weekday()]
        return now.strftime(f"{dia} %d/%m/%Y %H:%M")


def test():
    print("Hora Lima:", get_lima_time())


if __name__ == "__main__":
    test()
