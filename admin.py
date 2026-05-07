"""Genera un dashboard HTML estático con todas las postulaciones registradas.

Uso:
    python admin.py            # genera admin.html y lo abre en el navegador
    python admin.py --no-open  # solo genera el archivo

El HTML resultante se queda como `admin.html` en la raíz del proyecto.
Se puede regenerar cuantas veces quieras — siempre lee los JSONs más nuevos.
"""
import json
import sys
import webbrowser
from collections import Counter
from datetime import datetime
from pathlib import Path

from src import applog

ROOT = Path(__file__).parent
OUT = ROOT / "admin.html"


def stats(records):
    today = datetime.now().strftime("%Y-%m-%d")
    by_status = Counter(r.get("status", "unknown") for r in records)
    by_destination = Counter(r.get("destination", "unknown") for r in records)
    by_date = Counter(r.get("date", "") for r in records)
    today_count = sum(1 for r in records if r.get("date") == today and r.get("status") == "applied")
    pending_email = sum(1 for r in records if r.get("email_confirmation_required"))
    return {
        "total": len(records),
        "applied": by_status.get("applied", 0),
        "skipped": by_status.get("skipped", 0),
        "today": today_count,
        "pending_email": pending_email,
        "by_destination": dict(by_destination.most_common()),
        "by_date": dict(by_date.most_common(14)),
    }


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8" />
<title>Panel — Postulaciones</title>
<style>
  * { box-sizing: border-box; }
  html { -webkit-text-size-adjust: 100%; }
  body {
    font-family: "Inter", "Segoe UI Variable", "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, system-ui, "Helvetica Neue", Arial, sans-serif;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    text-rendering: optimizeLegibility;
    margin: 0; padding: 24px; background: #f4f6f8; color: #1d2530;
    font-size: 14px;
    line-height: 1.45;
  }
  h1 { margin: 0 0 24px; font-size: 24px; font-weight: 600; letter-spacing: -0.01em; }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 24px; }
  .card {
    background: #fff; border-radius: 10px; padding: 18px 20px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.03);
    border: 1px solid #e8edf2;
  }
  .card .num { font-size: 30px; font-weight: 700; color: #2563eb; line-height: 1.1; font-variant-numeric: tabular-nums; }
  .card .label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: #64748b; margin-top: 4px; font-weight: 600; }
  .filters { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
  .filter {
    background: #fff; border: 1px solid #cbd5e1; border-radius: 6px;
    padding: 7px 12px; font-size: 13px; cursor: pointer;
    font-family: inherit; color: #334155;
    transition: all 0.15s ease;
  }
  .filter:hover { border-color: #94a3b8; background: #f8fafc; }
  .filter.active { background: #2563eb; color: #fff; border-color: #2563eb; }
  table {
    width: 100%; background: #fff; border-radius: 10px; overflow: hidden;
    border-collapse: separate; border-spacing: 0;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.03);
    border: 1px solid #e8edf2;
  }
  th, td { padding: 12px 16px; text-align: left; font-size: 13px; border-bottom: 1px solid #eef1f5; vertical-align: top; }
  th { background: #f8fafc; font-weight: 600; color: #475569; text-transform: uppercase; font-size: 11px; letter-spacing: 0.06em; }
  tr:last-child td { border-bottom: none; }
  tr.row { cursor: pointer; transition: background 0.1s ease; }
  tr.row:hover { background: #f8fafc; }
  .badge { display: inline-block; padding: 3px 9px; border-radius: 999px; font-size: 11px; font-weight: 600; letter-spacing: 0.02em; }
  .badge.applied { background: #dcfce7; color: #15803d; }
  .badge.skipped { background: #f1f5f9; color: #64748b; }
  .badge.failed  { background: #fee2e2; color: #b91c1c; }
  .destination { font-family: ui-monospace, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace; font-size: 11px; color: #475569; }
  .pending-email { color: #b45309; font-size: 11px; font-weight: 500; }
  .detail-row td { background: #f8fafc; padding: 16px 24px; }
  .detail-row .qa { background: #fff; padding: 14px 16px; border-radius: 8px; margin-bottom: 8px; border-left: 3px solid #2563eb; box-shadow: 0 1px 2px rgba(0,0,0,0.03); }
  .detail-row .qa .q { font-weight: 600; color: #1d2530; margin-bottom: 6px; font-size: 13px; }
  .detail-row .qa .a { color: #475569; font-size: 13px; white-space: pre-wrap; line-height: 1.55; }
  .detail-row .qa .src { font-size: 10px; color: #94a3b8; text-transform: uppercase; margin-top: 6px; letter-spacing: 0.05em; font-weight: 600; }
  .empty { text-align: center; padding: 60px; color: #94a3b8; }
  a { color: #2563eb; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .ts { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 11px; color: #64748b; font-variant-numeric: tabular-nums; }
  .meta { font-size: 11px; color: #94a3b8; margin-top: 4px; }
</style>
</head>
<body>
<h1>Panel de postulaciones <span style="color:#94a3b8;font-weight:400;font-size:13px;">(generado {generated_at})</span></h1>

<div class="stats">
  <div class="card"><div class="num">{total}</div><div class="label">Total</div></div>
  <div class="card"><div class="num">{applied}</div><div class="label">Aplicadas</div></div>
  <div class="card"><div class="num">{skipped}</div><div class="label">Saltadas</div></div>
  <div class="card"><div class="num">{today}</div><div class="label">Hoy</div></div>
  <div class="card"><div class="num">{pending_email}</div><div class="label">Pendientes email</div></div>
</div>

<div class="filters">
  <button class="filter active" data-filter="all">Todos</button>
  <button class="filter" data-filter="applied">Aplicadas</button>
  <button class="filter" data-filter="skipped">Saltadas</button>
  {dest_filters}
</div>

<table id="apps">
  <thead>
    <tr>
      <th>Fecha</th>
      <th>Puesto / Empresa</th>
      <th>Destino</th>
      <th>Estado</th>
      <th>Q&amp;A</th>
    </tr>
  </thead>
  <tbody>
    {rows}
  </tbody>
</table>

<script>
const filters = document.querySelectorAll('.filter');
filters.forEach(f => f.addEventListener('click', () => {{
  filters.forEach(x => x.classList.remove('active'));
  f.classList.add('active');
  const v = f.dataset.filter;
  document.querySelectorAll('tr.row').forEach(r => {{
    if (v === 'all') r.style.display = '';
    else if (v === 'applied' || v === 'skipped') r.style.display = (r.dataset.status === v) ? '' : 'none';
    else r.style.display = (r.dataset.destination === v) ? '' : 'none';
    // Hide expanded detail when row is hidden
    const detail = r.nextElementSibling;
    if (detail && detail.classList.contains('detail-row')) {{
      detail.style.display = r.style.display === 'none' ? 'none' : detail.dataset.expanded === '1' ? '' : 'none';
    }}
  }});
}}));

document.querySelectorAll('tr.row').forEach(r => {{
  r.addEventListener('click', () => {{
    const detail = r.nextElementSibling;
    if (!detail || !detail.classList.contains('detail-row')) return;
    const isOpen = detail.dataset.expanded === '1';
    detail.dataset.expanded = isOpen ? '0' : '1';
    detail.style.display = isOpen ? 'none' : '';
  }});
}});
</script>
</body>
</html>
"""


def render_row(idx, r):
    status = r.get("status", "unknown")
    dest = r.get("destination", "unknown")
    company = (r.get("company") or "?").strip()
    title = (r.get("title") or "?").strip()
    ts = r.get("timestamp", "")
    # Hora formateada
    short_ts = ts.replace("T", " ")[:16] if ts else "-"
    qa_count = len(r.get("killer_questions") or [])
    pending_email = r.get("email_confirmation_required")

    pending_html = ' <span class="pending-email">📩 confirmar email</span>' if pending_email else ""
    qa_html = f"{qa_count} pregunta{'s' if qa_count != 1 else ''}" if qa_count else "—"

    source_url = r.get("source_url") or "#"
    dest_url = r.get("dest_url") or ""

    detail = render_detail(r)

    return f"""
    <tr class="row" data-status="{status}" data-destination="{dest}">
      <td class="ts">{short_ts}</td>
      <td>
        <div><strong>{esc(title)}</strong></div>
        <div class="meta">{esc(company)}{pending_html}</div>
      </td>
      <td><span class="destination">{esc(dest)}</span></td>
      <td><span class="badge {status}">{status}</span></td>
      <td>{qa_html}</td>
    </tr>
    <tr class="detail-row" data-expanded="0" style="display:none;">
      <td colspan="5">{detail}</td>
    </tr>
    """


def render_detail(r):
    qas = r.get("killer_questions") or []
    notes = r.get("notes") or []
    errors = r.get("errors") or []
    source_url = r.get("source_url") or ""
    dest_url = r.get("dest_url") or ""
    parts = []
    if source_url:
        parts.append(f'<div class="meta">Origen: <a href="{esc(source_url)}" target="_blank">{esc(source_url)[:80]}</a></div>')
    if dest_url:
        parts.append(f'<div class="meta">Destino: <a href="{esc(dest_url)}" target="_blank">{esc(dest_url)[:80]}</a></div>')
    if qas:
        parts.append("<div style='margin-top:12px;font-weight:600;font-size:13px;'>Killer Questions</div>")
        for qa in qas:
            q = esc(qa.get("question", ""))
            a = esc(qa.get("answer", ""))
            src = qa.get("source", "")
            parts.append(f'<div class="qa"><div class="q">{q}</div><div class="a">{a}</div><div class="src">{src}</div></div>')
    if notes:
        parts.append("<div style='margin-top:12px;font-weight:600;font-size:13px;'>Notas</div>")
        for n in notes:
            parts.append(f'<div class="qa">{esc(n)}</div>')
    if errors:
        parts.append("<div style='margin-top:12px;font-weight:600;font-size:13px;color:#991b1b;'>Errores</div>")
        for e in errors:
            parts.append(f'<div class="qa" style="border-left-color:#dc2626;">{esc(e)}</div>')
    if not parts:
        parts.append("<div class='meta'>(sin detalles adicionales)</div>")
    return "".join(parts)


def esc(s):
    if s is None:
        return ""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def build():
    records = applog.read_all()
    s = stats(records)
    rows = "".join(render_row(i, r) for i, r in enumerate(records)) if records else \
           "<tr><td colspan='5' class='empty'>Aún no hay postulaciones registradas.</td></tr>"
    dest_filters = "\n  ".join(
        f'<button class="filter" data-filter="{esc(d)}">{esc(d)} ({c})</button>'
        for d, c in s["by_destination"].items()
    )
    replacements = {
        "{generated_at}": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "{total}": str(s["total"]),
        "{applied}": str(s["applied"]),
        "{skipped}": str(s["skipped"]),
        "{today}": str(s["today"]),
        "{pending_email}": str(s["pending_email"]),
        "{dest_filters}": dest_filters,
        "{rows}": rows,
    }
    html = HTML_TEMPLATE
    for k, v in replacements.items():
        html = html.replace(k, v)
    OUT.write_text(html, encoding="utf-8")
    return s


def main():
    s = build()
    print(f"→ {s['total']} postulaciones registradas ({s['applied']} aplicadas, {s['skipped']} saltadas)")
    print(f"→ Dashboard: {OUT}")
    if "--no-open" not in sys.argv:
        try:
            webbrowser.open(f"file://{OUT}")
        except Exception:
            pass


if __name__ == "__main__":
    main()
