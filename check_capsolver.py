#!/usr/bin/env python3
"""Chequea balance Capsolver y prueba resolver un Turnstile real."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src import capsolver

if not os.environ.get("CAPSOLVER_API_KEY"):
    print("⚠ CAPSOLVER_API_KEY no seteada en .env")
    print("  1. Creá cuenta en https://www.capsolver.com")
    print("  2. Recargá $1-5 USD")
    print("  3. Copia el clientKey y agregalo a .env como:")
    print("     CAPSOLVER_API_KEY=CAP-xxx...")
    sys.exit(1)

key = os.environ.get("CAPSOLVER_API_KEY", "")
print(f"  Key presente: {key[:8]}...{key[-4:] if len(key) > 12 else ''} (len={len(key)})")

balance = capsolver.get_balance(verbose=True)
if balance is None:
    print("⚠ No pude consultar balance.")
    print("  Causas posibles:")
    print("    - Key inválida o sin formato 'CAP-...'")
    print("    - Saldo en $0.00 (Capsolver puede rechazar consultas)")
    print("    - Network bloqueando api.capsolver.com")
    sys.exit(1)

print(f"✓ Capsolver balance: ${balance:.4f} USD")
print(f"  Eso alcanza para ~{int(balance / 0.001)} captchas Turnstile.")

if "--test" in sys.argv:
    print("\n→ Probando resolver Turnstile en proempresa.hiringroom.com...")
    token = capsolver.solve_turnstile(
        "https://proempresa.hiringroom.com/jobs/get_vacancy/69f0d2114e38ce55b989d68e",
        "0x4AAAAAAA0jh6dH7_Z2AOon",
    )
    if token:
        print(f"  ✓ Token recibido (len={len(token)}): {token[:40]}...")
    else:
        print("  ⚠ No se obtuvo token")
