"""Cliente LLM para responder killer questions de los formularios.

Soporta OpenAI (default, ChatGPT) y Anthropic (Claude) como fallback.
Si no hay ninguna API key configurada, devuelve None y el handler caerá
a input manual del usuario.

Variables de entorno:
  OPENAI_API_KEY     → usa gpt-4o-mini (default si está set)
  ANTHROPIC_API_KEY  → usa claude-haiku-4-5 (fallback)

Costo aproximado: $0.0001 por pregunta con gpt-4o-mini.
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent
PROMPT_PATH = ROOT / "prompts" / "killer_questions.md"

# Cargar .env del proyecto si existe (solo una vez al importar)
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

OPENAI_MODEL = "gpt-4o-mini"
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"


def answer_question(question: str, profile: dict, options: list = None) -> str | None:
    """Devuelve la respuesta a una killer question. None si no hay LLM.

    Si `options` es una lista (pregunta tipo radio/multiple choice), instruye al
    LLM a devolver EXACTAMENTE el texto de UNA de las opciones provistas.
    """
    if not question or not question.strip():
        return ""

    prompt = build_prompt(question, profile)

    if options:
        opts = "\n".join(f"  - {o}" for o in options if o)
        prompt = (
            prompt
            + "\n\n## OPCIONES DISPONIBLES (elige UNA, devolvé SOLO su texto exacto)\n"
            + opts
            + "\n\nReglas extra para esta pregunta:\n"
            + "- Devuelve UNA sola opción, copiada literal de la lista de arriba.\n"
            + "- Sin comillas, sin prefijos, sin explicación, sin opciones extra.\n"
            + "- Si dudas, elige la más optimista pero verdadera según el perfil.\n"
        )

    if os.environ.get("OPENAI_API_KEY"):
        return _call_openai(prompt)
    if os.environ.get("ANTHROPIC_API_KEY"):
        return _call_anthropic(prompt)
    return None


def build_prompt(question: str, profile: dict) -> str:
    if not PROMPT_PATH.exists():
        # Prompt mínimo de fallback
        return (
            f"Responde como Alex Abad usando estos datos:\n"
            f"{json.dumps(profile, ensure_ascii=False, indent=2)}\n\n"
            f"Pregunta: {question}\n\n"
            f"Respuesta corta y profesional (solo texto, sin prefijos):"
        )
    template = PROMPT_PATH.read_text(encoding="utf-8")
    profile_data = json.dumps(profile, ensure_ascii=False, indent=2)
    return template.replace("{profile_data}", profile_data).replace("{question}", question)


def _call_openai(prompt: str) -> str | None:
    try:
        from openai import OpenAI
    except ImportError:
        print("        ⚠ openai SDK no instalado. pip install openai")
        return None
    try:
        client = OpenAI()
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=400,
        )
        text = (resp.choices[0].message.content or "").strip()
        return _clean_answer(text)
    except Exception as e:
        print(f"        ⚠ OpenAI error: {str(e)[:80]}")
        return None


def _call_anthropic(prompt: str) -> str | None:
    try:
        import anthropic
    except ImportError:
        print("        ⚠ anthropic SDK no instalado. pip install anthropic")
        return None
    try:
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        text = (msg.content[0].text if msg.content else "").strip()
        return _clean_answer(text)
    except Exception as e:
        print(f"        ⚠ Anthropic error: {str(e)[:80]}")
        return None


def _clean_answer(text: str) -> str:
    """Limpia prefijos comunes que el LLM a veces agrega a pesar de las reglas."""
    text = text.strip().strip('"').strip("'")
    for prefix in (
        "Respuesta:", "respuesta:", "RESPUESTA:",
        "Mi respuesta:", "Hola,", "Hola.",
    ):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return text
