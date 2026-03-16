"""
tools/calocalc_tool.py
Motor de CaloCalc extraido de calorie_calculator.py — sin colorama ni terminal.
200+ alimentos con calorias y macros por 100g.
Fuentes: INCAP, USDA, CENAN
"""
import re

# Base de datos extraida de calorie_calculator.py
# Formato: "nombre": (calorias, proteinas, carbohidratos, grasas, fibra) por 100g
ALIMENTOS = {
    # Frutas
    "manzana":           (52,  0.3, 14.0,  0.2, 2.4),
    "platano":           (89,  1.1, 23.0,  0.3, 2.6),
    "banana":            (89,  1.1, 23.0,  0.3, 2.6),
    "naranja":           (47,  0.9, 12.0,  0.1, 2.4),
    "mango":             (60,  0.8, 15.0,  0.4, 1.6),
    "papaya":            (43,  0.5, 11.0,  0.3, 1.7),
    "pina":              (50,  0.5, 13.0,  0.1, 1.4),
    "uva":               (69,  0.7, 18.0,  0.2, 0.9),
    "uvas":              (69,  0.7, 18.0,  0.2, 0.9),
    "fresa":             (33,  0.7,  8.0,  0.3, 2.0),
    "fresas":            (33,  0.7,  8.0,  0.3, 2.0),
    "pera":              (57,  0.4, 15.0,  0.1, 3.1),
    "sandia":            (30,  0.6,  8.0,  0.2, 0.4),
    "maracuya":          (97,  2.2, 23.0,  0.7,10.4),
    "arandano":          (57,  0.7, 14.0,  0.3, 2.4),
    "arandanos":         (57,  0.7, 14.0,  0.3, 2.4),
    "kiwi":              (61,  1.1, 15.0,  0.5, 3.0),
    "guayaba":           (68,  2.6, 14.0,  1.0, 5.4),
    "aguaymanto":        (53,  1.9, 11.0,  0.7, 4.9),
    "lucuma":            (99,  1.5, 25.0,  0.5, 1.3),
    # Verduras
    "lechuga":           (15,  1.4,  2.9,  0.2, 1.3),
    "ensalada":          (15,  1.4,  2.9,  0.2, 1.3),
    "tomate":            (18,  0.9,  3.9,  0.2, 1.2),
    "zanahoria":         (41,  0.9, 10.0,  0.2, 2.8),
    "brocoli":           (34,  2.8,  7.0,  0.4, 2.6),
    "espinaca":          (23,  2.9,  3.6,  0.4, 2.2),
    "cebolla":           (40,  1.1,  9.0,  0.1, 1.7),
    "pepino":            (16,  0.7,  3.6,  0.1, 0.5),
    "pimiento":          (31,  1.0,  6.0,  0.3, 2.1),
    "esparrago":         (20,  2.2,  3.9,  0.1, 2.1),
    "coliflor":          (25,  1.9,  5.0,  0.3, 2.0),
    "remolacha":         (43,  1.6, 10.0,  0.2, 2.8),
    "betarraga":         (43,  1.6, 10.0,  0.2, 2.8),
    "choclo":            (86,  3.3, 19.0,  1.4, 2.7),
    "maiz":              (86,  3.3, 19.0,  1.4, 2.7),
    "champinon":         (22,  3.1,  3.3,  0.3, 1.0),
    "champinones":       (22,  3.1,  3.3,  0.3, 1.0),
    "zapallo":           (26,  1.0,  7.0,  0.1, 0.5),
    "zucchini":          (17,  1.2,  3.1,  0.3, 1.0),
    "apio":              (16,  0.7,  3.0,  0.2, 1.6),
    # Legumbres
    "lentejas":          (116, 9.0, 20.0,  0.4, 7.9),
    "garbanzos":         (164, 8.9, 27.0,  2.6, 7.6),
    "frijoles":          (127, 8.7, 23.0,  0.5, 6.4),
    "habas":             (88,  7.6, 18.0,  0.7, 5.4),
    "arvejas":           (81,  5.4, 14.0,  0.4, 5.7),
    "quinua":            (120, 4.4, 21.0,  1.9, 2.8),
    # Carnes
    "pollo":             (165,31.0,  0.0,  3.6, 0.0),
    "pechuga":           (165,31.0,  0.0,  3.6, 0.0),
    "pollo pechuga":     (165,31.0,  0.0,  3.6, 0.0),
    "pollo muslo":       (209,26.0,  0.0, 10.9, 0.0),
    "carne":             (176,20.0,  0.0, 10.0, 0.0),
    "res":               (271,26.1,  0.0, 18.0, 0.0),
    "bistec":            (271,26.1,  0.0, 18.0, 0.0),
    "lomo":              (143,26.0,  0.0,  3.5, 0.0),
    "cerdo":             (143,26.3,  0.0,  3.5, 0.0),
    "pavo":              (135,30.0,  0.0,  0.7, 0.0),
    "higado":            (135,20.4,  3.9,  3.6, 0.0),
    # Pescados
    "atun":              (116,25.5,  0.0,  0.8, 0.0),
    "salmon":            (208,20.4,  0.0, 13.4, 0.0),
    "tilapia":           (96, 20.1,  0.0,  1.7, 0.0),
    "sardinas":          (208,24.6,  0.0, 11.5, 0.0),
    "merluza":           (71, 17.0,  0.0,  0.4, 0.0),
    "trucha":            (148,20.8,  0.0,  6.6, 0.0),
    "camaron":           (99, 24.0,  0.2,  0.3, 0.0),
    "camarones":         (99, 24.0,  0.2,  0.3, 0.0),
    "corvina":           (104,18.0,  0.0,  3.2, 0.0),
    "pejerrey":          (87, 18.5,  0.0,  1.0, 0.0),
    "bonito":            (108,24.0,  0.0,  1.0, 0.0),
    # Lacteos y huevos
    "huevo":             (155, 13.0,  1.1, 11.0, 0.0),
    "huevos":            (155, 13.0,  1.1, 11.0, 0.0),
    "clara":             (52,  11.0,  0.7,  0.2, 0.0),
    "claras":            (52,  11.0,  0.7,  0.2, 0.0),
    "leche":             (61,   3.2,  4.8,  3.3, 0.0),
    "leche entera":      (61,   3.2,  4.8,  3.3, 0.0),
    "yogur":             (59,   3.5,  5.0,  3.3, 0.0),
    "yogur griego":      (97,   9.0,  4.0,  5.0, 0.0),
    "queso fresco":      (98,   8.0,  2.0,  7.0, 0.0),
    "queso":             (200, 12.0,  2.0, 16.0, 0.0),
    # Cereales y carbohidratos
    "arroz":             (130,  2.7, 28.0,  0.3, 0.4),
    "arroz blanco":      (130,  2.7, 28.0,  0.3, 0.4),
    "arroz integral":    (111,  2.6, 23.0,  0.9, 1.8),
    "papa":              (77,   2.0, 17.0,  0.1, 2.2),
    "papa hervida":      (77,   2.0, 17.0,  0.1, 2.2),
    "papa al horno":     (93,   2.5, 21.0,  0.1, 2.3),
    "papa frita":        (312,  3.4, 41.0, 15.0, 3.8),
    "camote":            (86,   1.6, 20.0,  0.1, 3.0),
    "batata":            (86,   1.6, 20.0,  0.1, 3.0),
    "yuca":              (160,  1.4, 38.0,  0.3, 1.8),
    "avena":             (389, 17.0, 66.0,  7.0,10.6),
    "avena cocida":      (68,   2.4, 12.0,  1.4, 1.7),
    "pan":               (265,  9.0, 49.0,  3.2, 2.7),
    "pan blanco":        (265,  9.0, 49.0,  3.2, 2.7),
    "pan integral":      (247, 13.0, 41.0,  4.2, 7.0),
    "pasta":             (131,  5.0, 25.0,  1.1, 1.8),
    "pasta integral":    (124,  5.3, 23.0,  1.4, 3.9),
    "cereales":          (379,  7.0, 84.0,  3.0, 3.0),
    # Grasas saludables
    "aguacate":          (160,  2.0,  9.0, 15.0, 7.0),
    "palta":             (160,  2.0,  9.0, 15.0, 7.0),
    "aceite oliva":      (884,  0.0,  0.0,100.0, 0.0),
    "aceite":            (884,  0.0,  0.0,100.0, 0.0),
    "almendras":         (579, 21.0, 22.0, 50.0,12.5),
    "nueces":            (654, 15.0, 14.0, 65.0, 6.7),
    "mani":              (567, 26.0, 16.0, 49.0, 8.5),
    "mantequilla mani":  (588, 25.0, 20.0, 50.0, 6.0),
    "chia":              (486, 17.0, 42.0, 31.0,34.4),
    "semillas chia":     (486, 17.0, 42.0, 31.0,34.4),
    # Snacks y dulces
    "galleta":           (450,  6.0, 65.0, 19.0, 2.0),
    "galletas":          (450,  6.0, 65.0, 19.0, 2.0),
    "alfajor":           (380,  4.0, 62.0, 13.0, 0.5),
    "chocolate negro":   (598,  8.0, 46.0, 43.0,10.9),
    "chocolate":         (535,  8.0, 57.0, 30.0, 3.4),
    "helado":            (207,  3.5, 24.0, 11.0, 0.7),
    "papas fritas":      (536,  7.0, 53.0, 35.0, 3.8),
    "cereal":            (379,  7.0, 84.0,  3.0, 3.0),
    # Bebidas
    "jugo":              (45,   0.7, 10.0,  0.2, 0.2),
    "gaseosa":           (37,   0.0, 10.0,  0.0, 0.0),
    "cafe con leche":    (40,   1.5,  5.0,  1.5, 0.0),
    "cafe":              (2,    0.3,  0.0,  0.0, 0.0),
    "agua coco":         (19,   0.7,  3.7,  0.2, 1.1),
    # Comidas peruanas completas
    "lomo saltado":      (520, 32.0, 45.0, 18.0, 3.0),
    "aji de gallina":    (480, 28.0, 38.0, 22.0, 2.0),
    "ceviche":           (220, 28.0, 12.0,  6.0, 2.0),
    "arroz con leche":   (280,  6.0, 52.0,  6.0, 0.0),
    "causa":             (380, 12.0, 58.0, 10.0, 3.0),
    "sopa":              (180, 10.0, 22.0,  5.0, 2.0),
    "menu":              (650, 35.0, 75.0, 18.0, 4.0),
    "pollo a la brasa":  (420, 38.0, 15.0, 22.0, 0.0),
    "chifa":             (580, 28.0, 72.0, 18.0, 3.0),
    "tacu tacu":         (480, 18.0, 68.0, 14.0, 8.0),
    "anticucho":         (280, 32.0,  8.0, 12.0, 0.0),
    "anticuchos":        (280, 32.0,  8.0, 12.0, 0.0),
    "chicharron":        (520, 38.0,  8.0, 36.0, 0.0),
    "tallarin":          (480, 18.0, 72.0, 12.0, 4.0),
    "tallarines":        (480, 18.0, 72.0, 12.0, 4.0),
    "arroz chaufa":      (520, 22.0, 68.0, 16.0, 3.0),
    "seco de res":       (480, 35.0, 28.0, 24.0, 4.0),
    "estofado":          (420, 30.0, 32.0, 18.0, 3.0),
    "ensalada rusa":     (280,  6.0, 38.0, 12.0, 3.0),
    "papa rellena":      (380, 18.0, 52.0, 12.0, 3.0),
    "leche asada":       (220,  8.0, 32.0,  8.0, 0.0),
    "mazamorra":         (180,  3.0, 42.0,  2.0, 1.0),
    "picaron":           (320,  5.0, 52.0, 10.0, 2.0),
    "picarones":         (320,  5.0, 52.0, 10.0, 2.0),
    "suspiro":           (380,  6.0, 62.0, 12.0, 0.0),
    "omelette":          (154, 11.0,  1.0, 12.0, 0.0),
    "tortilla":          (154, 11.0,  1.0, 12.0, 0.0),
    # Extras
    "mantequilla":       (717,  0.9,  0.1, 81.0, 0.0),
    "mayonesa":          (680,  1.0,  0.6, 75.0, 0.0),
}

# Porciones tipicas en gramos (para cuando no se especifica cantidad)
PORCIONES = {
    "huevo": 60, "huevos": 120, "clara": 33, "claras": 66,
    "pollo": 150, "pechuga": 150, "carne": 150, "res": 150,
    "atun": 120, "salmon": 150,
    "papa": 150, "camote": 150, "arroz": 150, "quinua": 150,
    "avena": 40, "avena cocida": 240, "pan": 30, "pan integral": 30,
    "pasta": 180, "lentejas": 150, "garbanzos": 150, "frijoles": 150,
    "yogur": 150, "yogur griego": 150, "leche": 240,
    "queso": 30, "queso fresco": 50,
    "aguacate": 60, "palta": 60,
    "almendras": 23, "nueces": 28, "mani": 30,
    "mantequilla mani": 32,
    "galleta": 30, "galletas": 30, "alfajor": 40,
    "chocolate": 30, "helado": 100,
    "aceite": 10, "aceite oliva": 10,
    "ensalada": 100, "brocoli": 100,
    "espinaca": 80, "zanahoria": 80,
    "banana": 120, "platano": 120,
    "manzana": 150, "naranja": 150,
    # Platos completos: valores ya son por porción, usar 100 para factor=1.0
    "lomo saltado": 100, "aji de gallina": 100,
    "ceviche": 100, "pollo a la brasa": 100,
    "chifa": 100, "menu": 100,
    "sopa": 100, "tacu tacu": 100,
    "anticucho": 100, "anticuchos": 100,
    "chicharron": 100, "tallarin": 100, "tallarines": 100,
    "arroz chaufa": 100, "seco de res": 100,
    "estofado": 100, "ensalada rusa": 100,
    "papa rellena": 100, "causa": 100,
    "arroz con leche": 100, "leche asada": 100,
    "mazamorra": 100, "picaron": 100, "picarones": 100,
    "suspiro": 100, "omelette": 100, "tortilla": 100,
}

DEFAULT_PORCION = 100


def _detectar_cantidad(texto: str, pos: int) -> int:
    """Busca un numero en el texto cerca de la posicion dada."""
    ventana = texto[max(0, pos-20):pos+30]
    numeros = re.findall(r'\b(\d+)\s*(?:g|gr|gramos|ml)?\b', ventana)
    if numeros:
        try:
            n = int(numeros[0])
            if 5 <= n <= 1000:
                return n
        except ValueError:
            pass
    # Detectar "2 huevos", "3 claras" etc.
    unidades = re.findall(r'\b([2-9]|1[0-9]?)\s+(?:huevo|clara|galleta|alfajor)', ventana)
    if unidades:
        try:
            return int(unidades[0]) * DEFAULT_PORCION
        except ValueError:
            pass
    return None


def analizar_texto(texto: str) -> dict:
    """
    Analiza texto libre y extrae alimentos con sus calorias y macros.
    Retorna dict con lista de items y totales.
    Usa posiciones del texto para evitar duplicados (ej: "pollo a la brasa" no cuenta "pollo" aparte).
    """
    texto_lower = texto.lower()
    encontrados = []
    posiciones_usadas = set()

    # Ordenar por longitud descendente — frases largas primero
    claves = sorted(ALIMENTOS.keys(), key=len, reverse=True)

    for clave in claves:
        if clave not in texto_lower:
            continue

        pos = texto_lower.find(clave)

        # Verificar si esta posición ya fue usada por una frase más larga
        rango = set(range(pos, pos + len(clave)))
        if rango & posiciones_usadas:
            continue

        # Marcar estas posiciones como usadas
        posiciones_usadas |= rango

        kcal_100, prot_100, carb_100, gras_100, fibr_100 = ALIMENTOS[clave]
        porcion = _detectar_cantidad(texto_lower, pos)
        if porcion is None:
            porcion = PORCIONES.get(clave, DEFAULT_PORCION)

        factor = porcion / 100
        encontrados.append({
            "nombre":   clave,
            "porcion":  porcion,
            "kcal":     round(kcal_100 * factor),
            "proteina": round(prot_100 * factor, 1),
            "carbos":   round(carb_100 * factor, 1),
            "grasas":   round(gras_100 * factor, 1),
            "fibra":    round(fibr_100 * factor, 1),
        })

    totales = {
        "kcal":     sum(i["kcal"]     for i in encontrados),
        "proteina": sum(i["proteina"] for i in encontrados),
        "carbos":   sum(i["carbos"]   for i in encontrados),
        "grasas":   sum(i["grasas"]   for i in encontrados),
        "fibra":    sum(i["fibra"]    for i in encontrados),
    }

    return {"items": encontrados, "totales": totales, "encontro": len(encontrados) > 0}


def analizar_para_nutribot(texto: str, total_hoy: int = 0, meta: int = 2400) -> str:
    """
    Retorna analisis calorico completo listo para insertar en el prompt de Nutribot.
    """
    resultado = analizar_texto(texto)

    if not resultado["encontro"]:
        # Intentar buscar en internet
        from tools.food_search import buscar_en_internet
        busqueda = buscar_en_internet(texto[:50])
        if busqueda:
            return (
                f"=== ANALISIS (Open Food Facts) ===\n"
                f"Alimento: {busqueda['nombre']}\n"
                f"Por 100g: {busqueda['kcal_100g']} kcal | "
                f"P:{busqueda['proteina']}g C:{busqueda['carbos']}g "
                f"G:{busqueda['grasas']}g\n"
                f"Fuente: Open Food Facts\n"
                f"INSTRUCCION: Pregunta a Nathalie cuanto comio "
                f"para calcular las calorias exactas."
            )
        # Si tampoco encuentra en internet
        return "ALIMENTO_NO_ENCONTRADO"

    lineas = ["=== ANALISIS CALORICO (CaloCalc) ==="]
    lineas.append("Alimentos detectados:")

    for item in resultado["items"]:
        lineas.append(
            f"  - {item['nombre']} ({item['porcion']}g) = "
            f"{item['kcal']} kcal | "
            f"P:{item['proteina']}g C:{item['carbos']}g G:{item['grasas']}g"
        )

    t = resultado["totales"]
    lineas.append(f"\nEsta comida: {t['kcal']} kcal")
    lineas.append(f"  Proteina: {round(t['proteina'],1)}g | Carbos: {round(t['carbos'],1)}g | "
                  f"Grasas: {round(t['grasas'],1)}g | Fibra: {round(t['fibra'],1)}g")

    nuevo_total = total_hoy + t["kcal"]
    restante    = meta - nuevo_total
    pct         = round((nuevo_total / meta) * 100)

    lineas.append(f"\nAcumulado hoy: {nuevo_total} kcal / {meta} kcal ({pct}%)")

    if restante > 0:
        lineas.append(f"Faltan: {restante} kcal para la meta")
        if nuevo_total < 800:
            lineas.append("ALERTA: Ingesta muy baja. Urge comer mas.")
        elif nuevo_total < 1500:
            lineas.append("DEFICIT: Va por debajo. Recuerdale la siguiente comida.")
    else:
        lineas.append("Meta calorica alcanzada. Felicitala.")

    lineas.append("Fuente: INCAP / USDA / CENAN")
    return "\n".join(lineas)


if __name__ == "__main__":
    # Test
    casos = [
        "comi pollo con papa al horno y ensalada",
        "desayune 2 huevos con pan integral y aguacate",
        "me comi un alfajor y unas galletas",
        "almorce atun con arroz y brocoli",
    ]
    for caso in casos:
        print(f"\nTexto: '{caso}'")
        print(analizar_para_nutribot(caso, total_hoy=400))
        print("-" * 60)
