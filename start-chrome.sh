#!/bin/bash
# Lanza una NUEVA instancia de Chrome (separada de la que ya tengas abierta)
# con debugging port y profile dedicado. Usa `open -na` para forzar new
# instance y para que herede permisos TCC de macOS (FIDO/Bluetooth) que
# Cloudflare Turnstile chequea.
#
# Después corré en OTRA terminal:
#   NR_CDP_URL=http://localhost:9222 python main.py -k '...' -l '...'

PROFILE_DIR="$(cd "$(dirname "$0")" && pwd)/browser-profile-cdp"
mkdir -p "$PROFILE_DIR"

# Si ya hay un Chrome con port 9222, no relanzar
if lsof -i :9222 -sTCP:LISTEN > /dev/null 2>&1; then
    echo "→ Chrome ya está escuchando en port 9222. Usa esa instancia."
    echo "  En OTRA terminal: NR_CDP_URL=http://localhost:9222 python main.py ..."
    exit 0
fi

echo "→ Lanzando NUEVA instancia de Chrome (no afecta tu Chrome normal)"
echo "  Profile: $PROFILE_DIR"
echo "  Debugging port: 9222"
echo ""

# `-n` fuerza nueva instancia incluso si Chrome ya está corriendo.
# `-a` lanza vía LaunchServices (igual que Finder → permisos TCC completos).
# Stdout/stderr al log para no spammear la terminal.
LOG_FILE="$(cd "$(dirname "$0")" && pwd)/logs/chrome-cdp.log"
mkdir -p "$(dirname "$LOG_FILE")"

open -na "Google Chrome" \
    --stdout "$LOG_FILE" \
    --stderr "$LOG_FILE" \
    --args \
    --remote-debugging-port=9222 \
    --user-data-dir="$PROFILE_DIR" \
    --no-first-run \
    --no-default-browser-check

# Esperar a que el port esté listo (máx 8s)
for i in 1 2 3 4 5 6 7 8; do
    sleep 1
    if lsof -i :9222 -sTCP:LISTEN > /dev/null 2>&1; then
        echo "✓ Chrome corriendo con CDP en port 9222 (PID: $(lsof -ti :9222))"
        echo ""
        echo "  Ahora en OTRA terminal corré:"
        echo "    NR_CDP_URL=http://localhost:9222 python main.py -k 'Jefe de Finanzas' -l 'Lima, Peru'"
        echo ""
        echo "  Log de Chrome: $LOG_FILE"
        exit 0
    fi
done

echo "⚠ Chrome no levantó el port 9222 después de 8s."
echo "  Posibles causas:"
echo "    - Chrome se cerró (revisá $LOG_FILE)"
echo "    - Otro proceso usa el port"
echo "  Probá:"
echo "    pkill -f 'Google Chrome'    # cerrá TODOS los Chrome (cuidado)"
echo "    ./start-chrome.sh           # reintentá"
exit 1
