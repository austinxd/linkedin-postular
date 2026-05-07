"""Handler Computrabajo — recibe una pestaña ya abierta en una oferta y la postula."""
import time
import random
from playwright.sync_api import Page, TimeoutError as PWTimeout

from . import autofill
from . import profile_helper as ph


def human_pause(a=1.5, b=3.5):
    time.sleep(random.uniform(a, b))


def apply_on_page(page: Page, profile: dict) -> bool:
    """Postula en una página Computrabajo ya abierta. Devuelve True si se aplicó."""
    profile = ph.flatten(profile) if "personal" in profile else profile
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except PWTimeout:
        pass
    human_pause(1.5, 3)

    # ¿Ya postulado antes?
    already = page.locator(":text('ya te postulaste'), :text('Ya te has postulado')")
    if already.count():
        print("        → Ya postulado anteriormente (Computrabajo)")
        return True

    # Si pide login
    if "login" in page.url.lower() or "ingresar" in page.url.lower():
        print("        → Computrabajo pide login.")
        input("          Logueate manualmente y presiona ENTER... ")

    btn = page.locator(
        "button:has-text('Postularme'), "
        "a:has-text('Postularme'), "
        "button:has-text('Aplicar'), "
        "a:has-text('Aplicar ahora')"
    ).first
    if btn.count():
        try:
            btn.click()
            human_pause(2, 3)
        except Exception:
            pass

    fill_form(page, profile)
    human_pause(0.8, 1.5)

    confirm = page.locator(
        "button:has-text('Postular'), "
        "button:has-text('Enviar postulación'), "
        "button:has-text('Confirmar'), "
        "button:has-text('Enviar')"
    )
    if confirm.count():
        try:
            confirm.first.click()
            human_pause(2, 4)
            print("        ✓ Postulación enviada (Computrabajo)")
            return True
        except Exception:
            pass

    print("        ⚠ Submit automático falló. Revisá la pestaña.")
    r = input("        [s] terminé manualmente / [n] saltar: ").strip().lower()
    return r == "s"


def fill_form(page: Page, profile):
    inputs = page.locator(
        "form input:not([type=hidden]):not([type=submit]):not([type=file]):not([type=checkbox]):not([type=radio]), "
        "form select, form textarea"
    ).all()
    for el in inputs:
        try:
            name = el.get_attribute("name") or ""
            placeholder = el.get_attribute("placeholder") or ""
            aria = el.get_attribute("aria-label") or ""
            label = " ".join(x for x in (aria, placeholder, name) if x)
            tag = el.evaluate("e => e.tagName.toLowerCase()")
            if tag in ("input", "textarea"):
                try:
                    if el.input_value():
                        continue
                except Exception:
                    pass
            value = autofill.match_field(label, profile)
            if value is None:
                continue
            if tag == "select":
                try:
                    el.select_option(label=str(value))
                except Exception:
                    try:
                        el.select_option(value=str(value))
                    except Exception:
                        pass
            else:
                el.fill(str(value))
        except Exception:
            continue
