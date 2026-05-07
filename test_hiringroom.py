#!/usr/bin/env python3
"""Test del handler HiringRoom en aislamiento.

Pasale una URL de oferta de HiringRoom y el bot:
  1. Conecta a tu Chrome (CDP) o lanza uno nuevo.
  2. Navega a la URL.
  3. Click 'Postularse'.
  4. Switch a 'Currículum manual'.
  5. Llena todos los campos + responde questions con LLM.
  6. Resuelve Turnstile con Capsolver.
  7. Submit.

Uso:
  # Con Chrome del bot ya corriendo (./start-chrome.sh):
  NR_CDP_URL=http://localhost:9222 python test_hiringroom.py URL_DE_OFERTA

  # Sin CDP (lanza Chrome nuevo):
  python test_hiringroom.py URL_DE_OFERTA

  # Default URL si no pasás argumento:
  python test_hiringroom.py
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from src import browser, hiringroom

DEFAULT_URL = "https://proempresa.hiringroom.com/jobs/get_vacancy/69f0d2114e38ce55b989d68e?source=linkedinjobs"


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    # Limpiar shell escapes accidentales (\?, \=, \&) que rompen el server
    url = url.replace("\\?", "?").replace("\\=", "=").replace("\\&", "&").strip()
    print(f"\n=== Test HiringRoom ===")
    print(f"URL: {url}\n")

    profile_path = ROOT / "profile.json"
    if not profile_path.exists():
        print(f"⚠ No se encontró {profile_path}")
        sys.exit(1)
    profile = json.loads(profile_path.read_text(encoding="utf-8"))

    pw, ctx = browser.launch()

    # Reusar la primera page abierta (con cookies del Chrome) o crear nueva
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    print(f"→ Navegando a {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(3)

    log_ctx = {
        "killer_questions": [],
        "notes": [],
        "errors": [],
    }

    print("\n=== Iniciando apply_on_page ===\n")
    t0 = time.time()
    try:
        result = hiringroom.apply_on_page(page, profile, log_ctx)
        elapsed = time.time() - t0
        print(f"\n=== Resultado ===")
        print(f"  apply_on_page retornó: {result}")
        print(f"  Tiempo total: {elapsed:.1f}s")
        print(f"  killer_questions: {len(log_ctx.get('killer_questions', []))}")
        for kq in log_ctx.get("killer_questions", []):
            print(f"    Q: {kq.get('question', '')[:60]}")
            print(f"    A: {kq.get('answer', '')[:60]}")
        if log_ctx.get("notes"):
            print(f"  Notes: {log_ctx['notes']}")
    except KeyboardInterrupt:
        print("\n[Ctrl+C] interrumpido por usuario")
    except Exception as e:
        import traceback
        print(f"\n⚠ Error: {e}")
        traceback.print_exc()

    print("\n→ Test terminado. ENTER para cerrar...")
    try:
        input()
    except EOFError:
        pass


if __name__ == "__main__":
    main()
