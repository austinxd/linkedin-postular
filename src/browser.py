import os
from pathlib import Path
from playwright.sync_api import sync_playwright

# Stealth puede romper el renderer de algunos sitios (LinkedIn carga sin CSS).
# Activá con NR_STEALTH=1 para Cloudflare Turnstile, dejá apagado para LinkedIn.
ENABLE_STEALTH = os.environ.get("NR_STEALTH", "0") == "1"

try:
    from playwright_stealth import stealth_sync, StealthConfig
    HAS_STEALTH = True
except ImportError:
    HAS_STEALTH = False

PROFILE_DIR = Path(__file__).parent.parent / "browser-profile"

# Patches extra encima de stealth_sync — refuerza navigator.languages y
# elimina markers ChromeDriver que stealth no toca.
# AGREGADO: hijack de turnstile.render para capturar el callback que la
# librería react-turnstile (que usa HiringRoom) registra. Después llamamos
# ese callback con el token de Capsolver para que React actualice su state.
EXTRA_STEALTH_SCRIPT = r"""
Object.defineProperty(Navigator.prototype, 'languages', { get: () => ['es-PE', 'es', 'en-US', 'en'] });
delete window.__playwright;
delete window.__pwInitScripts;
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;

// === Turnstile hijack (no intrusivo) ===
// Polling: cuando window.turnstile aparece, envolvemos render/execute SIN
// usar defineProperty (que puede romper el widget en algunos browsers).
(function() {
    window.__nrTurnstileCallbacks = window.__nrTurnstileCallbacks || [];
    window.__nrTurnstileWidgets = window.__nrTurnstileWidgets || {};
    window.__nrTurnstileEvents = window.__nrTurnstileEvents || [];

    function logEvent(type, detail) {
        try { window.__nrTurnstileEvents.push({ ts: Date.now(), type, detail }); } catch(e) {}
    }

    function wrapTurnstile(ts) {
        if (!ts || ts.__nrWrapped) return false;
        const origRender = ts.render;
        const origExecute = ts.execute;
        if (typeof origRender === 'function') {
            ts.render = function(container, options) {
                try {
                    if (options && typeof options.callback === 'function') {
                        window.__nrTurnstileCallbacks.push(options.callback);
                        logEvent('render', { sitekey: options.sitekey, hasCallback: true });
                    }
                } catch (e) {}
                const wid = origRender.apply(this, arguments);
                try { window.__nrTurnstileWidgets[wid] = options; } catch(e) {}
                return wid;
            };
        }
        if (typeof origExecute === 'function') {
            ts.execute = function(widgetId, options) {
                logEvent('execute', { widgetId, hasToken: !!window.__nrCapsolverToken });
                const w = window.__nrTurnstileWidgets[widgetId];
                if (window.__nrCapsolverToken && w && typeof w.callback === 'function') {
                    try {
                        w.callback(window.__nrCapsolverToken);
                        logEvent('execute-fast', 'used cached token');
                        return Promise.resolve(window.__nrCapsolverToken);
                    } catch (e) {
                        logEvent('execute-error', String(e));
                    }
                }
                return origExecute.apply(this, arguments);
            };
        }
        ts.__nrWrapped = true;
        return true;
    }

    // Estrategia 1: Hijack `cf__reactTurnstileOnLoad` (función puente que la
    // página define y api.js llama tras cargarse). Lo envolvemos para que
    // ANTES de llamar la original (que invoca turnstile.render), wrap turnstile.
    let onloadHijacked = false;
    function tryHijackOnload() {
        if (onloadHijacked) return true;
        const orig = window.cf__reactTurnstileOnLoad;
        if (typeof orig === 'function') {
            window.cf__reactTurnstileOnLoad = function() {
                if (window.turnstile) {
                    wrapTurnstile(window.turnstile);
                    logEvent('hijack', 'via cf__reactTurnstileOnLoad');
                }
                return orig.apply(this, arguments);
            };
            onloadHijacked = true;
            return true;
        }
        return false;
    }

    // Estrategia 2 (fallback): polling de window.turnstile.
    // Estrategia 3: MutationObserver para script tags de cloudflare.
    let tries = 0;
    const interval = setInterval(() => {
        if (tryHijackOnload()) {
            clearInterval(interval);
            return;
        }
        if (window.turnstile && wrapTurnstile(window.turnstile)) {
            logEvent('hijack', 'via polling after ' + tries + ' tries');
            clearInterval(interval);
            return;
        }
        if (++tries > 600) clearInterval(interval); // 30s @ 50ms
    }, 50);

    // Watch for cloudflare script tag insertion
    try {
        const obs = new MutationObserver(() => {
            tryHijackOnload();
            if (window.turnstile) wrapTurnstile(window.turnstile);
        });
        obs.observe(document.documentElement || document, { childList: true, subtree: true });
    } catch (e) {}
})();
"""


def launch(use_chrome: bool = True):
    """Lanza el browser. Tres modos en orden de preferencia:

      1. NR_CDP_URL=http://localhost:9222 → conecta a Chrome ya corriendo.
         Es lo más bot-resistente: Cloudflare ve un Chrome normal lanzado por
         vos manualmente, no por Playwright.

      2. channel='chrome' → lanza Chrome del sistema (mejor que Chromium pero
         todavía detectable por CDP).

      3. Chromium de Playwright (último recurso).
    """
    pw = sync_playwright().start()

    # Modo 1: connect_over_cdp
    cdp_url = os.environ.get("NR_CDP_URL")
    if cdp_url:
        try:
            browser = pw.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            print(f"[browser] conectado vía CDP a {cdp_url}")
            # En modo CDP no se aplica stealth porque el Chrome es real.
            context.add_init_script(EXTRA_STEALTH_SCRIPT)
            return pw, context
        except Exception as e:
            print(f"[browser] CDP falló ({str(e)[:80]}), cayendo a launch")

    PROFILE_DIR.mkdir(exist_ok=True)

    # Mínimo de args: Chrome real (channel='chrome') marca como "no admitidos"
    # casi todos los flags de Chromium para automation. La invisibilidad la da
    # `ignore_default_args` (saca --enable-automation) + playwright-stealth.
    args = [
        "--no-first-run",
        "--no-default-browser-check",
    ]

    base_kwargs = dict(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        viewport={"width": 1366, "height": 850},
        locale="es-PE",
        timezone_id="America/Lima",
        args=args,
        # Quitar args que disparan el banner de "command-line flag no admitida"
        # de Chrome real (--no-sandbox) y el marker de automatización.
        ignore_default_args=[
            "--enable-automation",
            "--no-sandbox",
            "--disable-component-extensions-with-background-pages",
            "--disable-default-apps",
        ],
    )

    context = None
    if use_chrome:
        try:
            # Con channel='chrome' NO forzamos user_agent — Chrome real envía
            # el suyo, que coincide con su versión actual y CSS/scripts cargan.
            # Si imponemos un UA distinto, LinkedIn sirve una página degradada.
            context = pw.chromium.launch_persistent_context(
                channel="chrome",
                **base_kwargs,
            )
            print("[browser] usando Chrome del sistema (channel='chrome')")
        except Exception as e:
            print(f"[browser] Chrome no disponible ({str(e)[:80]}), cayendo a Chromium")
            context = None

    if context is None:
        # Para Chromium sí seteamos UA realista (sino delata "HeadlessChrome")
        context = pw.chromium.launch_persistent_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            **base_kwargs,
        )
        print("[browser] usando Chromium de Playwright")

    # Stealth — sólo si NR_STEALTH=1. Por default OFF porque rompe el renderer
    # de LinkedIn (CSS no carga). Activalo para Cloudflare Turnstile (HiringRoom).
    if HAS_STEALTH and ENABLE_STEALTH:
        cfg = StealthConfig(navigator_languages=False)

        def _apply_stealth(pg):
            try:
                stealth_sync(pg, cfg)
            except Exception as e:
                print(f"[browser] stealth_sync error: {str(e)[:60]}")

        for pg in context.pages:
            _apply_stealth(pg)
        context.on("page", _apply_stealth)
        print("[browser] playwright-stealth ACTIVO (NR_STEALTH=1)")
    else:
        print("[browser] stealth desactivado (export NR_STEALTH=1 para activar)")

    # Patches mínimos — sólo lo más leve, no debería romper nada
    context.add_init_script(EXTRA_STEALTH_SCRIPT)

    return pw, context
