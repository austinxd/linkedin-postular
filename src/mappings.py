"""Mappings de valores semánticos del profile.json a IDs específicos por plataforma.

Cada plataforma usa IDs propios para selects (género, nacionalidad, tipo de
contrato, etc.). El profile.json mantiene valores semánticos ("male",
"indefinite") y aquí los traducimos.

Para agregar plataforma nueva: agregá un dict con la misma forma que PANDAPE.
"""

PANDAPE = {
    # IDs sacados del HTML real de Pandapé.
    "gender": {
        "male": "1",
        "female": "2",
        "unspecified": "0",
        "other": "3",
    },
    "marital_status": {
        "single": "1",
        "married": "2",
        "separated": "3",
        "divorced": "3",
        "widowed": "4",
    },
    "has_children": {
        "yes": "2",
        "no": "3",
        "unspecified": "1",
    },
    "document_type": {
        "DNI": "1",
        "CE": "2",
        "carnet_extranjeria": "2",
        "RUC": "3",
        "passport": "1",  # fallback
    },
    "working_hour": {
        "full_time": "1",
        "part_time": "2",
        "hourly": "3",
        "internship": "5",
    },
    "contract_type": {
        "emergency": "1",
        "occasional": "2",
        "seasonal": "3",
        "supply": "4",
        "specific_project": "5",
        "intermittent": "6",
        "new_activity": "7",
        "market_needs": "8",
        "business_reconversion": "9",
        "indefinite": "10",
        "internship_contract": "11",
    },
    # IDs Pandapé para país y nacionalidad coinciden en el HTML.
    "country": {
        "Peru": "174",
        "Argentina": "10",
        "Bolivia": "21",
        "Chile": "43",
        "Colombia": "48",
        "Ecuador": "63",
        "Mexico": "139",
        "Spain": "209",
        "USA": "240",
        "Venezuela": "245",
    },
    "nationality": {
        "peruvian": "174",
        "argentine": "10",
        "bolivian": "21",
        "chilean": "43",
        "colombian": "48",
        "ecuadorian": "63",
        "mexican": "139",
        "spanish": "209",
        "american": "240",
        "venezuelan": "245",
    },
    "language_level": {
        # Pandapé usa otros IDs que se descubrirán cuando expandamos la sección
        # "Idiomas". Por ahora placeholder.
        "native": "5",
        "advanced": "4",
        "intermediate": "3",
        "basic": "2",
        "beginner": "1",
    },
    # Category1 IDs para el select "Área" en experience sub-form (Pandapé)
    "experience_area": {
        "administration": "1",
        "logistics": "15",
        "customer_service": "16",
        "call_center": "17",
        "purchases": "18",
        "construction": "19",
        "finance": "6",
        "accounting": "6",
        "management": "5",
        "design": "2",
        "teaching": "7",
        "hospitality": "8",
        "it": "4",
        "engineering": "9",
        "research_quality": "3",
        "legal": "10",
        "maintenance": "20",
        "medical": "12",
        "marketing": "21",
        "other": "14",
        "production": "22",
        "human_resources": "13",
        "general_services": "23",
        "sales": "11",
    },
}


# Heurística para mapear texto en español del profile a un Category1 de Pandapé.
# Orden importa: claves más específicas primero. Devuelve "14" (Otros) si nada matchea.
PANDAPE_AREA_KEYWORDS = [
    ("dirección", "5"),
    ("gerencia general", "5"),
    ("ceo", "5"),
    ("country manager", "5"),
    ("tesorería", "6"),
    ("tesoreria", "6"),
    ("finanzas", "6"),
    ("contabilidad", "6"),
    ("financ", "6"),
    ("planeamiento", "6"),
    ("comercial", "11"),
    ("ventas", "11"),
    ("sales", "11"),
    ("recursos humanos", "13"),
    ("rrhh", "13"),
    ("hr", "13"),
    ("informática", "4"),
    ("informatica", "4"),
    ("ti ", "4"),
    ("it ", "4"),
    ("tecnología", "4"),
    ("software", "4"),
    ("ingenier", "9"),
    ("legal", "10"),
    ("asesoría", "10"),
    ("salud", "12"),
    ("médic", "12"),
    ("medicin", "12"),
    ("marketing", "21"),
    ("publicidad", "21"),
    ("comunicaci", "21"),
    ("logística", "15"),
    ("logistica", "15"),
    ("almacén", "15"),
    ("almacen", "15"),
    ("transport", "15"),
    ("compras", "18"),
    ("comercio exterior", "18"),
    ("construcción", "19"),
    ("construccion", "19"),
    ("obra", "19"),
    ("calidad", "3"),
    ("investigación", "3"),
    ("docencia", "7"),
    ("educación", "7"),
    ("turismo", "8"),
    ("hosteler", "8"),
    ("producción", "22"),
    ("manufactura", "22"),
    ("operario", "22"),
    ("administración", "1"),
    ("administracion", "1"),
    ("oficina", "1"),
    ("atención", "16"),
    ("atencion", "16"),
    ("call center", "17"),
    ("callcenter", "17"),
    ("telemerc", "17"),
    ("seguridad", "23"),
    ("aseo", "23"),
    ("limpieza", "23"),
    ("mantenimiento", "20"),
]


def match_pandape_area(text: str, default: str = "14") -> str:
    """Mapea un texto en español (e.g. 'Dirección / Gerencia General') al
    Category1 ID de Pandapé. Default 14 = 'Otros'."""
    if not text:
        return default
    t = str(text).lower()
    for keyword, area_id in PANDAPE_AREA_KEYWORDS:
        if keyword in t:
            return area_id
    return default


# Pandapé Study1 IDs para nivel educativo (Studies[].IdStudy1)
PANDAPE_EDU_LEVEL_KEYWORDS = [
    ("doctorado", "6"),
    ("doctorate", "6"),
    ("phd", "6"),
    ("ph.d", "6"),
    ("maestría", "5"),
    ("maestria", "5"),
    ("master", "5"),
    ("mba", "5"),
    ("postgrado", "5"),
    ("posgrado", "5"),
    ("magíster", "5"),
    ("magister", "5"),
    ("bachiller", "4"),
    ("universitario", "4"),
    ("universitaria", "4"),
    ("licenciado", "4"),
    ("licenciatura", "4"),
    ("undergraduate", "4"),
    ("pregrado", "4"),
    ("ingeniería", "4"),
    ("ingenieria", "4"),
    ("técnico", "3"),
    ("tecnico", "3"),
    ("technical", "3"),
    ("instituto", "3"),
    ("secundaria", "2"),
    ("secondary", "2"),
    ("high school", "2"),
    ("colegio", "2"),
    ("bachillerato", "2"),
    ("primaria", "1"),
    ("primary", "1"),
    ("primario", "1"),
]


def match_pandape_education_level(text: str, default: str = "") -> str:
    """Mapea un texto al Study1 ID de Pandapé. Default vacío = no setear."""
    if not text:
        return default
    t = str(text).lower()
    for keyword, level_id in PANDAPE_EDU_LEVEL_KEYWORDS:
        if keyword in t:
            return level_id
    return default


def map_value(platform: str, field: str, semantic_value, default: str = "") -> str:
    """Traduce un valor semántico a su ID en la plataforma.

    Si el valor ya parece numérico (ej. "1"), lo devuelve sin tocar para
    permitir que el usuario sobrescriba con IDs crudos.
    """
    if semantic_value is None:
        return default
    val = str(semantic_value).strip()
    if not val:
        return default
    # Si ya es un ID numérico crudo, dejar pasar.
    if val.isdigit():
        return val
    table = {
        "pandape": PANDAPE,
    }.get(platform, {})
    return table.get(field, {}).get(val, default)
