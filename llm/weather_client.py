"""
weather_client.py — Clima actual de Lima via Open-Meteo (gratis, sin API key).
"""
import urllib.request
import json

LIMA_LAT = -12.0464
LIMA_LON = -77.0428


def get_lima_weather() -> dict:
    """
    Obtiene temperatura actual de Lima via Open-Meteo.
    Gratis, sin API key, sin registro.
    """
    try:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={LIMA_LAT}&longitude={LIMA_LON}"
            "&current=temperature_2m,relative_humidity_2m,weathercode"
            "&timezone=America%2FLima"
        )
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read())

        current = data["current"]
        temp = current["temperature_2m"]
        humidity = current["relative_humidity_2m"]
        code = current["weathercode"]

        # Descripcion simple del clima
        if code == 0:
            desc = "despejado"
        elif code in [1, 2, 3]:
            desc = "parcialmente nublado"
        elif code in [45, 48]:
            desc = "neblina"
        elif code in [51, 53, 55, 61, 63, 65]:
            desc = "lloviendo"
        else:
            desc = "nublado"

        # Recomendacion de agua segun temperatura
        if temp >= 28:
            agua = "3.5+ litros — hace mucho calor, hidratacion critica"
        elif temp >= 24:
            agua = "3 litros — temperatura alta, bebe seguido"
        elif temp >= 20:
            agua = "2.5 litros — temperatura normal"
        else:
            agua = "2 litros minimo — aunque no sientas sed"

        return {
            "temp": temp,
            "humidity": humidity,
            "desc": desc,
            "agua": agua,
            "ok": True,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def format_for_prompt(weather: dict) -> str:
    """Formatea el clima para inyectar en el system prompt."""
    if not weather.get("ok"):
        return ""
    return (
        f"Clima actual en Lima: {weather['temp']}C, "
        f"{weather['desc']}, humedad {weather['humidity']}%\n"
        f"Agua recomendada hoy: {weather['agua']}"
    )


def test():
    w = get_lima_weather()
    print(format_for_prompt(w))


if __name__ == "__main__":
    test()
