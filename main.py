"""Punto de entrada. Busca en LinkedIn y rutea a handlers según el dominio destino.

Uso:
    python main.py                          # menú interactivo de keywords
    python main.py -k "Gerente Comercial"   # usar SOLO esta keyword (puede repetir -k)
    python main.py -a "Jefe de Tesorería"   # agregar a las del config (puede repetir -a)
    python main.py -y                       # no preguntar, usar config tal cual
    python main.py -l "Peru"                # override de ubicación para -k / -a
"""
import argparse
import json
import sys
from pathlib import Path

import yaml

from src import browser, state, linkedin

ROOT = Path(__file__).parent
DEFAULT_LOCATION = "Lima, Peru"


def load_config():
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_profile():
    with open(ROOT / "profile.json", encoding="utf-8") as f:
        return json.load(f)


def parse_args():
    p = argparse.ArgumentParser(
        description="Postular en LinkedIn con routing a HiringRoom/Computrabajo.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("-k", "--keyword", action="append", default=[],
                   help="Usar SOLO estas keywords (repetible). Ignora config.yaml")
    p.add_argument("-a", "--add", action="append", default=[],
                   help="Agregar estas keywords a las del config (repetible)")
    p.add_argument("-l", "--location", default=None,
                   help=f"Ubicación para keywords nuevas (default: {DEFAULT_LOCATION})")
    p.add_argument("-y", "--yes", action="store_true",
                   help="No preguntar, usar config tal cual")
    return p.parse_args()


def show_searches(searches, title="Keywords actuales"):
    print(f"\n  === {title} ===")
    for i, s in enumerate(searches, 1):
        print(f"   {i:2d}) {s['keywords']}  ({s.get('location', DEFAULT_LOCATION)})")


def prompt_keywords(loc):
    """Pide keywords una por línea hasta línea vacía."""
    print(f"  Pega keywords (una por línea, ubicación '{loc}'). ENTER vacío para terminar.")
    out = []
    while True:
        line = input("  > ").strip()
        if not line:
            break
        out.append({"keywords": line, "location": loc})
    return out


def keyword_menu(config_searches):
    show_searches(config_searches)
    print(
        "\n  ¿Qué hacer?"
        "\n   [ENTER]  Usar estas tal cual"
        "\n   a        Agregar más (mantiene las actuales)"
        "\n   r        Reemplazar todas"
        "\n   q        Cancelar"
    )
    while True:
        choice = input("  Tu elección: ").strip().lower()
        if choice == "":
            return config_searches
        if choice == "q":
            sys.exit(0)
        if choice == "a":
            loc = input(f"  Ubicación para las nuevas (ENTER = {DEFAULT_LOCATION}): ").strip() or DEFAULT_LOCATION
            extras = prompt_keywords(loc)
            return config_searches + extras
        if choice == "r":
            loc = input(f"  Ubicación (ENTER = {DEFAULT_LOCATION}): ").strip() or DEFAULT_LOCATION
            new = prompt_keywords(loc)
            return new if new else config_searches
        print("  Opción no válida.")


def resolve_searches(args, config):
    cfg_searches = config["linkedin"].get("searches", [])
    loc = args.location or DEFAULT_LOCATION

    if args.keyword:
        return [{"keywords": k, "location": loc} for k in args.keyword]
    if args.add:
        extras = [{"keywords": k, "location": loc} for k in args.add]
        return cfg_searches + extras
    if args.yes:
        return cfg_searches
    return keyword_menu(cfg_searches)


def main():
    args = parse_args()
    config = load_config()
    profile = load_profile()

    cv_path = ROOT / profile.get("cv_path", "cv/alex.pdf")
    if not cv_path.exists():
        print(f"⚠ No se encontró el CV en {cv_path}. Algunas postulaciones pueden fallar.")

    searches = resolve_searches(args, config)
    if not searches:
        print("No hay keywords para buscar. Saliendo.")
        return 1

    show_searches(searches, title="Buscando con")
    config["linkedin"]["searches"] = searches

    conn = state.init_db()
    pw, ctx = browser.launch()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    try:
        linkedin.search_and_apply(page, ctx, conn, profile, config["linkedin"])
    except KeyboardInterrupt:
        print("\n→ Interrumpido por el usuario.")
    finally:
        try:
            input("\n→ Presiona ENTER para cerrar el navegador... ")
        except EOFError:
            pass
        ctx.close()
        pw.stop()
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
