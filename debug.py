"""Shell de depuración. Abre Chromium con sesión persistente y deja una
consola Python interactiva con helpers para volcar selectores reales.

Uso:
    python debug.py linkedin
    python debug.py computrabajo
    python debug.py hiringroom <URL>
    python debug.py <cualquier-URL>
"""
import code
import sys
from src import browser


PLATFORMS = ["linkedin", "computrabajo", "hiringroom"]
STARTING_URLS = {
    "linkedin": (
        "https://www.linkedin.com/jobs/search/"
        "?keywords=gerente%20general&location=Lima%2C%20Peru&sortBy=DD"
    ),
    "computrabajo": "https://www.computrabajo.com.pe/trabajo-de-gerente-general",
}


def banner(target):
    print(
        f"""
=== DEBUG SHELL — {target} ===

Comandos:
  jobs()          cards de ofertas (selectores candidatos)
  header()        título / empresa
  apply_button()  botones de Apply / Postularme
  modal()         contenido de role=dialog (LinkedIn)
  form()          formulario inline (Computrabajo / HiringRoom)
  go(url)         navegar
  page            objeto Playwright Page

Salir: exit() o Ctrl-D
"""
    )


def make_helpers(page):
    def jobs():
        selectors = [
            # LinkedIn
            "li[data-occludable-job-id]",
            "li.jobs-search-results__list-item",
            ".job-card-container",
            "div.job-card-container--clickable",
            "ul.scaffold-layout__list-container > li",
            # Computrabajo
            "article.box_offer",
            "article a.js-o-link",
        ]
        for s in selectors:
            n = page.locator(s).count()
            mark = "✓" if n else " "
            print(f"  {mark} {n:4d}  {s}")

    def header():
        selectors = [
            ("LI title v1", ".jobs-unified-top-card__job-title"),
            ("LI title v2", ".job-details-jobs-unified-top-card__job-title"),
            ("LI company v1", ".jobs-unified-top-card__company-name"),
            ("LI company v2", ".job-details-jobs-unified-top-card__company-name a"),
            ("CT/HR h1", "h1"),
            ("CT company", "p.fc_base, a.fc_base"),
            ("HR company", ".company-name, [class*='company']"),
        ]
        for name, sel in selectors:
            try:
                t = page.locator(sel).first.inner_text(timeout=1500).strip()
                print(f"  ✓ {name:18s}  {sel}\n      → {t[:80]}")
            except Exception:
                print(f"  · {name:18s}  {sel}")

    def apply_button():
        selectors = [
            "button.jobs-apply-button",
            "button[aria-label*='Easy Apply']",
            "button[aria-label*='Solicitud sencilla']",
            "button:has-text('Easy Apply')",
            "button:has-text('Solicitud sencilla')",
            "button:has-text('Postularme')",
            "button:has-text('Postular')",
            "button:has-text('Aplicar')",
            "a:has-text('Postularme')",
            "a:has-text('Aplicar')",
        ]
        for s in selectors:
            loc = page.locator(s)
            n = loc.count()
            if n:
                try:
                    t = (loc.first.inner_text(timeout=500) or "").strip().replace("\n", " ")
                except Exception:
                    t = ""
                try:
                    aria = loc.first.get_attribute("aria-label") or ""
                except Exception:
                    aria = ""
                print(f"  ✓ {n:2d}  {s}\n      text='{t[:40]}' aria='{aria[:40]}'")
            else:
                print(f"  ·  0  {s}")

    def modal():
        print("\n  --- CONTENEDOR MODAL ---")
        for s in [
            "div.jobs-easy-apply-modal",
            "div[data-test-modal][role='dialog']",
            "div[role='dialog']",
            ".artdeco-modal",
        ]:
            n = page.locator(s).count()
            print(f"  {'✓' if n else '·'}  {n}  {s}")

        print("\n  --- BOTONES ---")
        for b in page.locator("div[role='dialog'] button").all():
            try:
                text = (b.inner_text(timeout=300) or "").strip().replace("\n", " ")
                aria = b.get_attribute("aria-label") or ""
                cls = (b.get_attribute("class") or "")[:60]
                print(f"    text='{text[:40]}' aria='{aria[:50]}' class='{cls}'")
            except Exception:
                pass

        print("\n  --- INPUTS / SELECTS / TEXTAREAS ---")
        for f in page.locator(
            "div[role='dialog'] input, div[role='dialog'] select, div[role='dialog'] textarea"
        ).all():
            _print_field(page, f)

        print("\n  --- FIELDSETS (radios) ---")
        for el in page.locator("div[role='dialog'] fieldset").all():
            try:
                legend = el.locator("legend").first.inner_text(timeout=300).strip()
                opts = [o.inner_text(timeout=200).strip() for o in el.locator("label").all()]
                print(f"    legend='{legend[:50]}' opciones={opts}")
            except Exception:
                pass

    def form():
        print(f"\n  --- FORMULARIO (página {page.url[:60]}) ---")
        n_forms = page.locator("form").count()
        print(f"  forms en la página: {n_forms}")

        print("\n  --- FILE INPUTS (CV upload) ---")
        for f in page.locator("input[type='file']").all():
            try:
                name = f.get_attribute("name") or ""
                accept = f.get_attribute("accept") or ""
                print(f"    name='{name}' accept='{accept}'")
            except Exception:
                pass

        print("\n  --- INPUTS / SELECTS / TEXTAREAS ---")
        for f in page.locator(
            "form input:not([type=hidden]):not([type=submit]), form select, form textarea"
        ).all():
            _print_field(page, f)

        print("\n  --- BOTONES DE SUBMIT ---")
        for b in page.locator("form button, form input[type=submit]").all():
            try:
                tag = b.evaluate("e => e.tagName.toLowerCase()")
                t = (b.inner_text(timeout=300) or "").strip()
                ttype = b.get_attribute("type") or ""
                print(f"    <{tag} type={ttype}>  text='{t[:40]}'")
            except Exception:
                pass

    def go(url):
        page.goto(url)

    return jobs, header, apply_button, modal, form, go


def _print_field(page, f):
    try:
        tag = f.evaluate("e => e.tagName.toLowerCase()")
        t = f.get_attribute("type") or ""
        name = f.get_attribute("name") or ""
        ph = f.get_attribute("placeholder") or ""
        aria = f.get_attribute("aria-label") or ""
        fid = f.get_attribute("id") or ""
        label = ""
        if fid:
            try:
                label = page.locator(f"label[for='{fid}']").first.inner_text(timeout=300).strip()
            except Exception:
                pass
        print(
            f"    <{tag} type={t:8s}>  label='{label[:35]}'  aria='{aria[:30]}'  ph='{ph[:25]}'  name='{name[:25]}'"
        )
    except Exception:
        pass


def resolve_url(args):
    if not args:
        print("Uso: python debug.py [linkedin|computrabajo|hiringroom <URL>|<URL>]")
        sys.exit(1)
    arg = args[0]
    if arg in STARTING_URLS:
        return arg, STARTING_URLS[arg]
    if arg == "hiringroom":
        if len(args) < 2:
            url = input("URL HiringRoom: ").strip()
        else:
            url = args[1]
        return "hiringroom", url
    if arg.startswith("http"):
        return "custom", arg
    print(f"Argumento no reconocido: {arg}")
    sys.exit(1)


def main():
    target, url = resolve_url(sys.argv[1:])
    pw, ctx = browser.launch()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    if url:
        try:
            page.goto(url)
        except Exception as e:
            print(f"⚠ No abrió {url}: {e}")
    jobs, header, apply_button, modal, form, go = make_helpers(page)
    banner(target)
    try:
        code.interact(local=dict(globals(), **locals()))
    finally:
        ctx.close()
        pw.stop()


if __name__ == "__main__":
    main()
