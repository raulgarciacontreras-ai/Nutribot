"""
tests/test_nutribot.py
Tests automáticos basados en bugs conocidos.
Se ejecutan al arrancar main.py.
"""
import logging

logger = logging.getLogger(__name__)


def run_all() -> dict:
    resultados = {}
    tests = [
        _test_calocalc_no_duplicados,
        _test_calocalc_alimentos_peruanos,
        _test_detectar_reporte_comida,
        _test_no_registra_sugerencias,
        _test_perfil_extrae_altura,
        _test_gemini_fallback,
    ]
    for test in tests:
        nombre = test.__name__.replace("_test_", "")
        try:
            test()
            resultados[nombre] = "OK"
            logger.info("Test %s: OK", nombre)
        except AssertionError as e:
            resultados[nombre] = f"FAIL: {e}"
            logger.error("Test %s FALLO: %s", nombre, e)
        except Exception as e:
            resultados[nombre] = f"ERROR: {e}"
            logger.error("Test %s ERROR: %s", nombre, e)
    return resultados


def _test_calocalc_no_duplicados():
    """BUG conocido: CaloCalc duplicaba ingredientes en frases compuestas."""
    from tools.calocalc_tool import analizar_texto

    r = analizar_texto("pollo a la brasa con papa")
    items = [i["nombre"] for i in r["items"]]
    assert "pollo" not in items or "pollo a la brasa" not in items, \
        f"Duplicado detectado: {items}"
    assert r["totales"]["kcal"] < 800, \
        f"Calorias sobreestimadas: {r['totales']['kcal']} kcal (esperado <800)"


def _test_calocalc_alimentos_peruanos():
    """Verifica que los alimentos peruanos estan en la DB."""
    from tools.calocalc_tool import analizar_texto

    casos = [
        ("ceviche", 100, 400),
        ("lomo saltado", 300, 800),
        ("pollo a la brasa", 200, 700),
        ("anticucho", 100, 500),
    ]
    for alimento, min_kcal, max_kcal in casos:
        r = analizar_texto(f"comi {alimento}")
        assert r["encontro"], f"{alimento} no encontrado en CaloCalc"
        kcal = r["totales"]["kcal"]
        assert min_kcal <= kcal <= max_kcal, \
            f"{alimento}: {kcal} kcal fuera de rango [{min_kcal}-{max_kcal}]"


def _test_detectar_reporte_comida():
    """Verifica que se detectan correctamente los reportes de comida."""
    from tools.meal_tracker import detectar_reporte_comida

    assert detectar_reporte_comida("cene pollo con arroz"), \
        "No detecto 'cene'"
    assert detectar_reporte_comida("almorce lomo saltado"), \
        "No detecto 'almorce'"
    assert detectar_reporte_comida("me comi un anticucho"), \
        "No detecto 'me comi'"


def _test_no_registra_sugerencias():
    """BUG conocido: Nutribot registraba calorias de sugerencias propias."""
    from tools.meal_tracker import detectar_reporte_comida

    frases_no_reporte = [
        "me toca cenar",
        "hora de almorzar",
        "tengo hambre",
        "que como hoy",
    ]
    for frase in frases_no_reporte:
        assert not detectar_reporte_comida(frase), \
            f"Falso positivo en: '{frase}'"


def _test_perfil_extrae_altura():
    """BUG conocido: La altura no se extraia correctamente."""
    from bot.telegram_handler import _extraer_perfil

    casos = [
        ("tengo 1.65m de altura", "165"),
        ("mido 165cm", "165"),
        ("altura 1.65", "165"),
        ("1,65m", "165"),
    ]
    for texto, esperado in casos:
        r = _extraer_perfil(texto)
        assert r.get("height_cm") == esperado, \
            f"Altura no extraida de '{texto}': got {r.get('height_cm')}"


def _test_gemini_fallback():
    """Verifica que el sistema de fallback LLM esta configurado."""
    from llm.llm_client import _active_llm, TONES

    llm = _active_llm()
    assert llm in ["claude", "gemini", "groq"], \
        f"LLM activo invalido: {llm}"
    assert len(TONES) >= 5, \
        f"TONES incompleto: {TONES}"
