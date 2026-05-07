"""Test del parseo del CV en Pandapé.

Uso:
    python test_pandape.py "<URL_PANDAPE>"

Hace:
  1. Abre la URL.
  2. Sube cv/alex_ats.docx al input #CvInputFile.
  3. Espera 8 segundos a que el parser haga su trabajo.
  4. Dumpea cada input/select/textarea: id, name, label, valor.
  5. Guarda todo en pandape_dump.txt y lo imprime en consola.

NO hace submit. Solo diagnóstico.
"""
import sys
import time
import json
from pathlib import Path

from src import browser

ROOT = Path(__file__).parent
CV = ROOT / "cv" / "alex_ats.docx"
OUT = ROOT / "pandape_dump.txt"


def label_for(page, fid: str) -> str:
    if not fid:
        return ""
    try:
        return page.locator(f"label[for='{fid}']").first.inner_text(timeout=300).strip()
    except Exception:
        return ""


def dump_fields(page) -> str:
    lines = []
    fields = page.locator(
        "form input:not([type=hidden]):not([type=submit]):not([type=file]):not([type=checkbox]):not([type=radio]), "
        "form select, form textarea"
    ).all()
    lines.append(f"=== INPUTS / SELECTS / TEXTAREAS ({len(fields)}) ===")
    for f in fields:
        try:
            tag = f.evaluate("e => e.tagName.toLowerCase()")
            ttype = f.get_attribute("type") or ""
            fid = f.get_attribute("id") or ""
            name = f.get_attribute("name") or ""
            placeholder = f.get_attribute("placeholder") or ""
            lab = label_for(page, fid)
            try:
                val = f.input_value()
            except Exception:
                val = ""
            mark = "✓" if (val and val.strip()) else "✗"
            lines.append(
                f"  {mark} <{tag} type={ttype}> id={fid!r} name={name!r}"
            )
            lines.append(f"      label={lab!r}  ph={placeholder!r}")
            lines.append(f"      value={val!r}")
        except Exception as e:
            lines.append(f"  ! error: {e}")

    boxes = page.locator("form input[type=checkbox]").all()
    lines.append(f"\n=== CHECKBOXES ({len(boxes)}) ===")
    for cb in boxes:
        try:
            fid = cb.get_attribute("id") or ""
            name = cb.get_attribute("name") or ""
            checked = cb.is_checked()
            lab = label_for(page, fid)
            mark = "☑" if checked else "☐"
            lines.append(f"  {mark} id={fid!r} name={name!r} label={lab!r}")
        except Exception:
            pass

    radios = page.locator("form input[type=radio]").all()
    lines.append(f"\n=== RADIOS ({len(radios)}) ===")
    for r in radios:
        try:
            fid = r.get_attribute("id") or ""
            name = r.get_attribute("name") or ""
            val = r.get_attribute("value") or ""
            checked = r.is_checked()
            lab = label_for(page, fid)
            mark = "●" if checked else "○"
            lines.append(f"  {mark} id={fid!r} name={name!r} value={val!r} label={lab!r}")
        except Exception:
            pass

    # Componentes dinámicos (experiencia, educación) — listar
    lines.append("\n=== SECCIONES COLAPSABLES ===")
    sections = page.locator("a.js_btnCollapse").all()
    for s in sections:
        try:
            txt = s.inner_text(timeout=500).strip().replace("\n", " ")
            collapsed = "collapsed" in (s.get_attribute("class") or "")
            target = s.get_attribute("data-target") or ""
            mark = "▶" if collapsed else "▼"
            lines.append(f"  {mark} {txt[:60]}  target={target}")
        except Exception:
            pass

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Uso: python test_pandape.py '<URL>'")
        sys.exit(1)
    url = sys.argv[1]

    if not CV.exists():
        print(f"⚠ No existe {CV}")
        sys.exit(1)

    pw, ctx = browser.launch()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    try:
        print(f"→ Abriendo {url[:80]}...")
        page.goto(url, timeout=30000)
        page.wait_for_load_state("domcontentloaded", timeout=20000)
        time.sleep(3)

        if "login" in page.url.lower() or "ingresar" in page.url.lower():
            print("\n⚠ Pandapé pide login.")
            input("  Logueate manualmente y presiona ENTER... ")

        if page.locator("#CvInputFile").count() == 0:
            print("\n⚠ No se encontró #CvInputFile — ¿estás en la página correcta?")
            input("  ENTER para dumpear lo que haya... ")
        else:
            print(f"→ Subiendo {CV.name} a #CvInputFile...")
            page.locator("#CvInputFile").set_input_files(str(CV))
            print("→ Esperando 8s para que parsee...")
            time.sleep(8)

        # Expandir secciones
        for s in page.locator("a.js_btnCollapse.collapsed").all():
            try:
                s.click(timeout=800)
            except Exception:
                pass
        time.sleep(1)

        dump = dump_fields(page)
        OUT.write_text(dump, encoding="utf-8")
        print(f"\n=== DUMP COMPLETO ===\n")
        print(dump)
        print(f"\n→ Guardado en {OUT}")
        input("\n→ Presiona ENTER para cerrar el navegador... ")
    finally:
        ctx.close()
        pw.stop()


if __name__ == "__main__":
    main()
