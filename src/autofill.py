import re

# Heuristic: regex on label/placeholder/name -> profile.json key
RULES = [
    (r"(years?|años?).*(exp|experien)|(exp|experien).*(years?|años?)", "experience_years"),
    (r"salar|sueldo|expected pay|compensation|pretensi[oó]n", "salary_expectation"),
    (r"current.*salar|sueldo actual", "current_salary"),
    (r"phone|tel[eé]fono|celular|m[oó]vil", "phone"),
    (r"country code|c[oó]digo.*pa[ií]s", "phone_country_code"),
    (r"first name|nombres?\b", "first_name"),
    (r"last name|apellidos?\b", "last_name"),
    (r"full name|nombre completo", "full_name"),
    (r"e-?mail|correo", "email"),
    (r"city|ciudad", "city"),
    (r"country|pa[ií]s", "country"),
    (r"address|direcci[oó]n", "address"),
    (r"linkedin", "linkedin_url"),
    (r"portfolio|website|sitio web", "portfolio_url"),
    (r"github", "github_url"),
    (r"authoriz|legally|work permit|permiso de trabajo", "work_authorization"),
    (r"sponsor|visa", "needs_sponsorship"),
    (r"notice period|disponibilidad|aviso", "notice_period"),
    (r"start.*date|fecha.*inicio|incorporaci[oó]n", "available_start"),
    (r"english|ingl[eé]s", "english_level"),
    (r"spanish|espa[nñ]ol", "spanish_level"),
    (r"education|estudios|nivel.*acad", "education_level"),
    (r"relocate|reubicar|mudarse", "willing_to_relocate"),
    (r"remote|remoto|teletrabajo", "remote_preference"),
]


def match_field(label: str, profile: dict):
    if not label:
        return None
    label_l = label.lower().strip()
    for pattern, key in RULES:
        if re.search(pattern, label_l):
            return profile.get(key)
    snake = re.sub(r"\W+", "_", label_l).strip("_")
    if snake in profile:
        return profile[snake]
    return None


def ask_user(label: str):
    """Prompt for unknown field. Returns the user's answer or None to skip."""
    print(f"\n  ⚠ Campo desconocido: '{label}'")
    val = input("  Tu respuesta (o ENTER para saltar): ").strip()
    if val:
        slug = re.sub(r"\W+", "_", label.lower()).strip("_")
        print(f"  → Para guardar permanente, agrega a profile.json: \"{slug}\": \"{val}\"")
    return val or None
