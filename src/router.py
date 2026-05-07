"""Decide qué handler usar según el dominio de la URL externa."""
import os
from urllib.parse import urlparse


# Lista de plataformas a saltear (separadas por coma).
# Util cuando Cloudflare flagea tu IP y HiringRoom queda inutilizable —
# corré con: NR_SKIP=hiringroom python main.py ...
NR_SKIP = set(s.strip().lower() for s in os.environ.get("NR_SKIP", "").split(",") if s.strip())


def route_for_url(url: str) -> str:
    """Devuelve clave del handler ('hiringroom', 'computrabajo') o None si no se automatiza."""
    if not url:
        return None
    host = urlparse(url).netloc.lower()
    handler = None
    if "hiringroom.com" in host:
        handler = "hiringroom"
    elif "pandape." in host:
        handler = "pandape"
    elif "computrabajo." in host:
        handler = "computrabajo"
    if handler and handler in NR_SKIP:
        return None  # forzar fallback a "manual" (usuario salta)
    return handler


def short_domain(url: str) -> str:
    if not url:
        return ""
    host = urlparse(url).netloc.lower()
    return host.replace("www.", "")
