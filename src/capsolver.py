"""Cliente Capsolver para resolver Cloudflare Turnstile.

API key en `.env` como CAPSOLVER_API_KEY.
Costo aprox: $0.001 por captcha resuelto.

Flujo:
  1. POST /createTask con websiteURL + websiteKey → taskId
  2. Poll /getTaskResult con taskId hasta status='ready' → token
  3. El llamador inyecta el token en input[name='cf-turnstile-response']
"""
import os
import ssl
import time
import json
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass


CAPSOLVER_API = "https://api.capsolver.com"
TIMEOUT_TOTAL = 120  # segundos máximo de polling
POLL_INTERVAL = 3


def _ssl_context() -> ssl.SSLContext:
    """SSL context con CA bundle de certifi (Python en macOS no encuentra
    los certs del sistema por default)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        # Fallback: contexto default. Puede fallar en macOS con CERTIFICATE_VERIFY_FAILED.
        return ssl.create_default_context()


def _post_json(url: str, payload: dict, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        return json.loads(resp.read().decode("utf-8"))


def solve_turnstile(website_url: str, website_key: str, action: str = None) -> str | None:
    """Resuelve Turnstile vía Capsolver. Devuelve el token o None si falla."""
    api_key = os.environ.get("CAPSOLVER_API_KEY")
    if not api_key:
        print("        ⚠ CAPSOLVER_API_KEY no seteada en .env")
        return None
    if not website_key or not website_url:
        print(f"        ⚠ falta website_key o url para Capsolver")
        return None

    task = {
        "type": "AntiTurnstileTaskProxyLess",
        "websiteURL": website_url,
        "websiteKey": website_key,
    }
    if action:
        task["metadata"] = {"action": action}

    try:
        # 1. Crear task
        print(f"        → Capsolver: pidiendo solución (siteKey={website_key[:20]}...)")
        resp = _post_json(
            f"{CAPSOLVER_API}/createTask",
            {"clientKey": api_key, "task": task},
        )
        if resp.get("errorId"):
            print(f"        ⚠ Capsolver createTask error: {resp.get('errorDescription')}")
            return None
        task_id = resp.get("taskId")
        if not task_id:
            print(f"        ⚠ Capsolver no devolvió taskId: {resp}")
            return None

        # 2. Polling
        deadline = time.time() + TIMEOUT_TOTAL
        while time.time() < deadline:
            time.sleep(POLL_INTERVAL)
            resp = _post_json(
                f"{CAPSOLVER_API}/getTaskResult",
                {"clientKey": api_key, "taskId": task_id},
            )
            status = resp.get("status")
            if status == "ready":
                token = (resp.get("solution") or {}).get("token")
                if token:
                    print(f"        ✓ Capsolver resolvió Turnstile en {int(time.time() - (deadline - TIMEOUT_TOTAL))}s")
                    return token
                print(f"        ⚠ Capsolver ready sin token: {resp}")
                return None
            if status == "failed" or resp.get("errorId"):
                print(f"        ⚠ Capsolver falló: {resp.get('errorDescription', resp)}")
                return None
            # status == "processing" → seguir
        print(f"        ⚠ Capsolver timeout ({TIMEOUT_TOTAL}s)")
        return None
    except urllib.error.HTTPError as e:
        print(f"        ⚠ Capsolver HTTP {e.code}: {e.reason}")
        return None
    except Exception as e:
        print(f"        ⚠ Capsolver error: {str(e)[:100]}")
        return None


def get_balance(verbose: bool = False) -> float | None:
    """Devuelve el balance USD de la cuenta. None si no hay API key o falla.
    Si verbose=True, imprime el error específico."""
    api_key = os.environ.get("CAPSOLVER_API_KEY")
    if not api_key:
        if verbose:
            print("  [debug] CAPSOLVER_API_KEY vacía")
        return None
    try:
        resp = _post_json(f"{CAPSOLVER_API}/getBalance", {"clientKey": api_key})
        if verbose:
            print(f"  [debug] respuesta: {resp}")
        if resp.get("errorId"):
            if verbose:
                print(f"  [debug] errorId={resp.get('errorId')} desc={resp.get('errorDescription')}")
            return None
        return float(resp.get("balance", 0))
    except urllib.error.HTTPError as e:
        if verbose:
            try:
                body = e.read().decode("utf-8")
            except Exception:
                body = ""
            print(f"  [debug] HTTP {e.code} {e.reason}: {body[:200]}")
        return None
    except urllib.error.URLError as e:
        if verbose:
            print(f"  [debug] URLError: {e.reason}")
        return None
    except Exception as e:
        if verbose:
            print(f"  [debug] {type(e).__name__}: {str(e)[:200]}")
        return None
