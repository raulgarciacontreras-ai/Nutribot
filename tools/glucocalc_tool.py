"""
tools/glucocalc_tool.py
Motor de GlucoCalc extraido de la GUI — sin tkinter ni matplotlib.
Permite a Nutribot consultar IG y CG de alimentos por nombre.
Fuentes: Atkinson et al. 2008, Foster-Powell 2002
"""

# (nombre, categoria, IG, carbos/100g, porcion_default, unidad)
FOODS = [
    ("Arroz blanco cocido",     "Cereales",   73, 28, 150, "g"),
    ("Arroz integral cocido",   "Cereales",   50, 23, 150, "g"),
    ("Pan blanco",              "Cereales",   75, 49,  30, "g"),
    ("Pan integral",            "Cereales",   51, 41,  30, "g"),
    ("Avena cocida",            "Cereales",   55, 12, 240, "g"),
    ("Pasta blanca cocida",     "Cereales",   50, 25, 180, "g"),
    ("Pasta integral cocida",   "Cereales",   37, 22, 180, "g"),
    ("Quinoa cocida",           "Cereales",   53, 21, 180, "g"),
    ("Maiz / choclo",           "Cereales",   52, 18, 150, "g"),
    ("Tortilla de maiz",        "Cereales",   52, 48,  45, "g"),
    ("Papa hervida",            "Tuberculos", 78, 17, 150, "g"),
    ("Papa al horno",           "Tuberculos", 85, 20, 150, "g"),
    ("Papa frita",              "Tuberculos", 63, 33, 100, "g"),
    ("Camote / batata",         "Tuberculos", 44, 17, 150, "g"),
    ("Yuca cocida",             "Tuberculos", 46, 38, 150, "g"),
    ("Platano / banana",        "Frutas",     51, 23, 120, "g"),
    ("Manzana",                 "Frutas",     36, 14, 150, "g"),
    ("Naranja",                 "Frutas",     43, 12, 150, "g"),
    ("Mango",                   "Frutas",     51, 15, 150, "g"),
    ("Uvas",                    "Frutas",     59, 18, 120, "g"),
    ("Sandia",                  "Frutas",     76,  8, 200, "g"),
    ("Fresas / frutillas",      "Frutas",     40,  8, 150, "g"),
    ("Pera",                    "Frutas",     38, 15, 150, "g"),
    ("Pina / anana",            "Frutas",     59, 13, 150, "g"),
    ("Lentejas cocidas",        "Legumbres",  32, 20, 150, "g"),
    ("Garbanzos cocidos",       "Legumbres",  28, 27, 150, "g"),
    ("Frijoles negros",         "Legumbres",  30, 23, 150, "g"),
    ("Arvejas / guisantes",     "Legumbres",  48, 14,  80, "g"),
    ("Leche entera",            "Lacteos",    27,  5, 240, "ml"),
    ("Yogur natural sin azucar","Lacteos",    14,  6, 150, "g"),
    ("Yogur con frutas/azucar", "Lacteos",    33, 19, 150, "g"),
    ("Helado de crema",         "Lacteos",    57, 23, 100, "g"),
    ("Galletas de soda",        "Snacks",     74, 67,  30, "g"),
    ("Chocolate negro 70%+",    "Snacks",     23, 46,  30, "g"),
    ("Chocolate con leche",     "Snacks",     43, 57,  30, "g"),
    ("Galletas de chocolate",   "Snacks",     57, 60,  30, "g"),
    ("Papas fritas de bolsa",   "Snacks",     55, 52,  30, "g"),
    ("Alfajor",                 "Snacks",     65, 62,  40, "g"),
    ("Miel",                    "Snacks",     61, 82,  20, "g"),
    ("Jugo de naranja natural", "Bebidas",    50, 10, 240, "ml"),
    ("Gaseosa / refresco",      "Bebidas",    63, 11, 355, "ml"),
    ("Bebida isotonica",        "Bebidas",    78,  6, 355, "ml"),
    ("Zanahoria cruda",         "Verduras",   16, 10,  80, "g"),
    ("Zanahoria cocida",        "Verduras",   47,  8,  80, "g"),
    ("Betarraga / remolacha",   "Verduras",   64, 10,  80, "g"),
    ("Zapallo / calabaza",      "Verduras",   64,  7, 120, "g"),
]


def calcular_cg(gi: int, carbos_100g: int, porcion_g: int) -> float:
    """Calcula la Carga Glucemica para una porcion dada."""
    carbos = (carbos_100g * porcion_g) / 100
    return round((gi * carbos) / 100, 1)


def clasificar_gi(gi: int) -> str:
    if gi <= 55:
        return "BAJO (absorcion lenta, ideal)"
    elif gi <= 69:
        return "MEDIO (impacto moderado)"
    else:
        return "ALTO (pico de glucosa rapido)"


def clasificar_cg(cg: float) -> str:
    if cg <= 10:
        return "BAJA (excelente)"
    elif cg <= 19:
        return "MEDIA (moderada)"
    else:
        return "ALTA (impacto alto)"


def buscar_alimento(nombre: str) -> dict | None:
    """
    Busca un alimento por nombre (busqueda flexible, ignora mayusculas).
    Retorna dict con toda la info o None si no se encuentra.
    """
    nombre_lower = nombre.lower().strip()

    # Coincidencia exacta primero
    for food in FOODS:
        if nombre_lower == food[0].lower():
            return _build_result(food)

    # Coincidencia parcial
    for food in FOODS:
        if nombre_lower in food[0].lower() or food[0].lower() in nombre_lower:
            return _build_result(food)

    # Busqueda por palabras clave
    palabras = nombre_lower.split()
    for food in FOODS:
        food_lower = food[0].lower()
        if any(p in food_lower for p in palabras if len(p) > 3):
            return _build_result(food)

    return None


def _build_result(food: tuple) -> dict:
    nombre, categoria, gi, carbos, porcion, unidad = food
    cg = calcular_cg(gi, carbos, porcion)
    return {
        "nombre":    nombre,
        "categoria": categoria,
        "gi":        gi,
        "gi_clase":  clasificar_gi(gi),
        "carbos_100g": carbos,
        "porcion_default": porcion,
        "unidad":    unidad,
        "cg_porcion": cg,
        "cg_clase":  clasificar_cg(cg),
    }


def analizar_para_nathalie(nombre: str, porcion_g: int = None) -> str:
    """
    Retorna un analisis listo para insertar en el prompt de Nutribot.
    """
    resultado = buscar_alimento(nombre)

    if not resultado:
        return (
            f"'{nombre}' no esta en la base de datos de GlucoCalc. "
            f"Responde basandote en conocimiento general de nutricion."
        )

    porcion = porcion_g or resultado["porcion_default"]
    cg = calcular_cg(resultado["gi"], resultado["carbos_100g"], porcion)
    cg_clase = clasificar_cg(cg)

    return (
        f"=== ANALISIS GLUCEMICO: {resultado['nombre']} ===\n"
        f"Categoria: {resultado['categoria']}\n"
        f"Indice Glucemico: {resultado['gi']} -> {resultado['gi_clase']}\n"
        f"Porcion analizada: {porcion}{resultado['unidad']}\n"
        f"Carbohidratos en porcion: {round(resultado['carbos_100g'] * porcion / 100, 1)}g\n"
        f"Carga Glucemica: {cg} -> {cg_clase}\n"
        f"Fuente: Atkinson et al. 2008 / Foster-Powell 2002"
    )
