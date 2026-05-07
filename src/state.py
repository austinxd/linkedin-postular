import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent.parent / "applications.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS applied (
            source TEXT,
            job_id TEXT,
            destination TEXT,
            title TEXT,
            company TEXT,
            url TEXT,
            status TEXT,
            applied_at TEXT,
            PRIMARY KEY (source, job_id)
        )
        """
    )
    conn.commit()
    return conn


def already_seen(conn, source, job_id):
    """True si la oferta ya fue procesada (aplicada o saltada)."""
    cur = conn.execute(
        "SELECT 1 FROM applied WHERE source=? AND job_id=?",
        (source, job_id),
    )
    return cur.fetchone() is not None


def record(conn, source, job_id, destination, title, company, url, status):
    conn.execute(
        "INSERT OR REPLACE INTO applied VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            source,
            job_id,
            destination,
            title,
            company,
            url,
            status,
            datetime.now().isoformat(),
        ),
    )
    conn.commit()


def count_today_applied(conn):
    """Total aplicadas hoy (todas las plataformas destino)."""
    today = datetime.now().strftime("%Y-%m-%d")
    cur = conn.execute(
        "SELECT COUNT(*) FROM applied WHERE status='applied' AND applied_at LIKE ?",
        (f"{today}%",),
    )
    return cur.fetchone()[0]
