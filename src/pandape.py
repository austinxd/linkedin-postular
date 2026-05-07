"""Handler Pandapé — fill from semantic profile.json + mappings.

Estrategia:
  1. (Opcional) Subir CV al input #CvInputFile para que el parser de Pandapé
     intente rellenar experiencia y educación.
  2. Llenar TODOS los campos simples desde el profile.json semántico,
     usando mappings.PANDAPE para traducir valores semánticos a IDs.
  3. Adjuntar CV en #fileIncludeCV (sección perfil profesional).
  4. Marcar checkboxes de términos.
  5. Click en Submit (#btnSendCV).

NOTAS:
  - parse_cv=True (default): sube el CV para parseo. Después sobrescribimos lo
    mal formateado.
  - parse_cv=False: salta el parseo y llena todo desde el config.
  - Las secciones dinámicas (experience[], education[], languages[], skills[])
    NO se llenan automáticamente todavía. Requieren dump del HTML del sub-form
    que aparece al click "+ Incluir experiencia". Por ahora se cubren con el
    parseo del CV o quedan para review manual.
"""
import re
import time
import random
from pathlib import Path
from urllib.parse import urljoin
from playwright.sync_api import Page, TimeoutError as PWTimeout

from . import mappings
from . import profile_helper as ph
from . import llm

ROOT = Path(__file__).parent.parent

PARSE_CV = True  # cambiar a False para saltar parseo y llenar todo desde config


def human_pause(a=1.5, b=3.5):
    time.sleep(random.uniform(a, b))


# ---------------------------------------------------------------------------
# Definiciones declarativas: selector → (path en profile, override)
# ---------------------------------------------------------------------------

# Campos que SIEMPRE sobrescribimos (parser deforma)
# NOTA: #BirthDate se maneja aparte en fill_birth_date() porque es un datepicker.
TEXT_OVERWRITE = [
    ("#Phone", "contact.phone.local"),
    ("#Phone2", "contact.phone.local"),
    ("#PrefixPhone", "contact.phone.country_code_digits"),  # virtual
    ("#PrefixPhone2", "contact.phone.country_code_digits"),
    ("#CPF", "personal.document_number"),
    ("#AddressNumber", "contact.address.number"),
    ("#AddressComplement", "contact.address.complement"),
    ("#SalaryMin", "preferences.salary_min"),
    ("#SalaryMax", "preferences.salary_max"),
]

# Campos que solo llenamos si están vacíos (parser suele acertar)
TEXT_IF_EMPTY = [
    ("#Name", "personal.first_name"),
    ("#Surname", "personal.last_name"),
    ("#Address", "contact.address.street"),
    ("#Email", "contact.email"),
    ("#Job", "professional.current_position"),
    ("#PreferredJob", "professional.desired_position"),
    ("#Summary", "professional.summary"),
    ("#IdSkype", "contact.skype"),
]

# Selects: selector → (path semántico, campo del mapping)
# Valor del profile se traduce con mappings.map_value
SELECTS_SEMANTIC = [
    ("#Sex",                          "personal.gender",          "gender"),
    ("#Children",                     "personal.has_children",    "has_children"),
    ("#MaritalStatus",                "personal.marital_status",  "marital_status"),
    ("#IdentificationDocumentType",   "personal.document_type",   "document_type"),
    ("#WorkingHour",                  "preferences.working_hour", "working_hour"),
    ("#ContractWorkTypes",            "preferences.contract_type","contract_type"),
    ("#Nationality",                  "personal.nationality",     "nationality"),
    ("#Location1",                    "contact.address.country",  "country"),
]

TERMS_CHECKBOXES = [
    "#HasAcceptedTerms",
    "#HasAcceptedIJInformation",
]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def apply_on_page(page: Page, profile: dict, log_ctx: dict = None) -> bool:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except PWTimeout:
        pass
    human_pause(2, 4)

    if detect_already_applied(page):
        print("        → Ya postulado anteriormente (Pandapé)")
        if log_ctx is not None:
            log_ctx.setdefault("notes", []).append("Ya postulado anteriormente (detectado al cargar)")
        return True

    # Algunos enlaces de Pandapé muestran primero un step de identificación
    # (botón "Continuar con Computrabajo" + campo de email) antes del form real.
    # Intentamos navegar ese pre-form, y si no podemos, pedimos ayuda manual.
    if not ensure_form_loaded(page, profile):
        # Caso común: tras submit del email, Pandapé muestra "ya postulaste"
        if detect_already_applied(page):
            print("        → Ya postulado anteriormente (Pandapé) — detectado tras email")
            if log_ctx is not None:
                log_ctx.setdefault("notes", []).append("Ya postulado anteriormente (tras email)")
            return True
        print("        ⚠ No se cargó el formulario tras la identificación.")
        return manual_fallback()

    if PARSE_CV:
        try_import_from_file(page, profile)

    expand_collapsed_sections(page)
    human_pause(0.5, 1.2)

    upload_cv_attachment(page, profile)

    fill_all_fields(page, profile)
    human_pause(0.8, 1.5)

    fill_birth_date(page, profile)
    human_pause(0.3, 0.8)

    fill_postal_code(page, profile)
    human_pause(0.5, 1)

    fill_experience_areas(page, profile)
    human_pause(0.3, 0.8)

    fill_dynamic_dates(page, "Experiences", profile.get("experience", []))
    fill_dynamic_dates(page, "Studies", profile.get("education", []))
    human_pause(0.3, 0.8)

    fill_education_levels(page, profile)
    human_pause(0.3, 0.6)

    retry_empty_dates(page, profile)
    human_pause(0.3, 0.6)

    audit_dates(page)

    accept_terms(page)
    human_pause(0.5, 1)

    return try_submit(page, profile, log_ctx)


def ensure_form_loaded(page: Page, profile: dict) -> bool:
    """Navega los pasos previos hasta caer en el formulario real.

    Pandapé tiene 3 estados posibles tras venir desde LinkedIn:
      A) /Detail/{id}     → página informativa con dropdown "APLICAR"
      B) /Apply (email)   → form de email (#BtnSendEmail)
      C) /Apply (form)    → form real (#CvInputFile + #btnSendCV)
    """
    if is_on_real_form(page):
        return True

    # Paso A → B: navegar desde la página de detalle
    if not is_on_email_step(page):
        try:
            href = page.locator("a[href*='/ApplyCT/']").first.get_attribute("href")
        except Exception:
            href = None
        if href:
            full_url = href if href.startswith("http") else urljoin(page.url, href)
            try:
                print(f"        → Navegando a {href}")
                page.goto(full_url, timeout=20000)
                human_pause(2, 4)
            except Exception as e:
                print(f"        ⚠ No pude navegar: {e}")

    if is_on_real_form(page):
        print("        → Formulario cargado")
        return True

    # Paso B → C: completar email si aparece el step
    if is_on_email_step(page):
        email = (profile.get("contact", {}) or {}).get("email", "")
        if email:
            try:
                el = page.locator("#Email").first
                if el.count():
                    el.fill(email)
                    human_pause(0.5, 1.2)
            except Exception as e:
                print(f"        ⚠ No pude llenar email: {e}")
        try:
            print("        → Click en Continuar (email)")
            btn = page.locator("#BtnSendEmail").first
            if btn.count():
                btn.click()
                human_pause(3, 5)
        except Exception as e:
            print(f"        ⚠ No pude clickear Continuar: {e}")

    if is_on_real_form(page):
        print("        → Formulario cargado")
        return True
    if detect_already_applied(page):
        return False  # caller detectará y manejará como éxito

    # Esperar un poco más por si la navegación demora
    for _ in range(10):
        if is_on_real_form(page):
            print("        → Formulario cargado")
            return True
        if detect_already_applied(page):
            return False
        time.sleep(0.5)

    # Plan B manual
    print(f"\n        ⚠ No pude llegar al formulario automáticamente.")
    print(f"        URL actual: {page.url}")
    print( "        En la pestaña abierta, completa lo que falte hasta ver el form de candidatura.")
    input( "        ENTER cuando veas el formulario completo (o Ctrl+C para abortar): ")
    return is_on_real_form(page)


def is_on_email_step(page: Page) -> bool:
    return page.locator("#BtnSendEmail").count() > 0


def is_on_real_form(page: Page) -> bool:
    return page.locator("#CvInputFile").count() > 0 or page.locator("#btnSendCV").count() > 0


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def try_import_from_file(page: Page, profile: dict) -> bool:
    cv_path = ROOT / (profile.get("cv_path") or "cv/alex_ats.docx")
    if not cv_path.exists():
        print(f"        ⚠ CV no existe: {cv_path}")
        return False
    inp = page.locator("#CvInputFile")
    if inp.count() == 0:
        return False
    try:
        inp.set_input_files(str(cv_path))
        print(f"        → Importando datos desde archivo ({cv_path.name})...")
        human_pause(4, 6)
        return True
    except Exception as e:
        print(f"        ⚠ Falló import desde archivo: {e}")
        return False


def expand_collapsed_sections(page: Page):
    """Fuerza apertura de todas las secciones Bootstrap collapse + dispara
    los eventos para que jQuery datepicker se inicialice en los inputs nuevos.
    No depende de la animación de Bootstrap."""
    try:
        page.evaluate(
            """() => {
                if (window.jQuery) {
                    try { jQuery('.collapse:not(.show)').collapse('show'); } catch(e) {}
                    jQuery('.js_btnCollapse.collapsed')
                        .removeClass('collapsed')
                        .attr('aria-expanded', 'true');
                }
                document.querySelectorAll('.collapse').forEach(el => {
                    el.classList.add('show');
                    el.style.removeProperty('height');
                });
                if (window.jQuery) {
                    try { jQuery('.collapse').trigger('shown.bs.collapse'); } catch(e) {}
                }
            }"""
        )
    except Exception as e:
        print(f"        ⚠ expand_collapsed_sections: {str(e)[:60]}")
    time.sleep(0.6)  # tiempo para que jQuery datepicker termine de inicializar


def upload_cv_attachment(page: Page, profile: dict):
    cv_path = ROOT / (profile.get("cv_path") or "cv/alex_ats.docx")
    if not cv_path.exists():
        return
    try:
        inp = page.locator("#fileIncludeCV").first
        if inp.count() == 0:
            return
        inp.set_input_files(str(cv_path))
        print("        → CV adjuntado en perfil profesional")
        human_pause(1.5, 2.5)
    except Exception:
        pass


def fill_all_fields(page: Page, profile: dict):
    # Phone country code: extraer dígitos de "+51"
    cc = ph.get(profile, "contact.phone.country_code", "")
    if cc:
        cc_digits = "".join(c for c in cc if c.isdigit()) or "51"
        # Inyectamos virtualmente para TEXT_OVERWRITE
        # (no modifica profile, solo hace match con la "ruta virtual")
    else:
        cc_digits = "51"

    # Sobreescribir
    for sel, path in TEXT_OVERWRITE:
        if path == "contact.phone.country_code_digits":
            val = cc_digits
        else:
            val = ph.get(profile, path, "")
        if val is None or str(val).strip() == "":
            continue
        _force_fill(page, sel, str(val))

    # Solo si vacío
    for sel, path in TEXT_IF_EMPTY:
        val = ph.get(profile, path, "")
        if val is None or str(val).strip() == "":
            continue
        try:
            el = page.locator(sel).first
            if el.count() == 0:
                continue
            try:
                current = el.input_value()
                if current and current.strip():
                    continue
            except Exception:
                pass
            _force_fill(page, sel, str(val))
        except Exception:
            continue

    # Selects con mapping semántico → ID
    for sel, path, field in SELECTS_SEMANTIC:
        semantic = ph.get(profile, path, "")
        if not semantic:
            continue
        platform_id = mappings.map_value("pandape", field, semantic, default="")
        if not platform_id:
            continue
        try:
            el = page.locator(sel).first
            if el.count() == 0:
                continue
            try:
                el.select_option(value=platform_id)
            except Exception:
                pass
        except Exception:
            continue

    # Booleans en Información Adicional
    pref = profile.get("preferences", {}) or {}
    if pref.get("willing_to_travel"):
        _check(page, "#Travel")
    if pref.get("willing_to_relocate"):
        _check(page, "#ChangeResidence")


def fill_birth_date(page: Page, profile: dict):
    """#BirthDate es un jQuery datepicker. Necesita estrategia especial:
      1. Quitar atributo readonly si el plugin lo agregó.
      2. Set value via JS + trigger eventos jQuery (change, blur).
      3. Verificar que quedó. Si no, intento type() carácter por carácter.
    """
    value = ((profile.get("personal", {}) or {}).get("birth_date") or "").strip()
    if not value or value.upper().startswith("DD/"):
        if value.upper().startswith("DD/"):
            print("        ⚠ birth_date sigue siendo placeholder 'DD/MM/YYYY' en profile.json")
        return

    el = page.locator("#BirthDate").first
    if el.count() == 0:
        print("        ⚠ #BirthDate no encontrado en la página")
        return

    # Estrategia 1: JS directo (más confiable con jQuery datepickers)
    try:
        page.evaluate(
            """(v) => {
                const el = document.getElementById('BirthDate');
                if (!el) return;
                el.removeAttribute('readonly');
                if (window.jQuery) {
                    const $el = jQuery(el);
                    $el.val(v);
                    try { $el.datepicker('setDate', v); } catch (e) {}
                    $el.trigger('input').trigger('change').trigger('blur');
                } else {
                    el.value = v;
                    el.dispatchEvent(new Event('input', {bubbles:true}));
                    el.dispatchEvent(new Event('change', {bubbles:true}));
                    el.dispatchEvent(new Event('blur', {bubbles:true}));
                }
            }""",
            value,
        )
        human_pause(0.3, 0.6)
        actual = el.input_value()
        if actual.strip():
            print(f"        → Fecha nacimiento: {actual}")
            return
    except Exception as e:
        print(f"        ⚠ JS fill BirthDate falló: {e}")

    # Estrategia 2: type() simulando teclado
    try:
        el.click(force=True)
        human_pause(0.2, 0.5)
        try:
            page.keyboard.press("Escape")  # cerrar picker UI si abrió
        except Exception:
            pass
        # Limpiar y tipear
        el.evaluate("e => e.value = ''")
        el.type(value, delay=50)
        page.keyboard.press("Tab")
        human_pause(0.3, 0.6)
        actual = el.input_value()
        if actual.strip():
            print(f"        → Fecha nacimiento: {actual} (via type)")
            return
    except Exception as e:
        print(f"        ⚠ type() BirthDate falló: {e}")

    print(f"        ⚠ No pude llenar birth_date={value!r}; queda en blanco.")


def fill_postal_code(page: Page, profile: dict):
    """Pandapé usa Select2 con AJAX para código postal.

    Estrategia:
      1. Abrir el Select2 (preferimos JS porque el DOM nativo lo confunde).
      2. Escribir el código en el search.
      3. Esperar la AJAX, click en el primer resultado.
    """
    code = ((profile.get("contact", {}) or {}).get("address", {}) or {}).get("postal_code", "")
    if not code:
        return
    code = str(code).strip()
    if not code:
        return

    # 1) Abrir el dropdown Select2 — primer intento por JS (la API oficial)
    opened = False
    try:
        page.evaluate(
            "() => { if (window.jQuery && jQuery('#selectPostalCode').length) "
            "{ jQuery('#selectPostalCode').select2('open'); return true; } return false; }"
        )
        human_pause(0.4, 0.8)
        opened = page.locator(".select2-search__field").count() > 0
    except Exception:
        pass

    # 1b) Fallback: click en el contenedor combobox
    if not opened:
        try:
            combo = page.locator(
                ".select2-selection[aria-labelledby='select2-selectPostalCode-container']"
            ).first
            if combo.count() == 0:
                combo = page.locator("#selectPostalCode + .select2 .select2-selection").first
            if combo.count():
                combo.scroll_into_view_if_needed()
                combo.click(force=True, timeout=5000)
                human_pause(0.4, 0.8)
                opened = page.locator(".select2-search__field").count() > 0
        except Exception:
            pass

    if not opened:
        print("        ⚠ No pude abrir el Select2 de código postal")
        return

    # 2) Escribir el código
    try:
        search = page.locator(".select2-search__field").first
        search.fill(code)
        human_pause(2.5, 3.5)  # esperar AJAX
    except Exception as e:
        print(f"        ⚠ No pude escribir en Select2: {e}")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return

    # 3) Buscar opción que matchee la ciudad del profile, fallback al primero
    city = (((profile.get("contact", {}) or {}).get("address", {}) or {}).get("city", "") or "").strip().lower()
    try:
        results = page.locator(
            ".select2-results__option:not(.loading-results):not(.select2-results__message)"
        ).all()
        if not results:
            print(f"        ⚠ Sin resultados para postal {code}")
            return

        target = None
        target_text = ""
        if city:
            for r in results:
                try:
                    text = (r.inner_text(timeout=300) or "").strip()
                    if city in text.lower():
                        target = r
                        target_text = text
                        break
                except Exception:
                    continue

        if target is None:
            target = results[0]
            try:
                target_text = target.inner_text(timeout=300).strip()
            except Exception:
                target_text = "(?)"
            print(f"        ⚠ No matcheó city '{city}' en {len(results)} opciones, usando primera: {target_text!r}")
        else:
            print(f"        → Código postal: {target_text}")

        target.click(timeout=3000)
        human_pause(0.5, 1)
    except Exception as e:
        print(f"        ⚠ No pude seleccionar resultado: {e}")
    finally:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass


def fill_education_levels(page: Page, profile: dict):
    """Llena el select 'Nivel' (Studies[].IdStudy1) en cada entrada de educación.

    Mapea por:
      1. profile.education[i].level si existe
      2. profile.education[i].degree (e.g. 'MBA', 'Bachiller')
      Match con keywords en mappings.PANDAPE_EDU_LEVEL_KEYWORDS.
    """
    education = profile.get("education", []) or []
    if not education:
        return
    selects = page.locator("select[name*='Studies['][name*='.IdStudy1']").all()
    if not selects:
        return

    print(f"        → Niveles educativos en {len(selects)} estudio(s)")
    for i, sel in enumerate(selects):
        if i >= len(education):
            break
        edu = education[i]
        text = edu.get("level") or edu.get("degree") or edu.get("field") or ""
        level_id = mappings.match_pandape_education_level(text)
        if not level_id:
            print(f"        ⚠ [edu {i}] sin match para nivel, texto={text!r}")
            continue
        try:
            sel.select_option(value=level_id)
        except Exception:
            try:
                sel.evaluate(
                    "(el, v) => { el.value = v; "
                    "el.dispatchEvent(new Event('change', {bubbles:true})); }",
                    level_id,
                )
            except Exception:
                continue


def fill_experience_areas(page: Page, profile: dict):
    """Cada experience entry creada por el parser tiene un select
    `name="Experiences[GUID].IdCategory1"` que requiere el área (Category1).
    Iteramos en orden y mapeamos al area de profile.experience[i]."""
    experiences = profile.get("experience", []) or []
    if not experiences:
        return

    selects = page.locator("select[name*='IdCategory1']").all()
    if not selects:
        return

    print(f"        → Asignando área en {len(selects)} experiencias")
    for i, sel in enumerate(selects):
        if i >= len(experiences):
            break
        exp = experiences[i]
        area_text = exp.get("area") or exp.get("title") or ""
        area_id = mappings.match_pandape_area(area_text)
        if not area_id:
            continue
        try:
            sel.select_option(value=area_id)
        except Exception:
            try:
                sel.evaluate(
                    "(el, v) => { el.value = v; "
                    "el.dispatchEvent(new Event('change', {bubbles:true})); }",
                    area_id,
                )
            except Exception:
                continue


_LAST_DAY_OF_MONTH = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
                       7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


def normalize_date(value, position: str = "start") -> str:
    """Normaliza fechas a DD/MM/YYYY que es lo que espera el regex de Pandapé.

    Acepta:
      - DD/MM/YYYY → passthrough
      - MM/YYYY    → 01/MM/YYYY (start) ó último-día/MM/YYYY (end)
      - YYYY       → 01/01/YYYY (start) ó 31/12/YYYY (end)
      - "" / None → ""
    """
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    if re.match(r"^\d{2}/\d{2}/\d{4}$", s):
        return s
    m = re.match(r"^(\d{1,2})/(\d{4})$", s)
    if m:
        month = int(m.group(1))
        year = m.group(2)
        if position == "end":
            day = _LAST_DAY_OF_MONTH.get(month, 28)
            return f"{day:02d}/{month:02d}/{year}"
        return f"01/{month:02d}/{year}"
    if re.match(r"^\d{4}$", s):
        return ("31/12/" if position == "end" else "01/01/") + s
    return s  # último recurso: lo que sea, lo dejamos


def fill_dynamic_dates(page: Page, section: str, entries: list):
    """Llena BeginDate y EndDate de las entries de una sección dinámica
    (Experiences o Studies). Asume mismo orden DOM ↔ profile.

    Para entradas con is_current=true:
      - Marca el checkbox CurrentlyWorking (solo aplica a Experiences).
      - Limpia EndDate (el parser pone hoy por default y eso es incorrecto).
    """
    if not entries:
        return
    begins = page.locator(f"input[name*='{section}['][name*='].BeginDate']").all()
    ends = page.locator(f"input[name*='{section}['][name*='].EndDate']").all()
    currents = []
    if section == "Experiences":
        currents = page.locator(
            f"input[name*='{section}['][name*='].CurrentlyWorking']"
        ).all()
    if not begins and not ends:
        return

    section_label = "experiencia" if section == "Experiences" else "educación"
    print(f"        → Fechas en {len(begins)} {section_label}(s)")

    for i, entry in enumerate(entries):
        is_current = bool(entry.get("is_current")) and section == "Experiences"
        company = entry.get("company") or entry.get("institution") or entry.get("title") or f"#{i}"
        company_short = company[:30]

        # BeginDate
        if i < len(begins):
            begin = normalize_date(entry.get("start_date"), "start")
            if begin:
                ok = _fill_datepicker(page, begins[i], begin)
                if not ok:
                    print(f"        ⚠ [{i}] {company_short}: BeginDate {begin} NO se llenó")

        # CurrentlyWorking checkbox
        if is_current and i < len(currents):
            try:
                if not currents[i].is_checked():
                    currents[i].check(force=True)
                    print(f"        → [{i}] {company_short}: marcado 'Actualmente trabajo aquí'")
            except Exception as e:
                print(f"        ⚠ [{i}] CurrentlyWorking: {str(e)[:60]}")

        # EndDate
        if i < len(ends):
            if is_current:
                # Limpiar el valor que el parser dejó (típicamente "hoy")
                try:
                    ends[i].evaluate(
                        """el => {
                            el.removeAttribute('readonly');
                            el.value = '';
                            if (window.jQuery) {
                                const $el = jQuery(el);
                                $el.val('');
                                $el.removeAttr('value');
                                $el.trigger('input').trigger('change').trigger('blur');
                                try { $el.valid(); } catch (e) {}
                            }
                        }"""
                    )
                except Exception:
                    pass
            else:
                end = normalize_date(entry.get("end_date"), "end")
                if end:
                    ok = _fill_datepicker(page, ends[i], end)
                    if not ok:
                        print(f"        ⚠ [{i}] {company_short}: EndDate {end} NO se llenó")


def _fill_datepicker(page: Page, locator, value: str) -> bool:
    """Llena un datepicker (jQuery UI). Estrategia JS primero, type() como fallback.
    Verifica que el valor quedó. Devuelve True si se logró."""
    if not value:
        return False

    # Estrategia 1: JS — re-set value entre cada evento porque jQuery datepicker
    # blur handler suele re-parsear y limpiar si la fecha no matchea su parse.
    try:
        locator.evaluate(
            """(el, v) => {
                const setVal = () => {
                    el.removeAttribute('readonly');
                    el.setAttribute('aria-invalid', 'false');
                    el.value = v;
                    el.setAttribute('value', v);
                };
                setVal();
                if (window.jQuery) {
                    const $el = jQuery(el);
                    $el.val(v);
                    $el.attr('value', v);
                    try { $el.datepicker('setDate', v); } catch (e) {}
                    setVal();
                    $el.trigger('keyup').trigger('input').trigger('change');
                    setVal();
                    try { $el.valid(); } catch (e) {}
                    setVal();

                    const $group = $el.closest('.form-group');
                    $group.removeClass('has-danger').addClass('has-success');
                    const $errSpan = $group.find('span.field-validation-error');
                    $errSpan.removeClass('field-validation-error').addClass('field-validation-valid').empty();
                    $group.find('span[id$=\"-error\"]').empty();
                } else {
                    el.dispatchEvent(new Event('input', {bubbles:true}));
                    el.dispatchEvent(new Event('change', {bubbles:true}));
                }
            }""",
            value,
        )
        # Verificación con reintentos: si el valor desaparece, re-setearlo
        for _ in range(4):
            try:
                actual = (locator.input_value() or "").strip()
            except Exception:
                actual = ""
            if actual:
                return True
            try:
                locator.evaluate(
                    "(el, v) => { el.value = v; el.setAttribute('value', v); }",
                    value,
                )
            except Exception:
                break
            time.sleep(0.25)
    except Exception:
        pass

    # Estrategia 2: type() simulando teclado (requiere visibilidad)
    try:
        locator.scroll_into_view_if_needed()
        locator.click(force=True)
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        locator.evaluate("e => { e.removeAttribute('readonly'); e.value = ''; }")
        locator.type(value, delay=40)
        try:
            page.keyboard.press("Tab")
        except Exception:
            pass
        if (locator.input_value() or "").strip():
            return True
    except Exception as e:
        print(f"        ⚠ type() datepicker {value}: {str(e)[:60]}")

    print(f"        ⚠ no quedó valor {value} en datepicker")
    return False


def retry_empty_dates(page: Page, profile: dict):
    """Tras la primera pasada, algunos datepickers pueden quedar vacíos.
    Re-intenta llenándolos haciendo match por empresa/institución (no por orden DOM)."""
    state = page.evaluate(
        """() => {
            const out = [];
            const rows = document.querySelectorAll('.js_divExperience, .js_divAggregate');
            rows.forEach(row => {
                const company = (row.querySelector("input[name$='.Company']") || {}).value || '';
                const institution = (row.querySelector("input[name$='.Institution'], input[name$='.School']") || {}).value || '';
                const begin = row.querySelector("input.js_beginDate");
                const end = row.querySelector("input.js_endDate");
                out.push({
                    company: company.trim(),
                    institution: institution.trim(),
                    beginVal: begin ? begin.value : '',
                    beginName: begin ? begin.name : '',
                    endVal: end ? end.value : '',
                    endName: end ? end.name : '',
                });
            });
            return out;
        }"""
    )

    experiences = profile.get("experience", []) or []
    education = profile.get("education", []) or []

    for row in state:
        # Match por empresa o institución (case-insensitive, contiene)
        target_entry = None
        if row["company"]:
            for e in experiences:
                ec = (e.get("company") or "").lower()
                if ec and (ec in row["company"].lower() or row["company"].lower() in ec):
                    target_entry = e
                    break
        if target_entry is None and row["institution"]:
            for e in education:
                ei = (e.get("institution") or "").lower()
                if ei and (ei in row["institution"].lower() or row["institution"].lower() in ei):
                    target_entry = e
                    break
        if target_entry is None:
            continue

        is_current = bool(target_entry.get("is_current"))

        # Retry BeginDate si está vacío
        if not row["beginVal"].strip() and row["beginName"]:
            begin_val = normalize_date(target_entry.get("start_date"), "start")
            if begin_val:
                loc = page.locator(f"input[name='{row['beginName']}']").first
                ok = _fill_datepicker(page, loc, begin_val)
                label = row["company"] or row["institution"]
                if ok:
                    print(f"        ↻ retry BeginDate {label[:30]} = {begin_val}")
                else:
                    print(f"        ⚠ retry BeginDate {label[:30]} FALLÓ")

        # Retry EndDate si vacío y no es current
        if not row["endVal"].strip() and row["endName"] and not is_current:
            end_val = normalize_date(target_entry.get("end_date"), "end")
            if end_val:
                loc = page.locator(f"input[name='{row['endName']}']").first
                ok = _fill_datepicker(page, loc, end_val)
                label = row["company"] or row["institution"]
                if ok:
                    print(f"        ↻ retry EndDate {label[:30]} = {end_val}")


def audit_dates(page: Page):
    """Reporta el estado real de cada datepicker.

    Detecta required directo y conditional (data-val-requiredif), evaluando la
    dependencia (e.g., EndDate es required si CurrentlyWorking está unchecked).
    """
    audit = page.evaluate(
        """() => {
            const out = [];
            const rows = document.querySelectorAll('.js_divExperience, .js_divAggregate');
            rows.forEach(row => {
                const job = (row.querySelector("input[name$='.Job']") || {}).value || '';
                const company = (row.querySelector("input[name$='.Company']") || {}).value || '';
                const institution = (row.querySelector("input[name$='.Center'], input[name$='.Institution']") || {}).value || '';
                const dates = row.querySelectorAll("input.js_beginDate, input.js_endDate");
                dates.forEach(el => {
                    const name = el.name || '';
                    const val = (el.value || '').trim();
                    let isRequired = el.hasAttribute('data-val-required');
                    // data-val-requiredif: required CONDICIONAL
                    if (!isRequired && el.hasAttribute('data-val-requiredif')) {
                        const depName = el.getAttribute('data-val-requiredif-dependent-element');
                        const condition = el.getAttribute('data-val-requiredif-condition');
                        // condition=1 (NotChecked) significa "required si dep checkbox NO está marcado"
                        if (depName) {
                            const depEl = row.querySelector(`[name$=".${depName}"], [id$="__${depName}"]`)
                                       || document.getElementById(depName);
                            if (depEl) {
                                if (depEl.type === 'checkbox') {
                                    if (condition === '1' && !depEl.checked) isRequired = true;
                                    if (condition === '0' && depEl.checked) isRequired = true;
                                } else {
                                    // dependencia no-checkbox: aplicamos required por defecto
                                    isRequired = true;
                                }
                            } else {
                                isRequired = true;
                            }
                        }
                    }
                    const pattern = el.getAttribute('data-val-regex-pattern') || '';
                    let regexOk = true;
                    if (val && pattern) {
                        try {
                            const re = new RegExp(pattern.replace(/\\\\x20/g, ' '));
                            regexOk = re.test(val);
                        } catch (e) { regexOk = true; }
                    }
                    const label = company || institution || job || 'unknown';
                    const field = name.includes('BeginDate') ? 'BeginDate' : 'EndDate';
                    const isEmpty = !val;
                    const reasons = [];
                    if (isRequired && isEmpty) reasons.push('vacío y requerido');
                    if (val && !regexOk) reasons.push('no matchea regex');
                    out.push({label, field, name, val, reasons});
                });
            });
            return out;
        }"""
    )
    bad = [a for a in audit if a["reasons"]]
    if bad:
        print(f"        ⚠ Auditoría: {len(bad)}/{len(audit)} fechas con problemas:")
        for a in bad:
            label = (a["label"] or "?")[:30]
            reasons = ", ".join(a["reasons"])
            print(f"          · {label:30s} ({a['field']}) val={a['val']!r:14s}  → {reasons}")
    else:
        print(f"        ✓ Auditoría: {len(audit)} fechas OK")


def fix_visible_errors(page: Page, profile: dict, log_ctx: dict = None):
    """Lee los errores actualmente visibles y trata de corregirlos:
      - Errores en BeginDate/EndDate de Experiences/Studies → re-fill desde profile.
      - Otros errores → quedan para que se ven en el reporte final.
    """
    # 1) Re-correr retry_empty_dates (matchea por nombre de empresa, no orden)
    try:
        retry_empty_dates(page, profile)
    except Exception as e:
        print(f"          ⚠ retry_empty_dates falló: {e}")

    # 2) Sobre la auditoría, identificar fechas todavía con problemas y forzar de nuevo
    try:
        audit = page.evaluate(
            """() => {
                const out = [];
                const rows = document.querySelectorAll('.js_divExperience, .js_divAggregate');
                rows.forEach(row => {
                    const company = (row.querySelector("input[name$='.Company']") || {}).value || '';
                    const institution = (row.querySelector("input[name$='.Center'], input[name$='.Institution']") || {}).value || '';
                    const begin = row.querySelector('input.js_beginDate');
                    const end = row.querySelector('input.js_endDate');
                    const currentlyWorking = row.querySelector('input.js_currentlyWorking');
                    out.push({
                        company: company.trim(),
                        institution: institution.trim(),
                        beginVal: begin ? begin.value : '',
                        beginName: begin ? begin.name : '',
                        endVal: end ? end.value : '',
                        endName: end ? end.name : '',
                        isCurrent: currentlyWorking ? !!currentlyWorking.checked : false,
                    });
                });
                return out;
            }"""
        )
    except Exception:
        return

    experiences = profile.get("experience", []) or []
    education = profile.get("education", []) or []

    for row in audit:
        target = None
        if row["company"]:
            for e in experiences:
                ec = (e.get("company") or "").lower()
                if ec and (ec in row["company"].lower() or row["company"].lower() in ec):
                    target = e
                    break
        if target is None and row["institution"]:
            for e in education:
                ei = (e.get("institution") or "").lower()
                if ei and (ei in row["institution"].lower() or row["institution"].lower() in ei):
                    target = e
                    break
        if target is None:
            continue

        is_current = bool(target.get("is_current")) or row.get("isCurrent")

        if not row["beginVal"].strip() and row["beginName"]:
            v = normalize_date(target.get("start_date"), "start")
            if v:
                _fill_datepicker(page, page.locator(f"input[name='{row['beginName']}']").first, v)
                label = row["company"] or row["institution"]
                print(f"          ↻ fix BeginDate {label[:30]} = {v}")

        if not row["endVal"].strip() and row["endName"] and not is_current:
            v = normalize_date(target.get("end_date"), "end")
            if v:
                _fill_datepicker(page, page.locator(f"input[name='{row['endName']}']").first, v)
                label = row["company"] or row["institution"]
                print(f"          ↻ fix EndDate {label[:30]} = {v}")
                if log_ctx is not None:
                    log_ctx.setdefault("notes", []).append(f"fix EndDate {label[:30]} = {v}")


def report_form_errors(page: Page, limit: int = 15):
    """Tras un submit fallido, escanea todo el form y reporta cada mensaje de
    error rojo visible. Sirve para diagnóstico."""
    errors = page.evaluate(
        """(limit) => {
            const out = [];
            // Spans de error con texto no vacío
            const spans = document.querySelectorAll(
                "span.field-validation-error, span[id$='-error']"
            );
            spans.forEach(s => {
                const txt = (s.textContent || '').trim();
                if (!txt) return;
                // Buscar el campo y label de contexto
                let field = '';
                let context = '';
                const valFor = s.getAttribute('data-valmsg-for');
                if (valFor) field = valFor;
                const group = s.closest('.form-group, .input-custom-message');
                if (group) {
                    const lbl = group.querySelector('label.form-label-inner, label');
                    if (lbl) context = (lbl.textContent || '').trim();
                }
                // Buscar la fila padre (experiencia / educación) para identificar empresa
                const row = s.closest('.js_divExperience, .js_divAggregate');
                let parentLabel = '';
                if (row) {
                    const c = row.querySelector("input[name$='.Company']");
                    const i = row.querySelector("input[name$='.Center'], input[name$='.Institution']");
                    parentLabel = (c && c.value) || (i && i.value) || '';
                }
                out.push({txt, field, context, parentLabel});
            });
            return out.slice(0, limit);
        }""",
        limit,
    )
    if not errors:
        print("        (sin mensajes de error visibles encontrados)")
        return
    print(f"        ⚠ {len(errors)} mensajes de error detectados:")
    for e in errors:
        parent = f" [{e['parentLabel'][:25]}]" if e["parentLabel"] else ""
        ctx = f" ({e['context'][:25]})" if e["context"] else ""
        print(f"          · {e['txt'][:80]}{ctx}{parent}")


def accept_terms(page: Page):
    for sel in TERMS_CHECKBOXES:
        _check(page, sel)


def try_submit(page: Page, profile: dict = None, log_ctx: dict = None) -> bool:
    submit = page.locator("#btnSendCV").first
    if submit.count() == 0:
        print("        ⚠ No encontré botón submit (#btnSendCV)")
        return manual_fallback()

    # Esperar a que se habilite (validaciones JS)
    for _ in range(20):
        try:
            disabled = submit.get_attribute("disabled")
            if disabled is None:
                break
        except Exception:
            break
        time.sleep(0.5)

    # Submit con loop de auto-corrección si fallan validaciones
    MAX_SUBMIT_ATTEMPTS = 3
    for attempt in range(1, MAX_SUBMIT_ATTEMPTS + 1):
        try:
            submit = page.locator("#btnSendCV").first
            submit.scroll_into_view_if_needed()
            submit.click()
            human_pause(3, 5)
        except Exception as e:
            print(f"        ⚠ No pude clickear submit (try {attempt}): {e}")
            if attempt == MAX_SUBMIT_ATTEMPTS:
                return manual_fallback()
            human_pause(1, 2)
            continue

        # Killer questions o éxito
        if handle_killer_questions(page, profile, log_ctx):
            if detect_success(page):
                _print_success(page, log_ctx)
                return True
        if detect_success(page):
            _print_success(page, log_ctx)
            return True

        # Sin éxito → escanear errores y reintentar correcciones
        if attempt < MAX_SUBMIT_ATTEMPTS:
            print(f"        ⚠ Submit {attempt} sin éxito. Escaneando errores y corrigiendo...")
            report_form_errors(page, limit=10)
            fix_visible_errors(page, profile, log_ctx)
            human_pause(1.5, 2.5)
        else:
            print(f"        ⚠ Submit falló tras {MAX_SUBMIT_ATTEMPTS} intentos. Errores finales:")
            report_form_errors(page)
            return manual_fallback()

    return manual_fallback()


def _print_success(page: Page, log_ctx: dict = None):
    print("        ✓ Postulación enviada (Pandapé)")
    if detect_pending_email_confirmation(page):
        print("        ⚠ Pandapé requiere confirmación por email — revisá tu bandeja")
        print("           (o SPAM) y hace click en el enlace para finalizar.")
        if log_ctx is not None:
            log_ctx["email_confirmation_required"] = True


def handle_killer_questions(page: Page, profile: dict, context: dict = None) -> bool:
    """Tras el submit del form principal, Pandapé puede mostrar killer questions
    (#DivKillerQuestions). Cada `.js_TestSection` es una pregunta:
      - texto en `.js_question`
      - respuesta va a `textarea.js_TxtAnwers`
      - se avanza con `.js_BtNextSection` (la última tiene data-islast="True")

    Las respuestas vienen de un LLM (OpenAI / Anthropic). Si no hay API key
    configurada, cae a input manual del usuario.
    """
    container = page.locator("#DivKillerQuestions")
    if container.count() == 0:
        return False

    visible = False
    for _ in range(10):
        try:
            visible = container.evaluate("el => !el.classList.contains('hidden')")
            if visible:
                break
        except Exception:
            pass
        time.sleep(0.5)
    if not visible:
        return False

    print("        → Killer questions detectadas")
    if profile is None:
        profile = {}

    max_iters = 25
    last_question = ""
    for step in range(max_iters):
        sec = page.locator(".js_TestSection:not(.hidden-important)").first
        if sec.count() == 0:
            break

        try:
            question = sec.locator(".js_question").first.inner_text(timeout=2000).strip()
        except Exception:
            break
        if not question or question == last_question:
            break
        last_question = question

        print(f"          Q: {question[:90]}")

        # Detectar tipo de pregunta: radio (multiple choice) vs textarea
        radio_inputs = sec.locator("input.js_CheckAnwers").all()
        is_choice = len(radio_inputs) > 0

        if is_choice:
            # Recopilar opciones (label text + radio id)
            options_data = []
            for r in radio_inputs:
                try:
                    rid = r.get_attribute("id") or ""
                    if not rid:
                        continue
                    label_el = sec.locator(f"label[for='{rid}']").first
                    label_text = (label_el.inner_text(timeout=500) or "").strip() if label_el.count() else ""
                    options_data.append({"id": rid, "label": label_text})
                except Exception:
                    continue
            option_labels = [o["label"] for o in options_data if o["label"]]
            print(f"          Opciones: {option_labels}")

            answer = llm.answer_question(question, profile, options=option_labels)
            source = "llm"
            chosen = _match_choice(answer or "", options_data)
            if chosen is None:
                print(f"          ⚠ LLM devolvió '{answer}' que no matchea ninguna opción.")
                print(f"             Opciones: {option_labels}")
                manual = input("          Elige por número o texto: ").strip()
                source = "manual"
                if manual.isdigit() and 1 <= int(manual) <= len(options_data):
                    chosen = options_data[int(manual) - 1]
                else:
                    chosen = _match_choice(manual, options_data)
                if chosen is None and options_data:
                    chosen = options_data[0]
            if chosen is None:
                print("          ⚠ no pude elegir opción, salto.")
                continue
            answer = chosen["label"]
            print(f"          A (radio): {answer[:90]}")

            try:
                # Selector por atributo: el id puede empezar con dígito y CSS
                # no acepta #digit como selector válido.
                page.locator(f'[id="{chosen["id"]}"]').check(force=True)
                human_pause(0.5, 1)
            except Exception as e:
                print(f"          ⚠ no pude clickear radio: {e}")
                continue
        else:
            answer = llm.answer_question(question, profile)
            source = "llm"
            if not answer:
                print("          ⚠ Sin LLM (configura OPENAI_API_KEY o ANTHROPIC_API_KEY en .env).")
                answer = input("          Tu respuesta: ").strip() or "Con gusto detallo en entrevista."
                source = "manual"
            else:
                print(f"          A: {answer[:90]}")

            try:
                ta = sec.locator(".js_TxtAnwers, textarea").first
                ta.evaluate(
                    """(el, v) => {
                        el.value = v;
                        el.dispatchEvent(new Event('input', {bubbles: true}));
                        el.dispatchEvent(new Event('change', {bubbles: true}));
                        el.dispatchEvent(new Event('keyup', {bubbles: true}));
                        if (window.jQuery) {
                            try { jQuery(el).trigger('input').trigger('change').trigger('keyup'); } catch(e) {}
                        }
                    }""",
                    answer,
                )
                human_pause(0.7, 1.3)
            except Exception as e:
                print(f"          ⚠ no pude llenar respuesta: {e}")
                continue

        if context is not None:
            entry = {"question": question, "answer": answer, "source": source}
            if is_choice:
                entry["options"] = option_labels
            context.setdefault("killer_questions", []).append(entry)

        btn = sec.locator(".js_BtNextSection").first
        is_last = False
        try:
            is_last = (btn.get_attribute("data-islast") == "True")
        except Exception:
            pass

        # Esperar a que se habilite (atributo `disabled` ausente == enabled)
        enabled = False
        for _ in range(30):
            try:
                if btn.get_attribute("disabled") is None:
                    enabled = True
                    break
            except Exception:
                break
            time.sleep(0.3)

        # Si sigue disabled, lo forzamos vía JS (último recurso)
        if not enabled:
            print("          ⚠ botón disabled tras 9s, forzando enable + click")
            try:
                btn.evaluate(
                    "el => { el.removeAttribute('disabled'); el.disabled = false; el.click(); }"
                )
                human_pause(2, 3.5)
            except Exception as e:
                print(f"          ⚠ force click falló: {e}")
                break
        else:
            try:
                btn.click()
                human_pause(2, 3.5)
            except Exception:
                # fallback JS click
                try:
                    btn.evaluate("el => el.click()")
                    human_pause(2, 3.5)
                except Exception as e:
                    print(f"          ⚠ no pude clickear avanzar: {e}")
                    break

        if is_last:
            print("        ✓ Killer questions completas")
            human_pause(2, 4)
            return True

    return True


def _match_choice(answer: str, options: list) -> dict:
    """Matchea la respuesta del LLM (string libre) contra las opciones de un
    radio button. Devuelve el dict de la opción matcheada o None.

    Estrategia:
      1. Match exacto case-insensitive.
      2. Match por substring bidireccional.
      3. Detectar números/letras de elección (a, b, c, 1, 2, 3).
    """
    if not answer or not options:
        return None
    a = (answer or "").strip().strip('"').strip("'").lower()
    if not a:
        return None
    # 1. Exacto
    for opt in options:
        if (opt.get("label") or "").strip().lower() == a:
            return opt
    # 2. Substring bidireccional
    for opt in options:
        ol = (opt.get("label") or "").strip().lower()
        if not ol:
            continue
        if ol in a or a in ol:
            return opt
    # 3. Letra/número
    if a in {"a", "1", "primera", "first"} and len(options) >= 1:
        return options[0]
    if a in {"b", "2", "segunda", "second"} and len(options) >= 2:
        return options[1]
    if a in {"c", "3", "tercera", "third"} and len(options) >= 3:
        return options[2]
    if a in {"d", "4", "cuarta", "fourth"} and len(options) >= 4:
        return options[3]
    return None


def manual_fallback() -> bool:
    r = input("        [s] terminé manualmente / [n] saltar: ").strip().lower()
    return r == "s"


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def detect_already_applied(page: Page) -> bool:
    indicators = [
        ":text('Ya te postulaste')",
        ":text('ya te has postulado')",
        ":text('Ya aplicaste')",
        # Pandapé pantalla de "email ya usado para esta oferta"
        ":text('ya ha sido utilizado para postularte')",
        ":text('Ya estás participando en el proceso')",
        ":text('El correo electrónico informado ya ha sido utilizado')",
    ]
    for sel in indicators:
        try:
            if page.locator(sel).count():
                return True
        except Exception:
            continue
    return False


def detect_success(page: Page) -> bool:
    indicators = [
        ":text('postulación enviada')",
        ":text('Postulación enviada')",
        ":text('Gracias por postular')",
        ":text('hemos recibido')",
        ":text('aplicación enviada')",
        ":text('te has postulado')",
        # Pandapé: pantalla "Finaliza tu candidatura..." con confirmación por email
        ":text('Finaliza tu candidatura')",
        ":text('Recibirás un correo electrónico para confirmar')",
        ":text('para confirmar tu candidatura')",
    ]
    for sel in indicators:
        try:
            if page.locator(sel).count():
                return True
        except Exception:
            continue
    return False


def detect_pending_email_confirmation(page: Page) -> bool:
    """Pandapé manda email de confirmación. La postulación está enviada pero
    requiere que el candidato haga click en el enlace del correo."""
    try:
        return page.locator(":text('Recibirás un correo electrónico para confirmar')").count() > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _force_fill(page: Page, selector: str, value: str):
    try:
        el = page.locator(selector).first
        if el.count() == 0:
            return
        try:
            el.fill(value)
            return
        except Exception as e1:
            try:
                el.evaluate(
                    "(el, v) => { el.value = v; "
                    "el.dispatchEvent(new Event('input', {bubbles:true})); "
                    "el.dispatchEvent(new Event('change', {bubbles:true})); }",
                    value,
                )
                return
            except Exception as e2:
                print(f"        ⚠ {selector}: fill={str(e1)[:60]}, js={str(e2)[:60]}")
    except Exception as e:
        print(f"        ⚠ {selector}: {str(e)[:80]}")


def _check(page: Page, selector: str):
    try:
        cb = page.locator(selector).first
        if cb.count() == 0:
            return
        if cb.is_checked():
            return
        cb.check(force=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# TODO Fase 2: secciones dinámicas
# ---------------------------------------------------------------------------
# Para llenar profile["experience"], profile["education"], profile["languages"],
# profile["skills"] necesitamos:
#   1. Click en "+ Incluir experiencia" (#lnkIncludeExperience)
#   2. Esperar el sub-form que aparece
#   3. Mapear sus inputs (no tenemos el HTML de ese sub-form todavía)
#   4. Click en "Guardar" del sub-form, repetir por cada entrada
#
# Cuando tengas el HTML del sub-form (después de click en Incluir), lo
# implementamos. Mientras tanto, esas secciones se cubren con el parseo del CV
# o requieren completar manual.
