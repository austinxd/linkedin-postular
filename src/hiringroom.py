"""Handler HiringRoom — recruiter SaaS LATAM (SPA).

HiringRoom carga el formulario con JavaScript. El HTML inicial solo tiene
`<div id="app"></div>` y los datos en window.__INITIAL_VACANCY +
window.__INITIAL_QUESTIONS. Hay que esperar el render del SPA antes de fillear.

Estrategia:
  1. Esperar que aparezca un input visible (indicador de que la SPA montó).
  2. Detectar si ya postulamos antes (mensaje específico).
  3. Llenar campos comunes: firstname, lastname, email, phone, address,
     locality, dni, born (fecha nacimiento).
  4. Subir CV.
  5. Responder preguntas custom (text/radio) usando LLM.
  6. Click en submit ("Postularme" / "Aplicar" / "Enviar").
"""
import time
import random
from pathlib import Path
from playwright.sync_api import Page, TimeoutError as PWTimeout

from . import autofill, llm, capsolver
from . import profile_helper as ph

ROOT = Path(__file__).parent.parent


def human_pause(a=1.5, b=3.5):
    time.sleep(random.uniform(a, b))


def apply_on_page(page: Page, profile: dict, log_ctx: dict = None) -> bool:
    """Postula en una página HiringRoom (SPA). Devuelve True si se aplicó."""
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except PWTimeout:
        pass

    # Esperar que la SPA monte el formulario (10s máx)
    if not _wait_for_spa(page):
        print("        ⚠ SPA no terminó de cargar a tiempo. Probando igual.")

    if _detect_already_applied(page):
        print("        → Ya postulado anteriormente (HiringRoom)")
        if log_ctx is not None:
            log_ctx.setdefault("notes", []).append("Ya postulado (detectado al cargar)")
        return True

    # Login wall
    if _detect_login_wall(page):
        print("        → HiringRoom pide login.")
        input("          Logueate manualmente y presioná ENTER... ")
        human_pause(1, 2)

    # Si el form todavía no apareció, puede que haya un botón "Postularme"
    # o una landing previa que activa el formulario.
    _open_apply_form(page)

    # Seleccionar modo "Currículum manual" si existe esa opción.
    # Si lo logramos, NO subimos CV (por eso es "manual").
    manual_mode = _switch_to_manual_curriculum(page)
    human_pause(0.8, 1.5)

    # Dump APENAS abre el form (antes de tocar nada) — para inspeccionar
    # estructura inicial de inputs y selectores.
    initial_path = _dump_html(page, label="form-initial")
    print(f"        → HTML inicial del form: {initial_path}")

    flat = ph.flatten(profile) if "personal" in profile else profile

    # === STEP 1: Datos personales + radios (answers.4 etc) ===
    _fill_common_fields(page, flat)
    human_pause(0.5, 1.2)
    if manual_mode:
        print("        → Modo manual activo: omitimos upload de CV")
    else:
        _upload_cv(page, flat)
        human_pause(0.5, 1.2)

    # Responder preguntas tipo radio (las que existen en step 1)
    _answer_radio_questions(page, profile, log_ctx)
    human_pause(0.3, 0.6)

    after_fill_path = _dump_html(page, label="after-fill-step1")
    print(f"        → HTML post-fill step1: {after_fill_path}")

    # _try_submit avanza pasos y entre clicks llena lo que aparezca nuevo
    return _try_submit(page, profile, log_ctx)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _wait_for_spa(page: Page, timeout: float = 10.0) -> bool:
    """Espera a que el SPA renderice algo dentro de #app o aparezca un input
    interactivo."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            visible_inputs = page.locator(
                "input[type='text']:visible, input[type='email']:visible, "
                "input[type='tel']:visible, textarea:visible"
            ).count()
            if visible_inputs > 0:
                return True
            app_content = page.locator("#app").evaluate("el => el ? el.children.length : 0")
            if app_content and app_content > 1:
                # SPA montó algo; esperar un poco más a que termine
                time.sleep(0.8)
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def _detect_already_applied(page: Page) -> bool:
    """Detecta si la postulación ya fue enviada antes (mismo email). Usa el
    HTML completo (no body.innerText) porque HiringRoom muestra el mensaje
    en un modal/portal que innerText no captura."""
    keywords = [
        "ya te postulaste", "ya te has postulado", "ya postulaste",
        "ya aplicaste", "ya te postulaste a esta",
        "ya existe una postulación", "ya existe una postulacion",
        "ya existe una postulacion realizada",  # texto exacto de HiringRoom
        "ya tienes una postulación", "ya tienes una postulacion",
        "postulación duplicada", "postulacion duplicada",
        "ya se postuló", "ya se postulo",
        "este email ya tiene una postulación",
        "ya se ha registrado una postulación",
        "mismos datos para esta vacante",  # frase específica del modal HR
    ]
    try:
        html = page.content().lower()
        for kw in keywords:
            if kw in html:
                return True
    except Exception:
        pass
    return False


def _open_apply_form(page: Page) -> bool:
    """En HiringRoom el detalle de la vacante tiene un botón 'Postularse'
    que navega a /candidates/new (otra URL) donde está el form real."""
    # Decidir por URL — si ya estamos en la URL del formulario, no hacer nada.
    # Los modales ocultos (#frm-support, #form_login) tienen inputs que pasan
    # como `:visible` para Playwright en algunos casos, así que la URL es más fiable.
    url = (page.url or "").lower()
    if "/candidates/new" in url or "/apply" in url:
        return False

    selectors = [
        "a.hero__btn:has-text('Postular')",
        "a.main__button:has-text('Postular')",
        "a:has-text('Postularse'):visible",
        "a:has-text('Postularme'):visible",
        "a:has-text('Postular'):visible",
        "a:has-text('Aplicar a esta oferta'):visible",
        "a:has-text('Aplicar ahora'):visible",
        "button:has-text('Postularse'):visible",
        "button:has-text('Postularme'):visible",
        "button:has-text('Postular'):visible",
        "button:has-text('Aplicar'):visible",
    ]
    old_url = page.url
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.count() == 0:
                continue
            try:
                if not el.is_visible():
                    continue
            except Exception:
                continue
            el.click(force=True)
            print("        → Click inicial en 'Postularse'")
            human_pause(0.8, 1.5)

            # Esperar a que la URL cambie (HiringRoom navega a /candidates/new)
            try:
                page.wait_for_url(lambda u: u != old_url, timeout=10000)
            except Exception:
                pass
            try:
                page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            # Esperar que el SPA del formulario monte
            _wait_for_spa(page, timeout=10.0)
            human_pause(0.5, 1)
            return True
        except Exception:
            continue
    return False


def _switch_to_manual_curriculum(page: Page) -> bool:
    """Si HiringRoom ofrece 'Currículum manual' (vs subir CV), lo seleccionamos
    para que aparezcan los campos de llenado manual.

    Estrategia: escaneo JS de TODOS los elementos clickeables cuyo texto
    contenga variantes de "manual" / "llenar" / "sin cv". HiringRoom renderiza
    estos toggles con clases custom que cambian, por eso text-search es lo
    más robusto.
    """
    try:
        result = page.evaluate(
            r"""() => {
                const norm = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
                const KEYWORDS = [
                    'currículum manual', 'curriculum manual',
                    'llenar manualmente', 'completar manualmente',
                    'cargar manualmente', 'cargar mi cv manualmente',
                    'postular manualmente', 'postular sin cv',
                    'sin currículum', 'sin curriculum',
                    'llenar el formulario', 'completar formulario',
                    'manual', 'rellenar manualmente',
                ];
                const tags = ['button', 'a', 'label', 'span', 'div', 'li', '[role=tab]', '[role=button]'];
                const all = Array.from(document.querySelectorAll(tags.join(',')));
                const candidates = [];
                for (const el of all) {
                    const t = norm(el.innerText || el.textContent);
                    if (!t || t.length > 80) continue;
                    for (const kw of KEYWORDS) {
                        if (t === kw || t.includes(kw)) {
                            candidates.push({ el, text: t, kw, len: t.length });
                            break;
                        }
                    }
                }
                // Preferir matches más cortos (menos ruido) y los que tienen
                // keyword más específica (orden = prioridad)
                candidates.sort((a, b) => {
                    const ai = KEYWORDS.indexOf(a.kw);
                    const bi = KEYWORDS.indexOf(b.kw);
                    if (ai !== bi) return ai - bi;
                    return a.len - b.len;
                });
                for (const c of candidates) {
                    const r = c.el.getBoundingClientRect();
                    if (r.width < 1 || r.height < 1) continue;
                    try {
                        c.el.scrollIntoView({ block: 'center' });
                        c.el.click();
                        return { ok: true, text: c.text, tag: c.el.tagName };
                    } catch (e) {}
                }
                // Fallback: input[type=radio][value*=manual]
                const radios = document.querySelectorAll(
                    "input[type='radio'][value*='manual' i], input[type='radio'][id*='manual' i]"
                );
                for (const r of radios) {
                    try {
                        r.checked = true;
                        r.dispatchEvent(new Event('input', {bubbles:true}));
                        r.dispatchEvent(new Event('change', {bubbles:true}));
                        const lbl = document.querySelector(`label[for='${r.id}']`);
                        if (lbl) lbl.click();
                        return { ok: true, text: 'radio[manual]', tag: 'INPUT' };
                    } catch (e) {}
                }
                return { ok: false };
            }"""
        )
    except Exception as e:
        print(f"        ⚠ JS switch manual: {str(e)[:60]}")
        return False

    if result and result.get("ok"):
        print(f"        → Modo manual seleccionado: '{result.get('text', '')[:50]}'")
        human_pause(1.5, 2.5)
        return True
    return False


def _detect_login_wall(page: Page) -> bool:
    try:
        url = (page.url or "").lower()
        if "login" in url or "ingresar" in url or "signin" in url:
            return True
        if page.locator("input[type='password']:visible").count() > 0:
            # Solo es wall si el password está acompañado de email visible y NO
            # hay otros campos de postulación visibles
            other = page.locator("input[name*='firstname'], input[name*='Name']").count()
            return other == 0
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Fill
# ---------------------------------------------------------------------------

# selector → key en flat profile (text inputs simples)
# Phone: el id="phone" duplicado tiene un readonly type=tel con +51 y un
# type=number para el local. Usamos `phone_local` (sin código país) para el
# number, sino el form combina "+51" + "+51999..." = "51999...".
COMMON_FIELDS = [
    ("input[name='firstname'], input[name='first_name'], input#firstname", "first_name"),
    ("input[name='lastname'], input[name='last_name'], input#lastname", "last_name"),
    ("input[name='email']:not([name='emailConfirm']), input#email", "email"),
    ("input[name='emailConfirm'], input#emailConfirm", "email"),
    ("input[type='number'][name='phone']", "phone_local"),
    ("input[name='dni'], input#dni", "dni"),
    ("input[name='url_linkedin'], input#url_linkedin", "linkedin_url"),
    ("input[name='address'], input[name='direccion']", "address_street"),
]


def _react_fill_text(page: Page, selector: str, value: str) -> bool:
    """Llena un input/textarea usando el setter nativo de React.
    React-controlled inputs ignoran value=... directo; el setter nativo + input
    event hace que React detecte el cambio y commitee al state.
    No filtra por visibilidad (los inputs HiringRoom a veces reportan w/h=0)."""
    if not value:
        return False
    try:
        ok = page.evaluate(
            r"""([sel, val]) => {
                const candidates = Array.from(document.querySelectorAll(sel));
                for (const el of candidates) {
                    if (el.readOnly || el.disabled) continue;
                    if ((el.value || '').trim()) continue;
                    el.focus();
                    const proto = el.tagName === 'TEXTAREA'
                        ? window.HTMLTextAreaElement.prototype
                        : window.HTMLInputElement.prototype;
                    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
                    setter.call(el, val);
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.blur();
                    return true;
                }
                return false;
            }""",
            [selector, str(value)],
        )
        return bool(ok)
    except Exception:
        return False


def _react_check(page: Page, selector: str, want_checked: bool = True) -> bool:
    """Marca un checkbox/radio usando setter nativo + click event."""
    try:
        ok = page.evaluate(
            r"""([sel, want]) => {
                const el = document.querySelector(sel);
                if (!el) return false;
                if (el.disabled) return false;
                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'checked').set;
                setter.call(el, want);
                el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
                el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true }));
                el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                if (el.id) {
                    const lbl = document.querySelector(`label[for="${el.id}"]`);
                    if (lbl) lbl.click();
                }
                return true;
            }""",
            [selector, bool(want_checked)],
        )
        return bool(ok)
    except Exception:
        return False


def _fill_common_fields(page: Page, flat: dict):
    """Llena text inputs + custom React-Select widgets + checkboxes de términos."""
    filled = []
    # 1) Text inputs (vía native React setter)
    for selector, key in COMMON_FIELDS:
        val = flat.get(key)
        if not val:
            continue
        if _react_fill_text(page, selector, val):
            filled.append(key)

    # 2) Custom React-Select dropdowns (HiringRoom usa .custom-hr-select__*).
    # Cada entrada es (field_id, [variantes a probar en orden]).
    select_targets = [
        ("type_doc", _doc_type_variants(flat.get("document_type"))),
        ("type_phone_1", ["Móvil", "Celular", "Mobile"]),
        ("gender", _gender_variants(flat.get("gender"))),
        ("nationality", _nationality_variants(flat.get("nationality"))),
        ("location.country", _country_variants(flat.get("country") or flat.get("address_country"))),
    ]
    for fid, variants in select_targets:
        if not variants:
            continue
        for target in variants:
            if _fill_react_select(page, fid, target):
                filled.append(f"select#{fid}")
                break

    # 2b) Province / City (cascading, dependen del país — esperar a que se habiliten)
    province = flat.get("state") or flat.get("address_state") or "Lima"
    city = flat.get("city") or flat.get("address_city") or "Lima"
    # Esperar a que el cascading se habilite tras seleccionar país
    time.sleep(1.2)
    for variant in [province, "Lima"]:
        if _fill_react_select(page, "location.province", variant):
            filled.append("select#location.province")
            break
    time.sleep(1.2)
    for variant in [city, "Lima", "San Isidro"]:
        if _fill_react_select(page, "location.city", variant):
            filled.append("select#location.city")
            break

    # 3) Birth date (3 selects: bornObj.day, bornObj.month, bornObj.year)
    if _fill_birth_date_react(page, flat.get("birth_date")):
        filled.append("bornObj")

    # 4) Radio high_school_data → "si" (tiene universidad/MBA)
    if _react_check(page, "input[type='radio'][name='high_school_data'][value='si']"):
        filled.append("high_school_data")

    # 5) Términos hiringroom (obligatorio)
    if _react_check(page, "input[type='checkbox'][name='termsConditions.hiring']"):
        filled.append("termsConditions.hiring")

    if filled:
        print(f"        → Campos llenados: {len(filled)}")


def _gender_variants(g: str) -> list:
    if not g:
        return []
    g = g.lower()
    if g in ("male", "m", "masculino", "hombre"):
        return ["Masculino", "Hombre", "Male"]
    if g in ("female", "f", "femenino", "mujer"):
        return ["Femenino", "Mujer", "Female"]
    return [g.title()]


def _nationality_variants(n: str) -> list:
    if not n:
        return ["Peruana", "Peruano", "Peru"]
    n = n.lower()
    if "peru" in n:
        return ["Peruana", "Peruano", "Peruano(a)", "Peru", "Peruvian"]
    return [n.title()]


def _country_variants(c: str) -> list:
    if not c:
        return ["Peru", "Perú"]
    c = c.lower()
    if "peru" in c:
        return ["Peru", "Perú"]
    return [c.title()]


def _doc_type_variants(d: str) -> list:
    """HiringRoom usa labels largos: 'Documento de identidad', no 'DNI'."""
    if not d:
        return ["Documento de identidad", "DNI"]
    d = d.lower()
    if d in ("dni", "documento", "documento de identidad"):
        return ["Documento de identidad", "DNI"]
    if "pasaporte" in d or "passport" in d:
        return ["Pasaporte"]
    if "extranj" in d or "ce" == d:
        return ["Cédula extranjera", "Cedula extranjera"]
    return [d.title(), "Documento de identidad"]


def _fill_react_select(page: Page, field_id: str, target_text: str) -> bool:
    """Llena un widget React-Select de HiringRoom.

    Pasos:
      1. Buscar el input con id=field_id, subir al `.custom-hr-select__control`.
      2. Si está disabled, retornar False.
      3. Click en el control → abre el menú.
      4. Si el input es typeable (no readonly), tipear el target para filtrar.
      5. Buscar `.custom-hr-select__option` que matchee y clickear.
    """
    if not target_text:
        return False
    # Cerrar cualquier menú abierto de un select previo + LIMPIAR search input
    # (react-select v3 deja "Masculino" en el search cuando cerrás con Escape;
    # eso hace que el siguiente intento abra el menú con filtro stale → 0 opts).
    try:
        page.keyboard.press("Escape")
        time.sleep(0.15)
        # Limpiar cualquier search input residual de los selects via setter nativo
        page.evaluate(
            r"""() => {
                document.querySelectorAll('.custom-hr-select__input input').forEach(inp => {
                    if (!inp.value) return;
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    setter.call(inp, '');
                    inp.dispatchEvent(new Event('input', { bubbles: true }));
                });
            }"""
        )
        time.sleep(0.2)
    except Exception:
        pass
    try:
        # 1. Localizar control + chequear disabled/readonly + cerrar menús stale
        meta = page.evaluate(
            r"""(fid) => {
                document.querySelectorAll('[data-nr-rs]').forEach(e => e.removeAttribute('data-nr-rs'));
                const inp = document.querySelector(`[id="${fid}"]`);
                if (!inp) return { ok: false, reason: 'input-not-found' };
                const ctrl = inp.closest('.custom-hr-select__control');
                if (!ctrl) return { ok: false, reason: 'control-not-found' };
                if (ctrl.classList.contains('custom-hr-select__control--is-disabled')) {
                    return { ok: false, reason: 'disabled' };
                }
                ctrl.setAttribute('data-nr-rs', '1');
                return { ok: true, readonly: !!inp.readOnly, dummy: inp.classList.contains('css-62g3xt-dummyInput') };
            }""",
            field_id,
        )
        if not meta or not meta.get("ok"):
            reason = (meta or {}).get("reason", "unknown")
            if reason != "disabled":
                print(f"        ⚠ react-select #{field_id}: {reason}")
            return False

        ctrl = page.locator("[data-nr-rs='1']").first
        try:
            ctrl.scroll_into_view_if_needed()
        except Exception:
            pass
        ctrl.click()
        time.sleep(1.0)  # esperar a que el menú renderice todas las opciones

        # DEBUG: capturar todas las opciones visibles en este momento, para
        # diagnosticar matching issues incluso si terminamos commiteando.
        all_opts = page.evaluate(
            r"""() => Array.from(document.querySelectorAll('.custom-hr-select__option'))
                  .map(o => (o.innerText || o.textContent || '').trim())"""
        )
        if not all_opts:
            print(f"        ⓘ react-select #{field_id}: menú abrió con 0 opciones")
        else:
            print(f"        ⓘ react-select #{field_id}: opciones visibles = {all_opts[:10]}")

        # 2. Buscar la opción + marcarla; clickeamos con Playwright (no JS dispatch)
        # porque React-Select v3 sólo commitea con mousedown REAL del navegador.
        mark_js = r"""(target) => {
            document.querySelectorAll('[data-nr-opt]').forEach(e => e.removeAttribute('data-nr-opt'));
            const stripAccents = s => (s||'').normalize('NFD').replace(/[̀-ͯ]/g, '');
            const norm = (s) => stripAccents(s).replace(/\s+/g, ' ').trim().toLowerCase();
            const t = norm(target);
            const opts = Array.from(document.querySelectorAll('.custom-hr-select__option'));
            if (!opts.length) return { found: false, reason: 'no-options', count: 0 };
            let exact = null, contains = null;
            for (const o of opts) {
                const ot = norm(o.innerText || o.textContent);
                if (ot === t) { exact = o; break; }
                if (!contains && (ot.includes(t) || (t.length > 2 && t.includes(ot)))) contains = o;
            }
            const best = exact || contains;
            if (best) {
                best.setAttribute('data-nr-opt', '1');
                return { found: true, text: best.innerText, count: opts.length };
            }
            return { found: false, reason: 'no-match', count: opts.length, sample: opts.slice(0,8).map(o=>o.innerText) };
        }"""

        # Primer intento: sin tipear (lista completa)
        result = page.evaluate(mark_js, target_text)

        # Si no matcheó y el input es searchable, tipear prefijo y reintentar
        if (not result or not result.get("found")) and not meta.get("readonly") and not meta.get("dummy"):
            prefix = target_text[:3] if len(target_text) >= 3 else target_text
            try:
                page.keyboard.type(prefix, delay=40)
                time.sleep(0.8)
            except Exception:
                pass
            result = page.evaluate(mark_js, target_text)

        # Si encontramos la opción, clickeamos con Playwright real
        clicked = {"clicked": False}
        if result and result.get("found"):
            try:
                opt = page.locator("[data-nr-opt='1']").first
                opt.scroll_into_view_if_needed()
                opt.click()
                clicked = {"clicked": True, "text": result.get("text"), "count": result.get("count")}
            except Exception as e:
                clicked = {"clicked": False, "reason": f"click-failed: {str(e)[:40]}"}
        else:
            clicked = result if result else {"clicked": False, "reason": "unknown"}

        # Fallback: si todavía no commiteó, usar typing + Enter (método más
        # confiable en react-select v3 — selecciona la opción highlighteada).
        if not meta.get("readonly") and not meta.get("dummy"):
            committed_quick = page.evaluate(
                r"""(fid) => {
                    const inp = document.querySelector(`[id="${fid}"]`);
                    const c = inp?.closest('.custom-hr-select-container');
                    const sv = c?.querySelector('.custom-hr-select__single-value');
                    return !!(sv && (sv.innerText || '').trim().length > 0);
                }""",
                field_id,
            )
            if not committed_quick:
                # Reabrir menú: Escape, click ctrl
                try:
                    page.keyboard.press("Escape")
                    time.sleep(0.2)
                    ctrl_again = page.evaluate(
                        r"""(fid) => {
                            document.querySelectorAll('[data-nr-rs]').forEach(e => e.removeAttribute('data-nr-rs'));
                            const inp = document.querySelector(`[id="${fid}"]`);
                            const ctrl = inp?.closest('.custom-hr-select__control');
                            if (!ctrl) return false;
                            ctrl.setAttribute('data-nr-rs', '1');
                            return true;
                        }""",
                        field_id,
                    )
                    if ctrl_again:
                        page.locator("[data-nr-rs='1']").first.click()
                        time.sleep(0.4)
                        # Type the full target — react-select highlights matching, Enter selects
                        page.keyboard.type(target_text, delay=50)
                        time.sleep(0.6)
                        page.keyboard.press("Enter")
                        time.sleep(0.5)
                        clicked = {"clicked": True, "text": target_text, "method": "type+Enter"}
                except Exception as e:
                    print(f"        ⚠ react-select #{field_id} fallback type+Enter: {str(e)[:60]}")

        # Cleanup marca
        try:
            page.evaluate(r"() => document.querySelectorAll('[data-nr-opt]').forEach(e => e.removeAttribute('data-nr-opt'))")
        except Exception:
            pass
        time.sleep(0.4)
        ok = bool(clicked and clicked.get("clicked"))

        # Verificación post-click: el container debe mostrar `single-value`
        if ok:
            committed = page.evaluate(
                r"""(fid) => {
                    const inp = document.querySelector(`[id="${fid}"]`);
                    if (!inp) return false;
                    const container = inp.closest('.custom-hr-select-container');
                    if (!container) return false;
                    const sv = container.querySelector('.custom-hr-select__single-value');
                    return !!(sv && (sv.innerText || '').trim().length > 0);
                }""",
                field_id,
            )
            if not committed:
                print(f"        ⚠ react-select #{field_id}: click ok pero valor no commiteó, retry")
                ok = False

        # Cleanup marca
        try:
            page.evaluate(r"() => document.querySelectorAll('[data-nr-rs]').forEach(e => e.removeAttribute('data-nr-rs'))")
        except Exception:
            pass

        if not ok:
            print(f"        ⚠ react-select #{field_id}: target='{target_text}' falló. Detalle: {clicked}")
            try:
                page.keyboard.press("Escape")
                time.sleep(0.2)
            except Exception:
                pass
        return ok
    except Exception as e:
        print(f"        ⚠ react-select #{field_id}: {str(e)[:60]}")
        return False


SPANISH_MONTHS = {
    "01": "Enero", "02": "Febrero", "03": "Marzo", "04": "Abril",
    "05": "Mayo", "06": "Junio", "07": "Julio", "08": "Agosto",
    "09": "Septiembre", "10": "Octubre", "11": "Noviembre", "12": "Diciembre",
}


def _fill_birth_date_react(page: Page, birth_date: str) -> bool:
    """birth_date en DD/MM/YYYY; HiringRoom tiene 3 selects: bornObj.day, .month, .year"""
    if not birth_date or "/" not in birth_date:
        return False
    parts = birth_date.split("/")
    if len(parts) != 3:
        return False
    day, month, year = parts
    day_label = str(int(day))  # sin ceros: "4" no "04"
    month_label = SPANISH_MONTHS.get(month.zfill(2), "")
    year_label = year
    ok_d = _fill_react_select(page, "bornObj.day", day_label)
    ok_m = _fill_react_select(page, "bornObj.month", month_label) if month_label else False
    ok_y = _fill_react_select(page, "bornObj.year", year_label)
    return ok_d and ok_m and ok_y


def _upload_cv(page: Page, flat: dict):
    cv_path = ROOT / (flat.get("cv_path") or "cv/alex.pdf")
    if not cv_path.exists():
        print(f"        ⚠ CV no encontrado en {cv_path}")
        return
    try:
        inputs = page.locator("input[type='file']").all()
        for inp in inputs:
            try:
                inp.set_input_files(str(cv_path))
                print(f"        → CV subido: {cv_path.name}")
                human_pause(1, 2)
                return
            except Exception:
                continue
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Custom questions (HiringRoom: window.__INITIAL_QUESTIONS)
# ---------------------------------------------------------------------------

def _get_questions(page: Page) -> list:
    try:
        return page.evaluate("() => window.__INITIAL_QUESTIONS || []") or []
    except Exception:
        return []


def _answer_radio_questions(page: Page, profile: dict, log_ctx: dict = None):
    """Sólo las preguntas con opciones (radios). Aparecen en step 1.
    name=answers.{idx}.answer en el DOM."""
    questions = _get_questions(page)
    if not questions:
        return
    for idx, q in enumerate(questions):
        if not q.get("have_options"):
            continue
        text = (q.get("text") or "").strip()
        options = q.get("options") or []
        print(f"          Q-radio[{idx}]: {text[:80]}")
        answer = llm.answer_question(text, profile, options=options)
        source = "llm"
        if not answer:
            answer = options[0] if options else "Si"
            source = "default"
        print(f"          A: {answer[:80]}")
        ok = _set_question_answer(page, idx, answer, is_choice=True, options=options)
        if not ok:
            print(f"          ⚠ radio idx={idx} no se pudo marcar")
        if log_ctx is not None:
            log_ctx.setdefault("killer_questions", []).append({
                "question": text, "answer": answer, "source": source,
                "options": options, "type": "radio",
            })


def _answer_textarea_questions(page: Page, profile: dict, log_ctx: dict = None) -> int:
    """Preguntas de texto libre. Aparecen en step 2 ('Información adicional').
    Las textareas NO tienen name/id — se identifican por orden + placeholder."""
    questions = _get_questions(page)
    text_questions = [(i, q) for i, q in enumerate(questions) if not q.get("have_options")]
    if not text_questions:
        return 0
    # Buscar textareas en el DOM
    try:
        ta_count = page.evaluate(
            r"""() => document.querySelectorAll('textarea[placeholder*="respuesta" i]').length"""
        )
    except Exception:
        ta_count = 0
    if ta_count == 0:
        return 0
    print(f"        → {len(text_questions)} pregunta(s) de texto, {ta_count} textarea(s) detectada(s)")
    filled = 0
    for n, (idx, q) in enumerate(text_questions):
        text = (q.get("text") or "").strip()
        print(f"          Q-text[{idx}]: {text[:80]}")
        # Buscar respuesta ya generada (idempotente)
        existing = None
        if log_ctx is not None:
            for kq in log_ctx.get("killer_questions", []):
                if kq.get("question") == text and kq.get("type") == "text":
                    existing = kq.get("answer")
                    break
        answer = existing or llm.answer_question(text, profile)
        source = "llm" if not existing else "cached"
        if not answer:
            answer = input("          Respuesta manual: ").strip() or "Con gusto detallo en entrevista."
            source = "manual"
        print(f"          A: {answer[:80]}")
        ok = _fill_textarea_by_position(page, n, answer)
        if ok:
            filled += 1
        else:
            print(f"          ⚠ textarea pos={n} no se pudo llenar")
        if log_ctx is not None and not existing:
            log_ctx.setdefault("killer_questions", []).append({
                "question": text, "answer": answer, "source": source, "type": "text",
            })
    return filled


def _fill_textarea_by_position(page: Page, position: int, value: str) -> bool:
    """Encuentra la N-ésima textarea con placeholder de respuesta y la llena
    via setter nativo (React-controlled)."""
    if not value:
        return False
    try:
        ok = page.evaluate(
            r"""([pos, val]) => {
                const tas = Array.from(document.querySelectorAll('textarea[placeholder*="respuesta" i]'));
                if (pos >= tas.length) return false;
                const ta = tas[pos];
                ta.focus();
                const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
                setter.call(ta, val);
                ta.dispatchEvent(new Event('input', { bubbles: true }));
                ta.dispatchEvent(new Event('change', { bubbles: true }));
                ta.blur();
                return true;
            }""",
            [position, str(value)],
        )
        return bool(ok)
    except Exception:
        return False


def _set_question_answer(page: Page, index: int, answer: str, is_choice: bool, options: list) -> bool:
    """Llena la respuesta usando el ÍNDICE de la pregunta.

    HiringRoom genera inputs con name `answers.{i}.answer`. El índice viene
    del orden en `window.__INITIAL_QUESTIONS`, que coincide con el orden en
    el DOM. Esto es 100% determinístico (no depende de match de texto).
    """
    try:
        result = page.evaluate(
            r"""([idx, ans, isChoice]) => {
                const norm = (s) => (s||'').replace(/\s+/g, ' ').trim().toLowerCase();
                const ansN = norm(ans);
                const name = `answers.${idx}.answer`;

                if (isChoice) {
                    const radios = Array.from(document.querySelectorAll(`input[type=radio][name="${name}"]`));
                    if (!radios.length) return { ok: false, reason: 'no-radios', name };
                    let best = null;
                    for (const r of radios) {
                        const v = norm(r.value);
                        if (v === ansN || v.includes(ansN) || ansN.includes(v)) { best = r; break; }
                    }
                    if (!best) best = radios[0];
                    // Para inputs controlados de React, usar setter nativo + click + change
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'checked').set;
                    setter.call(best, true);
                    // Click real (con MouseEvent para que React lo capte)
                    best.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true}));
                    best.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, cancelable:true}));
                    best.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true}));
                    best.dispatchEvent(new Event('input', {bubbles:true}));
                    best.dispatchEvent(new Event('change', {bubbles:true}));
                    // También intentar click en el label asociado
                    const lbl = best.id ? document.querySelector(`label[for="${best.id}"]`) : null;
                    if (lbl) lbl.click();
                    return { ok: true, type: 'radio', value: best.value, name };
                }

                // Text/textarea: para inputs controlados de React, usar
                // nativeInputValueSetter para que React detecte el cambio.
                const ta = document.querySelector(`textarea[name="${name}"]`);
                const inp = document.querySelector(`input[name="${name}"]`);
                const target = ta || inp;
                if (!target) return { ok: false, reason: 'no-input', name };

                target.focus();
                const proto = target.tagName === 'TEXTAREA'
                    ? window.HTMLTextAreaElement.prototype
                    : window.HTMLInputElement.prototype;
                const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
                setter.call(target, ans);
                target.dispatchEvent(new Event('input', { bubbles: true }));
                target.dispatchEvent(new Event('change', { bubbles: true }));
                target.blur();
                return { ok: true, type: target.tagName.toLowerCase(), name };
            }""",
            [index, answer, is_choice],
        )
        return bool(result and result.get("ok"))
    except Exception as e:
        print(f"          ⚠ JS set answer: {str(e)[:60]}")
        return False


# ---------------------------------------------------------------------------
# Terms / submit
# ---------------------------------------------------------------------------

def _accept_terms(page: Page):
    sels = [
        "input[type='checkbox'][name*='term']",
        "input[type='checkbox'][name*='priv']",
        "input[type='checkbox'][name*='accept']",
        "input[type='checkbox'][name*='politica']",
    ]
    for sel in sels:
        try:
            for cb in page.locator(sel).all():
                try:
                    if cb.is_visible() and not cb.is_checked():
                        cb.check(force=True)
                except Exception:
                    continue
        except Exception:
            continue


def _try_submit(page: Page, profile: dict = None, log_ctx: dict = None) -> bool:
    """HiringRoom es multi-tab (CV / Datos Personales / Información adicional).
    Clickea 'Continuar' hasta llegar a 'Enviar postulación'. Entre pasos llena
    textareas que aparezcan y resuelve captcha (visible o invisible)."""
    # Pre-cargar token de Capsolver para Turnstile invisible.
    # Si la página llama turnstile.execute(), nuestro hijack lo usa al toque.
    _preload_turnstile_token(page)

    max_steps = 5
    for step in range(1, max_steps + 1):
        print(f"        ▶ Step {step}/{max_steps}: chequeo de form...")
        # Log eventos Turnstile capturados (diagnóstico)
        try:
            events = page.evaluate("() => window.__nrTurnstileEvents || []")
            if events:
                print(f"        ⓘ Turnstile events ({len(events)}): {events[-5:]}")
        except Exception:
            pass
        # 0. Llenar textareas que hayan aparecido (típicamente paso 2 → 3)
        if profile is not None:
            try:
                _answer_textarea_questions(page, profile, log_ctx)
            except Exception as e:
                print(f"        ⚠ fill textareas error: {str(e)[:60]}")

        # 1. Captcha Cloudflare Turnstile
        if _has_turnstile(page):
            print("        ⚠ Cloudflare Turnstile detectado. Esperando 5s auto-resolve...")
            if _wait_for_turnstile_solved(page, timeout=5):
                print("          ✓ Captcha resuelto automáticamente.")
            else:
                # Auto-resolve falló (Cloudflare detectó CDP). Intentamos Capsolver.
                solved = _solve_turnstile_via_capsolver(page)
                if not solved:
                    # Capsolver falló (sin API key, sin balance, o error)
                    action = _captcha_unsolvable_dialog(page.url)
                    if log_ctx is not None:
                        log_ctx.setdefault("notes", []).append(
                            "manual_pending: Turnstile bloqueó automation"
                        )
                    if action == "skip":
                        return False
            human_pause(0.5, 1)

        # 2. Buscar botón de acción primario
        chosen = _find_primary_action(page)
        if chosen is None:
            html_path = _dump_html(page, label=f"step{step}-no-button")
            print(f"        ⚠ no encontré botón de acción (step {step}).")
            print(f"          HTML dumpeado a: {html_path}")
            return _manual_fallback()

        # 3. Click
        try:
            chosen_text = (chosen.inner_text() or "").strip()[:30]
        except Exception:
            chosen_text = "?"
        try:
            chosen.scroll_into_view_if_needed()
            try:
                chosen.click(timeout=4000)
            except Exception:
                chosen.click(force=True)
            print(f"        → Click [{step}]: '{chosen_text}'")
            human_pause(2.5, 4.5)
        except Exception as e:
            print(f"        ⚠ no pude clickear '{chosen_text}': {str(e)[:80]}")
            return _manual_fallback()

        # 4. ¿Éxito?
        if _detect_success(page):
            print("        ✓ Postulación enviada (HiringRoom)")
            _close_modal(page)
            return True
        if _detect_already_applied(page):
            print("        → Ya postulado (HiringRoom, post-submit) — el primer submit FUE exitoso")
            if log_ctx is not None:
                log_ctx.setdefault("notes", []).append("Ya postulado (post-submit)")
            _close_modal(page)
            return True

        # Dump del estado post-click para diagnóstico de banners no detectados
        if step == 1:
            _dump_html(page, label=f"post-click-step{step}")

        # 5. ¿Hay errores de validación visibles? Dumpear y abandonar.
        if _has_validation_errors(page):
            html_path = _dump_html(page, label=f"step{step}-validation-error")
            print(f"        ⚠ errores de validación. HTML: {html_path}")
            return _manual_fallback()

    print("        ⚠ se agotaron los pasos sin confirmación de envío.")
    html_path = _dump_html(page, label="exhausted-steps")
    print(f"          HTML: {html_path}")
    return _manual_fallback()


def _find_primary_action(page: Page):
    """Encuentra el botón de acción del form, excluyendo modales auxiliares."""
    excluded_form_ids = ["frm-support", "form_login", "formUpdate"]
    excluded_button_ids = ["btn-submit-supportForm"]

    # Orden de prioridad: submit final primero, luego continuar.
    text_priority = [
        "postularme", "enviar postulación", "enviar postulacion",
        "aplicar a esta oferta", "postular",
        "continuar", "siguiente", "next", "send", "enviar",
    ]

    try:
        result = page.evaluate(
            """([priority, excludedFormIds, excludedBtnIds]) => {
                document.querySelectorAll('[data-nr-action]').forEach(e => e.removeAttribute('data-nr-action'));
                const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                const inExcluded = (el) => {
                    let p = el.closest('form, section, div.modal, div[class*=modal i]');
                    while (p) {
                        if (p.id && excludedFormIds.includes(p.id)) return true;
                        p = p.parentElement?.closest('form, section, div.modal, div[class*=modal i]');
                    }
                    return false;
                };
                // Visibilidad real: estar en viewport (no off-screen via translate)
                // Y no tener un ancestro con display:none / visibility:hidden.
                const visible = (el) => {
                    const r = el.getBoundingClientRect();
                    if (r.width < 1 || r.height < 1) return false;
                    if (r.right < 0 || r.bottom < 0) return false;
                    if (r.left > (window.innerWidth || 1e9)) return false;
                    if (r.top > (window.innerHeight || 1e9) * 1.5) return false;
                    const cs = getComputedStyle(el);
                    if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) < 0.05) return false;
                    // Chequear ancestros (HiringRoom oculta tabs con display:none o transform)
                    let p = el.parentElement;
                    while (p && p !== document.body) {
                        const pcs = getComputedStyle(p);
                        if (pcs.display === 'none' || pcs.visibility === 'hidden') return false;
                        p = p.parentElement;
                    }
                    return true;
                };
                const all = Array.from(document.querySelectorAll(
                    "button, input[type='submit'], a[role='button'], [role='button']"
                ));
                const candidates = all
                    .filter(el => visible(el))
                    .filter(el => !excludedBtnIds.includes(el.id || ''))
                    .filter(el => !inExcluded(el) && !el.disabled)
                    .map(el => {
                        const r = el.getBoundingClientRect();
                        return {
                            el,
                            text: norm(el.innerText || el.value || el.textContent),
                            id: el.id || '',
                            // Score: preferir botones grandes (width=100% o más prominentes)
                            // y los que están en el centro del viewport.
                            area: r.width * r.height,
                            cls: el.className || '',
                        };
                    });

                // Por cada keyword en orden, encontrar TODOS los matches y elegir el más grande
                for (const kw of priority) {
                    const matches = candidates.filter(c => c.text && (c.text === kw || c.text.includes(kw)));
                    if (matches.length === 0) continue;
                    // Preferir width=100% (HiringRoom marca así el botón principal de cada step)
                    const wide = matches.filter(c => /\\bwidth\\b\\s*:\\s*100%/.test(c.el.getAttribute('style') || '') ||
                                                       c.el.getAttribute('width') === '100%');
                    const pool = wide.length ? wide : matches;
                    // Entre los del pool, elegir el más grande (área)
                    pool.sort((a, b) => b.area - a.area);
                    pool[0].el.setAttribute('data-nr-action', '1');
                    return {
                        ok: true,
                        text: pool[0].text,
                        id: pool[0].id,
                        cls: pool[0].cls.slice(0, 50),
                        area: Math.round(pool[0].area),
                        ofMatches: matches.length,
                    };
                }
                const submits = candidates.filter(c => c.el.type === 'submit');
                if (submits.length) {
                    submits.sort((a, b) => b.area - a.area);
                    submits[0].el.setAttribute('data-nr-action', '1');
                    return { ok: true, text: submits[0].text, id: submits[0].id, fallback: 'submit' };
                }
                return { ok: false };
            }""",
            [text_priority, excluded_form_ids, excluded_button_ids],
        )
    except Exception:
        return None

    if not result or not result.get("ok"):
        return None
    print(f"        ⓘ acción elegida: text='{result.get('text')}' cls='{result.get('cls','')}' area={result.get('area')} de {result.get('ofMatches', 1)} match(es)")
    try:
        el = page.locator("[data-nr-action='1']").first
        if el.count() == 0:
            return None
        return el
    except Exception:
        return None


def _has_turnstile(page: Page) -> bool:
    """Detecta widget de Cloudflare Turnstile sin resolver. Espera hasta 5s
    para que el widget renderice (es async)."""
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            state = page.evaluate(
                r"""() => {
                    const widget = document.querySelector('.cf-turnstile, iframe[src*="challenges.cloudflare.com"]');
                    const r = document.querySelector('input[name="cf-turnstile-response"]');
                    return {
                        hasWidget: !!widget,
                        hasInput: !!r,
                        tokenLen: r ? (r.value || '').length : 0,
                        widgetClass: widget ? widget.className : null,
                    };
                }"""
            )
            if state and state.get("tokenLen", 0) > 10:
                return False  # ya validado
            if state and (state.get("hasWidget") or state.get("hasInput")):
                print(f"        ⓘ Turnstile detectado: {state}")
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _preload_turnstile_token(page: Page) -> bool:
    """Pre-carga un token de Capsolver en window.__nrCapsolverToken antes de
    cualquier interacción. Si la página llama turnstile.execute() invisible,
    nuestro hijack devuelve este token directamente."""
    try:
        # Site key del meta tag de HiringRoom
        site_key = page.evaluate(
            r"""() => {
                const meta = document.querySelector('meta[name="hiringroom:cloudflare_recapcha"]');
                return meta ? meta.getAttribute('content') : null;
            }"""
        )
    except Exception:
        site_key = None
    if not site_key:
        return False
    print(f"        → Pre-cargando token Capsolver (Turnstile invisible)")
    token = capsolver.solve_turnstile(page.url, site_key)
    if not token:
        return False
    try:
        page.evaluate(
            r"""(token) => { window.__nrCapsolverToken = token; }""",
            token,
        )
        # También inyectar en cualquier input cf-turnstile-response que exista
        page.evaluate(
            r"""(token) => {
                document.querySelectorAll('input[name="cf-turnstile-response"]').forEach(inp => {
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    setter.call(inp, token);
                    inp.dispatchEvent(new Event('input', { bubbles: true }));
                    inp.dispatchEvent(new Event('change', { bubbles: true }));
                });
                // Llamar callbacks ya capturados
                (window.__nrTurnstileCallbacks || []).forEach(cb => {
                    try { cb(token); } catch (e) {}
                });
            }""",
            token,
        )
        print("        ✓ Token pre-cargado en window.__nrCapsolverToken")
        return True
    except Exception as e:
        print(f"        ⚠ pre-load token error: {str(e)[:80]}")
        return False


def _solve_turnstile_via_capsolver(page) -> bool:
    """Resuelve Turnstile vía Capsolver API → inyecta el token en el form.

    Steps:
      1. Extrae el site key del DOM (.cf-turnstile data-sitekey o meta tag).
      2. Llama a capsolver.solve_turnstile(url, site_key) — espera ~10-30s.
      3. Inyecta el token devuelto en input[name='cf-turnstile-response'].
      4. Dispara los eventos React para que el form lo registre.
    """
    # 1. Site key
    try:
        site_key = page.evaluate(
            r"""() => {
                // Prioridad: data-sitekey en .cf-turnstile (estándar Turnstile)
                const widget = document.querySelector('.cf-turnstile, [data-sitekey]');
                if (widget && widget.dataset.sitekey) return widget.dataset.sitekey;
                // Fallback: meta tag específico de HiringRoom
                const meta = document.querySelector('meta[name="hiringroom:cloudflare_recapcha"]');
                if (meta) return meta.getAttribute('content');
                return null;
            }"""
        )
    except Exception:
        site_key = None

    if not site_key:
        print("        ⚠ no encontré site key de Turnstile en el DOM")
        return False

    # 2. Resolver vía Capsolver
    token = capsolver.solve_turnstile(page.url, site_key)
    if not token:
        return False

    # 3. Inyectar token en el form + invocar callbacks capturados
    try:
        injected = page.evaluate(
            r"""(token) => {
                let inputCount = 0;
                let callbackCount = 0;
                // a) Setear value en TODOS los inputs cf-turnstile-response
                const inputs = document.querySelectorAll('input[name="cf-turnstile-response"]');
                for (const inp of inputs) {
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    setter.call(inp, token);
                    inp.dispatchEvent(new Event('input', { bubbles: true }));
                    inp.dispatchEvent(new Event('change', { bubbles: true }));
                    inputCount++;
                }
                // b) Invocar los callbacks de turnstile.render capturados por
                //    el hijack en EXTRA_STEALTH_SCRIPT — esto actualiza el
                //    state de React (react-turnstile / HiringRoom).
                const cbs = window.__nrTurnstileCallbacks || [];
                for (const cb of cbs) {
                    try { cb(token); callbackCount++; } catch (e) {}
                }
                // c) Fallback: callbacks nombrados comunes
                ['turnstileCallback', 'onTurnstileSuccess', 'onCfTurnstileSuccess'].forEach(name => {
                    if (typeof window[name] === 'function') {
                        try { window[name](token); callbackCount++; } catch (e) {}
                    }
                });
                return { ok: inputCount > 0 || callbackCount > 0, inputs: inputCount, callbacks: callbackCount };
            }""",
            token,
        )
        if injected and injected.get("ok"):
            print(f"        ✓ Token inyectado: {injected['inputs']} input(s) + {injected['callbacks']} callback(s)")
            if injected['callbacks'] == 0:
                print("          ⓘ aviso: 0 callbacks de Turnstile capturados. Si el submit falla, el hijack no corrió.")
            return True
        print(f"        ⚠ inyección falló: {injected}")
        return False
    except Exception as e:
        print(f"        ⚠ error inyectando token: {str(e)[:80]}")
        return False


def _solve_turnstile_via_cdp_detach(page) -> bool:
    """Truco anti-Cloudflare: pausa la página vía CDP detach simulado.

    No podemos desconectar el browser sin romper el resto del bot, pero sí
    podemos PAUSAR la conexión CDP momentáneamente vía CDP `Page.disable` y
    que el usuario haga el click del captcha + submit manualmente.

    Cloudflare detecta CDP por la presencia continua del WebSocket. Si la
    página queda intocada por un momento Y el usuario interactúa, el captcha
    auto-resuelve.

    Realidad: este truco NO siempre funciona. Devuelve True solo si tras
    timeout vemos `cf-turnstile-response` con valor.
    """
    import os
    if not os.environ.get("NR_CDP_URL"):
        return False
    print()
    print("        ┌─ MODO MANUAL ASISTIDO (form ya está lleno) ──────────────")
    print("        │ El bot llenó todo. Te queda solo:")
    print("        │")
    print("        │   1. Click en el checkbox de Cloudflare ('verifico que")
    print("        │      soy humano') en la ventana del bot. Esperá ~5s.")
    print("        │   2. Click en 'Enviar postulación'.")
    print("        │")
    print("        │ El bot va a esperar 90s para que termines.")
    print("        └────────────────────────────────────────────────────────────")
    # Intento auto-resolve durante 90s (a veces Cloudflare se relaja con tiempo)
    for _ in range(90):
        time.sleep(1)
        try:
            ok = page.evaluate(
                r"""() => {
                    const r = document.querySelector('input[name="cf-turnstile-response"]');
                    return !!(r && r.value && r.value.length > 10);
                }"""
            )
            if ok:
                print("        ✓ Turnstile validado.")
                return True
        except Exception:
            pass
    print("        ⓘ 90s sin validación. Pasando a fallback manual completo.")
    return False


def _captcha_unsolvable_dialog(url: str) -> str:
    """Cuando Turnstile no auto-resuelve, dale al usuario opciones claras.

    Realidad técnica: con Playwright + CDP attached, Cloudflare puede detectar
    automation vía timing attacks aún con todos los parches. Por default
    abrimos la URL en el Chrome principal del usuario (sin CDP) — ahí
    Cloudflare valida normalmente y la postulación se completa manual.
    """
    try:
        import subprocess
        subprocess.run(["pbcopy"], input=url.encode(), check=False, timeout=2)
        clip_msg = " (URL al portapapeles)"
    except Exception:
        clip_msg = ""
    print()
    print("        ┌─ Cloudflare Turnstile bloquea la automatización ──────────")
    print("        │ Cloudflare detecta el WebSocket CDP de Playwright y no")
    print("        │ deja validar el captcha. Recomendado: completá manual.")
    print(f"        │ URL: {url}{clip_msg}")
    print("        │")
    print("        │ Opciones:")
    print("        │   [m] (default) abrir en tu Chrome normal — completás ahí")
    print("        │   [w] reintentar en este browser (probable falle)")
    print("        │   [s] saltar — no completar esta oferta")
    print("        └────────────────────────────────────────────────────────────")
    ans = input("        Tu opción [m/w/s] (ENTER = m): ").strip().lower()
    if ans == "w":
        return "wait"
    if ans == "s":
        return "skip"
    # default = m → abrir en el browser default del sistema (tu Chrome normal)
    # NO usar `-a "Google Chrome"` porque podría caer en el Chrome del bot
    # (CDP), donde Cloudflare igual bloquea. `open URL` usa default browser
    # registrado en LaunchServices = tu Chrome principal.
    try:
        import subprocess
        subprocess.run(["open", url], check=False, timeout=3)
        print("        → URL abierta en tu browser default (Chrome principal sin CDP).")
        print("          ⚠ IMPORTANTE: completá la postulación en ESA ventana,")
        print("            NO en la ventana del bot (la que tiene la barra naranja de DevTools).")
        print("          Cuando termines (o si querés saltarla), ENTER para seguir.")
        input("        ENTER para continuar con la próxima oferta... ")
    except Exception as e:
        print(f"        ⚠ no pude abrir URL: {str(e)[:60]}")
    return "skip"


def _wait_for_turnstile_solved(page: Page, timeout: int = 60) -> bool:
    """Espera hasta `timeout` segundos a que cf-turnstile-response tenga valor."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            solved = page.evaluate(
                r"""() => {
                    const r = document.querySelector('input[name="cf-turnstile-response"]');
                    return !!(r && r.value && r.value.length > 10);
                }"""
            )
            if solved:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def _has_validation_errors(page: Page) -> bool:
    try:
        return bool(page.evaluate(
            r"""() => {
                const sels = ['.error-message:not(:empty)', '.invalid-feedback:not(:empty)', '[class*="error" i]:not(:empty):not(script):not(style)'];
                for (const s of sels) {
                    const els = document.querySelectorAll(s);
                    for (const e of els) {
                        const r = e.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0 && (e.innerText || '').trim().length > 2) return true;
                    }
                }
                return false;
            }"""
        ))
    except Exception:
        return False


def _dump_html(page: Page, label: str = "dump") -> str:
    """Guarda el HTML actual de la página en logs/debug/ para inspección.
    Devuelve la ruta absoluta. También guarda una version recortada con solo
    el contenido del formulario (#app) para facilitar copia/pega."""
    try:
        out_dir = ROOT / "logs" / "debug"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        # Versión completa
        path_full = out_dir / f"hiringroom-{label}-{ts}.html"
        html = page.content()
        path_full.write_text(html, encoding="utf-8")
        # Versión solo form (más compacta para pegar al chat)
        try:
            form_html = page.evaluate(
                r"""() => {
                    const app = document.querySelector('#app');
                    if (!app) return document.body.innerHTML;
                    // Quitar scripts y estilos para que sea más liviano
                    const clone = app.cloneNode(true);
                    clone.querySelectorAll('script, style, svg').forEach(e => e.remove());
                    return clone.outerHTML;
                }"""
            )
            path_form = out_dir / f"hiringroom-{label}-{ts}.form.html"
            path_form.write_text(form_html, encoding="utf-8")
        except Exception:
            pass
        # También un summary con valores de campos (rápido de inspeccionar)
        try:
            summary = page.evaluate(
                r"""() => {
                    const lines = [];
                    document.querySelectorAll('input, textarea').forEach(el => {
                        if (el.type === 'hidden') return;
                        const id = el.id || el.name || '';
                        if (!id) return;
                        let val = '';
                        if (el.type === 'checkbox' || el.type === 'radio') {
                            val = el.checked ? 'CHECKED' : '';
                        } else {
                            val = el.value || '';
                        }
                        lines.push(`${el.tagName}[${el.type || ''}] ${id} = "${val.slice(0,80)}"`);
                    });
                    document.querySelectorAll('.custom-hr-select__single-value').forEach(el => {
                        const ctrl = el.closest('.custom-hr-select-container');
                        const label = ctrl?.previousElementSibling?.innerText || ctrl?.parentElement?.querySelector('label')?.innerText || '?';
                        lines.push(`SELECT[${label}] = "${(el.innerText||'').slice(0,80)}"`);
                    });
                    document.querySelectorAll('.custom-hr-select__placeholder').forEach(el => {
                        const ctrl = el.closest('.custom-hr-select-container');
                        const label = ctrl?.parentElement?.querySelector('label')?.innerText || '?';
                        lines.push(`SELECT_EMPTY[${label}] = (placeholder: "${(el.innerText||'').slice(0,40)}")`);
                    });
                    return lines.join('\n');
                }"""
            )
            path_summary = out_dir / f"hiringroom-{label}-{ts}.summary.txt"
            path_summary.write_text(summary, encoding="utf-8")
        except Exception:
            pass
        return str(path_full.absolute())
    except Exception as e:
        return f"<dump-failed: {e}>"


def _manual_fallback() -> bool:
    r = input("        [s] terminé manualmente / [n] saltar: ").strip().lower()
    return r == "s"


def _close_modal(page: Page) -> bool:
    """Cierra el popup/modal de confirmación.

    HiringRoom muestra un modal con texto "Tu postulación fue realizada".
    Intentamos varios métodos vía JS para encontrar el botón de cerrar.
    """
    try:
        result = page.evaluate(
            r"""() => {
                // 1. Buscar botones con texto típico de cierre dentro de modales
                const closeWords = ['cerrar', 'aceptar', 'ok', 'continuar', 'volver', 'finalizar', 'entendido', 'listo'];
                const containers = Array.from(document.querySelectorAll(
                    "[role='dialog'], .modal, [class*='Modal' i], [class*='modal' i], [class*='popup' i], [class*='Popup' i]"
                ));
                for (const cnt of containers) {
                    const r = cnt.getBoundingClientRect();
                    if (r.width < 1 || r.height < 1) continue;
                    const cs = getComputedStyle(cnt);
                    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
                    // Buscar buttons dentro
                    const buttons = cnt.querySelectorAll('button, a[role="button"]');
                    for (const btn of buttons) {
                        const txt = (btn.innerText || btn.textContent || '').trim().toLowerCase();
                        if (closeWords.some(w => txt === w || txt.includes(w))) {
                            btn.click();
                            return { ok: true, method: 'word-match', text: txt };
                        }
                    }
                    // Buscar X (svg/icon close button)
                    for (const btn of buttons) {
                        const cls = btn.className || '';
                        if (/close|cerrar|×/.test(cls)) {
                            btn.click();
                            return { ok: true, method: 'class-close', cls };
                        }
                        // Botón sin texto pero con SVG (típico botón X)
                        if (!btn.innerText.trim() && btn.querySelector('svg, img, span[class*="icon" i]')) {
                            btn.click();
                            return { ok: true, method: 'icon-only' };
                        }
                    }
                }
                // 2. Botones globales con aria-label de cerrar
                const ariaBtns = document.querySelectorAll(
                    "button[aria-label*='cerrar' i], button[aria-label*='close' i], button[aria-label*='dismiss' i]"
                );
                for (const btn of ariaBtns) {
                    const r = btn.getBoundingClientRect();
                    if (r.width < 1 || r.height < 1) continue;
                    btn.click();
                    return { ok: true, method: 'aria-label' };
                }
                return { ok: false };
            }"""
        )
        if result and result.get("ok"):
            print(f"        → Modal cerrado ({result.get('method')})")
            time.sleep(0.5)
            return True
    except Exception as e:
        print(f"        ⓘ close modal JS error: {str(e)[:60]}")

    # Fallback: presionar Escape
    try:
        page.keyboard.press("Escape")
        time.sleep(0.3)
    except Exception:
        pass
    return False


def _detect_success(page: Page) -> bool:
    """Detecta indicadores de envío exitoso. Usa el HTML completo (no solo
    body.innerText) para capturar modales/portals."""
    keywords = [
        # Frases exactas confirmadas en HiringRoom:
        "tu postulación fue realizada correctamente",
        "tu postulacion fue realizada correctamente",
        "contamos con tu perfil en nuestra base",
        "gracias por participar del proceso",
        "muchas gracias por participar",
        # Otras genéricas:
        "postulación enviada", "postulacion enviada",
        "tu postulación fue enviada", "postulación exitosa", "postulacion exitosa",
        "gracias por postular", "gracias por aplicar",
        "hemos recibido tu postulación", "hemos recibido tu postulacion", "hemos recibido",
        "aplicación enviada", "aplicacion enviada",
        "te has postulado", "candidatura enviada",
        "tu postulación ha sido", "tu solicitud ha sido recibida",
        "registramos tu postulación", "postulación registrada",
        "te contactaremos", "revisaremos tu",
        "tu postulación se realizó", "se realizo correctamente",
    ]
    try:
        html = page.content().lower()
        for kw in keywords:
            if kw in html:
                return True
    except Exception:
        pass
    return False
