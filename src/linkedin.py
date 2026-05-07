"""LinkedIn = único buscador. Para cada oferta enruta:

  - Easy Apply / Solicitud sencilla → handler interno (modal)
  - Apply externo → abre pestaña, mira dominio:
      - hiringroom.com      → handler HiringRoom
      - computrabajo.com.pe → handler Computrabajo
      - otro                → pausa, llenas manual, ENTER para seguir
"""
import time
import random
from urllib.parse import quote
from playwright.sync_api import Page, BrowserContext, TimeoutError as PWTimeout

from . import autofill, state, router, applog
from . import profile_helper as ph
from . import hiringroom as hr_handler
from . import computrabajo as ct_handler
from . import pandape as pd_handler

JOBS_URL = (
    "https://www.linkedin.com/jobs/search/"
    "?keywords={kw}&location={loc}&sortBy=DD"
)


def human_pause(a=1.5, b=3.5):
    time.sleep(random.uniform(a, b))


def login_check(page: Page):
    """Asegura que estamos logueados en LinkedIn. Reintenta tras login manual
    para que el ENTER prematuro no pise un redirect en curso."""
    def _needs_login(url: str) -> bool:
        u = (url or "").lower()
        return any(k in u for k in ("login", "checkpoint", "authwall", "signup"))

    try:
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        print(f"⚠ Error cargando LinkedIn: {str(e)[:80]}")
    human_pause(3, 5)

    while _needs_login(page.url):
        print("\n→ LinkedIn pide login/verificación.")
        print(f"  URL actual: {page.url}")
        print("  Inicia sesión manualmente en la ventana del navegador.")
        print("  Espera a estar en https://www.linkedin.com/feed/ y luego volvé acá.")
        input("  Presiona ENTER cuando estés en el feed... ")
        # Reintentar — el usuario puede haber dado ENTER mientras LinkedIn
        # todavía estaba redirigiendo de una verificación
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass
        human_pause(1, 2)
        if _needs_login(page.url):
            # Forzar navegación al feed
            try:
                page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=20000)
            except Exception:
                pass
            human_pause(2, 4)
    print("✓ Login en LinkedIn verificado")


def search_and_apply(page: Page, context: BrowserContext, conn, profile: dict, config: dict):
    login_check(page)
    daily_limit = config.get("daily_limit", 25)
    applied_today = state.count_today_applied(conn)
    print(f"\n→ Aplicadas hoy (total): {applied_today}/{daily_limit}")

    for query in config["searches"]:
        if applied_today >= daily_limit:
            print("→ Límite diario alcanzado.")
            return
        kw = quote(query["keywords"])
        loc = quote(query.get("location", "Peru"))
        # Paginación: LinkedIn muestra 25 por página, usa &start=N para offset.
        # Recorremos hasta 5 páginas (125 ofertas) o hasta que no haya nada más.
        max_pages = query.get("max_pages", 5)
        for page_num in range(max_pages):
            if applied_today >= daily_limit:
                print("→ Límite diario alcanzado.")
                return
            start = page_num * 25
            url = JOBS_URL.format(kw=kw, loc=loc)
            if start > 0:
                url += f"&start={start}"
            print(f"\n→ Buscando: {query['keywords']} en {query.get('location', 'Peru')} (página {page_num + 1})")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                print(f"  ⚠ goto error: {str(e)[:80]}")
            human_pause(3, 5)
            new_applied = process_results(page, context, conn, profile, daily_limit, applied_today)
            # Si no hubo cards o todas se aplicaron, no tiene sentido seguir paginando
            if new_applied == applied_today:
                # Cero progreso → puede ser que ya no haya más ofertas nuevas
                # Igual probamos siguiente página por si todas las de esta página
                # fueron skip (already_seen) — la próxima podría tener nuevas.
                pass
            applied_today = new_applied
            human_pause(2, 4)


def process_results(page, context, conn, profile, limit, applied_today):
    # LinkedIn carga resultados async; esperamos a que la lista renderice o
    # un mensaje de "no results"
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    # Esperar hasta 8s a que aparezca al menos una card o mensaje claro
    deadline = time.time() + 8
    while time.time() < deadline:
        if page.locator("li[data-occludable-job-id]").count() > 0:
            break
        if page.locator(".jobs-search-no-results, .jobs-search-results__no-results-banner").count() > 0:
            break
        time.sleep(0.4)

    # Probar múltiples selectores (LinkedIn cambia estructura seguido)
    selectors_to_try = [
        "li[data-occludable-job-id]",
        "div[data-job-id]",
        ".job-card-container",
        ".jobs-search-results__list-item",
        "li.scaffold-layout__list-item",
    ]
    cards = None
    count = 0
    for sel in selectors_to_try:
        c = page.locator(sel)
        n = c.count()
        if n > 0:
            cards = c
            count = n
            print(f"  Ofertas encontradas: {count} (selector: {sel})")
            break
    if cards is None or count == 0:
        print(f"  Ofertas encontradas: 0 (sin más resultados en esta página)")
        return applied_today

    # Scroll dentro del panel de resultados para forzar carga lazy
    if count > 0 and count < 20:
        try:
            for _ in range(5):
                cards.last.scroll_into_view_if_needed()
                time.sleep(0.6)
            # Re-contar después del scroll
            new_count = cards.count()
            if new_count > count:
                print(f"  → tras scroll: {new_count} cards")
                count = new_count
        except Exception:
            pass

    skipped_seen = 0
    for i in range(count):
        if applied_today >= limit:
            return applied_today
        card = cards.nth(i)
        try:
            job_id = card.get_attribute("data-occludable-job-id")
            if not job_id:
                continue
            if state.already_seen(conn, "linkedin", job_id):
                skipped_seen += 1
                continue
            card.scroll_into_view_if_needed()
            human_pause(0.5, 1.2)
            card.click()
            human_pause(1.5, 3)
            title, company = read_header(page)
            print(f"\n  [{i + 1}/{count}] {title} — {company}")
            log_ctx = {
                "killer_questions": [],
                "notes": [],
                "errors": [],
                "email_confirmation_required": False,
                "dest_url": "",
            }
            destination, applied = handle_offer(page, context, profile, log_ctx)
            status = "applied" if applied else "skipped"
            state.record(
                conn, "linkedin", job_id, destination or "unknown",
                title, company, page.url, status,
            )
            try:
                applog.write(applog.make_record(
                    source="linkedin",
                    source_job_id=job_id,
                    destination=destination or "unknown",
                    title=title,
                    company=company,
                    source_url=page.url,
                    dest_url=log_ctx.get("dest_url", ""),
                    status=status,
                    killer_questions=log_ctx.get("killer_questions", []),
                    notes=log_ctx.get("notes", []),
                    errors=log_ctx.get("errors", []),
                    email_confirmation_required=log_ctx.get("email_confirmation_required", False),
                ))
            except Exception as e:
                print(f"    ⚠ no pude escribir applog: {e}")
            if applied:
                applied_today += 1
        except Exception as e:
            print(f"    ✗ Error: {e}")
            continue
    if skipped_seen:
        print(f"  ⓘ {skipped_seen}/{count} ofertas ya procesadas en runs anteriores (skip).")
    return applied_today


def read_header(page: Page):
    title_sel = (
        ".jobs-unified-top-card__job-title, "
        ".job-details-jobs-unified-top-card__job-title, "
        "h1"
    )
    company_sel = (
        ".jobs-unified-top-card__company-name, "
        ".job-details-jobs-unified-top-card__company-name a, "
        ".job-details-jobs-unified-top-card__company-name"
    )
    title = company = ""
    try:
        title = page.locator(title_sel).first.inner_text(timeout=3000).strip()
    except PWTimeout:
        pass
    try:
        company = page.locator(company_sel).first.inner_text(timeout=3000).strip()
    except PWTimeout:
        pass
    return title, company


def handle_offer(page: Page, context: BrowserContext, profile: dict, log_ctx: dict = None):
    """Devuelve (destination, applied: bool). log_ctx (dict) se rellena con
    metadata para que el caller escriba el applog."""
    btn = page.locator("button.jobs-apply-button").first
    if btn.count() == 0:
        print("    → Sin botón de Apply visible, salto.")
        return None, False

    try:
        btn_text = (btn.inner_text(timeout=1000) or "").strip().lower()
    except Exception:
        btn_text = ""
    try:
        btn_aria = (btn.get_attribute("aria-label") or "").lower()
    except Exception:
        btn_aria = ""
    blob = btn_text + " " + btn_aria

    is_easy = "easy apply" in blob or "solicitud sencilla" in blob

    if is_easy:
        print("    → Easy Apply detectado")
        try:
            btn.click()
            human_pause(1.5, 3)
            ok = walk_easy_apply_modal(page, profile)
            return "linkedin", ok
        except Exception as e:
            print(f"    ✗ Error en Easy Apply: {e}")
            if log_ctx is not None:
                log_ctx.setdefault("errors", []).append(f"Easy Apply: {str(e)[:100]}")
            return "linkedin", False

    # Externo
    print("    → Apply externo, abriendo destino...")
    return handle_external_apply(page, context, btn, profile, log_ctx)


def handle_external_apply(page, context, btn, profile, log_ctx: dict = None):
    new_page = None
    try:
        with context.expect_page(timeout=15000) as new_page_info:
            btn.click()
            # LinkedIn a veces muestra un modal de confirmación antes
            try:
                page.locator(
                    "button:has-text('Continue'), button:has-text('Continuar')"
                ).first.click(timeout=2000)
            except Exception:
                pass
        new_page = new_page_info.value
        new_page.wait_for_load_state("domcontentloaded", timeout=20000)
    except Exception as e:
        print(f"    ✗ No abrió pestaña externa: {e}")
        return "unknown", False

    dest_url = new_page.url
    domain = router.short_domain(dest_url)
    route = router.route_for_url(dest_url)

    if log_ctx is not None:
        log_ctx["dest_url"] = dest_url

    print(f"    → {domain}")

    try:
        if route == "hiringroom":
            ok = hr_handler.apply_on_page(new_page, profile, log_ctx)
            try:
                new_page.close()
            except Exception:
                pass
            return "hiringroom", ok
        if route == "computrabajo":
            ok = ct_handler.apply_on_page(new_page, profile)
            try:
                new_page.close()
            except Exception:
                pass
            return "computrabajo", ok
        if route == "pandape":
            ok = pd_handler.apply_on_page(new_page, profile, log_ctx)
            try:
                new_page.close()
            except Exception:
                pass
            return "pandape", ok

        # Manual
        print(f"    ⚠ Plataforma no automatizada: {domain}")
        print(f"      Llena la postulación manualmente en la pestaña abierta.")
        print(f"      Cuando termines:")
        print(f"        ENTER       → registrar como APLICADA y continuar")
        print(f"        n + ENTER   → registrar como SALTADA y continuar")
        r = input("      Tu acción: ").strip().lower()
        return f"manual:{domain}", (r != "n")
    finally:
        if new_page and not new_page.is_closed():
            try:
                new_page.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Easy Apply modal walker
# ---------------------------------------------------------------------------

def walk_easy_apply_modal(page: Page, profile, max_steps=15) -> bool:
    modal = "div.jobs-easy-apply-modal, div[data-test-modal][role='dialog']"
    for _ in range(max_steps):
        if page.locator(modal).count() == 0:
            return False
        fill_modal_fields(page, profile)
        human_pause(0.8, 1.8)

        submit = page.locator(
            "button[aria-label='Submit application'], "
            "button[aria-label='Enviar solicitud']"
        )
        if submit.count() and submit.first.is_visible():
            uncheck_follow(page)
            submit.first.click()
            human_pause(2, 4)
            close_post_modal(page)
            print("    ✓ Aplicado (LinkedIn Easy Apply)")
            return True

        review = page.locator(
            "button[aria-label='Review your application'], "
            "button[aria-label='Revisar la solicitud']"
        )
        if review.count() and review.first.is_visible():
            review.first.click()
            human_pause(1, 2)
            continue

        nxt = page.locator(
            "button[aria-label='Continue to next step'], "
            "button[aria-label='Continuar al siguiente paso']"
        )
        if nxt.count() and nxt.first.is_visible():
            nxt.first.click()
            human_pause(1, 2)
            continue

        print("    ⚠ Modal no avanza. Saltando.")
        dismiss_modal(page)
        return False
    dismiss_modal(page)
    return False


def fill_modal_fields(page: Page, profile):
    flat = ph.flatten(profile)
    modal_scope = (
        "div.jobs-easy-apply-modal, "
        "div[data-test-modal][role='dialog'], "
        "div[role='dialog']"
    )

    # Buscar cada wrapper de form element (LinkedIn lo marca con data-test-form-element)
    form_wrappers = page.locator(f"{modal_scope} [data-test-form-element]").all()
    if not form_wrappers:
        # Fallback: buscar labels directamente
        form_wrappers = page.locator(f"{modal_scope} label").all()

    for wrapper in form_wrappers:
        try:
            _fill_modal_field(page, wrapper, flat)
        except Exception:
            continue

    # Radio fieldsets (preguntas Yes/No)
    for fs in page.locator(f"{modal_scope} fieldset").all():
        try:
            legend = fs.locator("legend").first.inner_text(timeout=400).strip()
            if not legend or fs.locator("input[type=radio]:checked").count():
                continue
            value = autofill.match_field(legend, flat) or autofill.ask_user(legend)
            if value is None:
                continue
            opt = fs.locator(f"label:has-text('{value}')").first
            if opt.count():
                opt.click()
        except Exception:
            continue


def _fill_modal_field(page: Page, wrapper, flat):
    """Llena un wrapper de form element del modal de Easy Apply."""
    # Texto del label (puede estar en <label>, <span aria-hidden>, o el primer span legible)
    label_text = ""
    for sel in ("label", "span[aria-hidden='true']", "legend"):
        try:
            el = wrapper.locator(sel).first
            if el.count():
                t = (el.inner_text(timeout=400) or "").strip()
                if t:
                    label_text = t
                    break
        except Exception:
            continue
    if not label_text:
        return

    # Encontrar el input/select/textarea dentro del wrapper
    input_el = wrapper.locator("input, select, textarea").first
    if input_el.count() == 0:
        return
    try:
        tag = input_el.evaluate("e => e.tagName.toLowerCase()")
    except Exception:
        return

    # Si ya tiene valor, saltar
    try:
        if tag in ("input", "textarea") and input_el.input_value():
            return
        if tag == "select":
            current = input_el.input_value()
            if current and current.strip().lower() not in ("", "select an option", "seleccione", "seleccione una opción"):
                return
    except Exception:
        pass

    value = autofill.match_field(label_text, flat)
    if value is None:
        value = autofill.ask_user(label_text)
        if value is None:
            return

    if tag == "select":
        _select_smart(input_el, str(value), label_text)
        return

    # Detectar typeahead (combobox con autocomplete)
    is_typeahead = False
    try:
        role = input_el.get_attribute("role") or ""
        autocomplete = input_el.get_attribute("aria-autocomplete") or ""
        if role == "combobox" or autocomplete == "list":
            is_typeahead = True
    except Exception:
        pass

    if is_typeahead:
        _fill_typeahead(page, input_el, str(value))
    else:
        try:
            input_el.fill(str(value))
        except Exception:
            try:
                input_el.evaluate(
                    "(el, v) => { el.value = v; "
                    "el.dispatchEvent(new Event('input', {bubbles:true})); "
                    "el.dispatchEvent(new Event('change', {bubbles:true})); }",
                    str(value),
                )
            except Exception:
                pass


def _select_smart(input_el, value: str, label_text: str = ""):
    """Selecciona opción de un <select> con varias estrategias de fallback."""
    v = (value or "").strip()
    if not v:
        return False
    # 1. Match exacto por label
    try:
        input_el.select_option(label=v)
        return True
    except Exception:
        pass
    # 2. Match exacto por value
    try:
        input_el.select_option(value=v)
        return True
    except Exception:
        pass
    # 3. Match por substring en label de cada opción
    try:
        options = input_el.evaluate(
            "el => Array.from(el.options).map(o => ({value: o.value, text: (o.textContent||'').trim()}))"
        )
        v_lower = v.lower()
        for opt in options:
            t = (opt.get("text") or "").lower()
            if v_lower and v_lower in t:
                input_el.select_option(value=opt["value"])
                return True
        # 4. Para email: si profile no matchea, usar la primera opción válida (LinkedIn solo muestra emails verificados)
        if "email" in (label_text or "").lower() or "correo" in (label_text or "").lower():
            for opt in options:
                val = opt.get("value") or ""
                if val and val.lower() not in ("select an option", "", "seleccione"):
                    input_el.select_option(value=val)
                    return True
    except Exception:
        pass
    return False


def _fill_typeahead(page: Page, input_el, value: str):
    """Llena un campo typeahead (combobox autocomplete): tipea, espera sugerencias,
    presiona ArrowDown + Enter para seleccionar la primera."""
    try:
        input_el.click()
        input_el.fill("")
        input_el.type(value, delay=40)
        # Esperar que aparezcan sugerencias
        for _ in range(8):
            time.sleep(0.25)
            try:
                if page.locator("[role='option']:visible, [role='listbox'] li:visible").count():
                    break
            except Exception:
                continue
        # Intentar click en la primera sugerencia
        opt = page.locator("[role='option']:visible, [role='listbox'] li:visible").first
        clicked = False
        if opt.count():
            try:
                opt.click(timeout=2000)
                clicked = True
            except Exception:
                pass
        if not clicked:
            # Fallback: ArrowDown + Enter
            try:
                input_el.press("ArrowDown")
                time.sleep(0.2)
                input_el.press("Enter")
            except Exception:
                pass
    except Exception:
        try:
            input_el.fill(value)
        except Exception:
            pass


def uncheck_follow(page: Page):
    try:
        chk = page.locator("label:has-text('Follow')").first
        if chk.count() and chk.is_visible():
            chk.click()
    except Exception:
        pass


def dismiss_modal(page: Page):
    try:
        page.locator("button[aria-label='Dismiss']").first.click(timeout=2000)
        human_pause(0.5, 1)
        discard = page.locator(
            "button:has-text('Discard'), button:has-text('Descartar')"
        ).first
        if discard.count():
            discard.click()
    except Exception:
        pass


def close_post_modal(page: Page):
    try:
        page.locator("button[aria-label='Dismiss']").first.click(timeout=3000)
    except Exception:
        pass


def css_escape(s: str) -> str:
    return s.replace(":", r"\:").replace(".", r"\.")
