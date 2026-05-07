"""Log de postulaciones — un JSON por aplicación en logs/applications/.

Cada archivo contiene:
  - timestamp / date
  - source: "linkedin"
  - source_job_id
  - destination: "linkedin" | "pandape" | "computrabajo" | "hiringroom" | "manual:domain"
  - title / company / location
  - source_url (LinkedIn) / dest_url (form al que llegó)
  - status: "applied" | "skipped" | "failed"
  - killer_questions: [{question, answer, source: "llm"|"manual"}]
  - notes: lista de mensajes informativos
  - errors: lista de errores capturados
  - email_confirmation_required: bool (Pandapé pide confirmar por email)
"""
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
LOG_DIR = ROOT / "logs" / "applications"


def make_record(**kwargs) -> dict:
    """Crea un registro vacío con valores por defecto. Pasá lo que sepás como kwargs."""
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "source": kwargs.get("source", "linkedin"),
        "source_job_id": kwargs.get("source_job_id", ""),
        "destination": kwargs.get("destination", "unknown"),
        "title": kwargs.get("title", ""),
        "company": kwargs.get("company", ""),
        "location": kwargs.get("location", ""),
        "source_url": kwargs.get("source_url", ""),
        "dest_url": kwargs.get("dest_url", ""),
        "status": kwargs.get("status", "skipped"),
        "killer_questions": kwargs.get("killer_questions", []),
        "notes": kwargs.get("notes", []),
        "errors": kwargs.get("errors", []),
        "email_confirmation_required": kwargs.get("email_confirmation_required", False),
    }


def write(record: dict) -> Path:
    """Persiste un registro a logs/applications/{ts}-{job_id}.json"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now()
    job_id = (record.get("source_job_id") or "unknown")[:24]
    safe_job = "".join(c if c.isalnum() else "_" for c in str(job_id))
    fname = f"{ts.strftime('%Y%m%d-%H%M%S')}-{safe_job}.json"
    path = LOG_DIR / fname
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_all() -> list:
    """Lee todos los logs ordenados por timestamp descendente."""
    if not LOG_DIR.exists():
        return []
    out = []
    for p in sorted(LOG_DIR.glob("*.json"), reverse=True):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out
