"""Helpers para acceder al profile.json semántico.

`get(profile, "contact.phone.local")` accede anidado.
`flatten(profile)` produce un dict plano para los handlers viejos
(autofill heurístico) que esperan claves al nivel raíz.
"""


def get(profile: dict, path: str, default=None):
    """Acceso anidado con punto: 'contact.phone.local'."""
    if profile is None:
        return default
    parts = path.split(".")
    cur = profile
    for p in parts:
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            return default
        if cur is None:
            return default
    return cur


def flatten(profile: dict) -> dict:
    """Aplana el perfil semántico a claves planas para los handlers que aún
    usan la heurística vieja (autofill.py: match por label string)."""
    out = {}
    p = profile.get("personal", {}) or {}
    c = profile.get("contact", {}) or {}
    pr = profile.get("professional", {}) or {}
    pref = profile.get("preferences", {}) or {}

    out.update({
        "first_name": p.get("first_name", ""),
        "last_name": p.get("last_name", ""),
        "full_name": p.get("full_name", f"{p.get('first_name','')} {p.get('last_name','')}").strip(),
        "birth_date": p.get("birth_date", ""),
        "dni": p.get("document_number", ""),
        "document_number": p.get("document_number", ""),
        "document_type": p.get("document_type", ""),
        "gender": p.get("gender", ""),
        "nationality": p.get("nationality", ""),
        "marital_status": p.get("marital_status", ""),
        "has_children": p.get("has_children", ""),
        "email": c.get("email", ""),
    })

    phone = c.get("phone", {}) or {}
    cc = phone.get("country_code", "")
    local = phone.get("local", "")
    out["phone"] = (cc + local).replace(" ", "") if cc and local else (local or cc)
    out["phone_local"] = local
    out["phone_country_code"] = cc

    addr = c.get("address", {}) or {}
    out.update({
        "address": addr.get("street", ""),
        "address_street": addr.get("street", ""),
        "address_number": str(addr.get("number", "")),
        "address_complement": addr.get("complement", ""),
        "city": addr.get("city", ""),
        "state": addr.get("state", ""),
        "country": addr.get("country", ""),
        "postal_code": addr.get("postal_code", ""),
    })

    out.update({
        "linkedin_url": c.get("linkedin_url", ""),
        "github_url": c.get("github_url", ""),
        "portfolio_url": c.get("portfolio_url", ""),
        "skype": c.get("skype", ""),
    })

    out.update({
        "current_position": pr.get("current_position", ""),
        "current_company": pr.get("current_company", ""),
        "desired_position": pr.get("desired_position", ""),
        "experience_years": str(pr.get("experience_years", "")),
        "education_level": pr.get("education_level", ""),
        "professional_summary": pr.get("summary", ""),
        "summary": pr.get("summary", ""),
    })

    out.update({
        "salary_min": str(pref.get("salary_min", "")),
        "salary_max": str(pref.get("salary_max", "")),
        "salary_expectation": str(pref.get("salary_max", "") or pref.get("salary_min", "")),
        "notice_period": pref.get("notice_period", ""),
        "available_start": pref.get("available_start", ""),
        "needs_sponsorship": "Sí" if pref.get("needs_visa_sponsorship") else "No",
        "work_authorization": "Sí" if pref.get("work_authorization_peru") else "No",
        "willing_to_relocate": "Sí" if pref.get("willing_to_relocate") else "No",
        "remote_preference": "Sí" if pref.get("willing_to_remote") else "No",
    })

    # Idiomas como flat: english_level / spanish_level
    for lang in profile.get("languages", []) or []:
        name = (lang.get("name") or "").lower()
        level = lang.get("level", "")
        if name in ("english", "inglés", "ingles"):
            out["english_level"] = level
        elif name in ("spanish", "español", "espanol"):
            out["spanish_level"] = level

    out["cv_path"] = profile.get("cv_path", "")
    out["cover_letter"] = profile.get("cover_letter", "")
    return out
