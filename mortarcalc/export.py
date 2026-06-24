"""Export FM-fiche naar HTML/PDF.

HTML wordt door QTextDocument naar PDF gerenderd via QPrinter (PdfFormat).
Geen externe deps nodig (PySide6 levert QtPrintSupport mee in pyside6-addons).
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .battery import Peloton
from .firemission import FireMission, PieceSolution


def fm_to_html(fm: FireMission, solutions: Iterable[PieceSolution], peloton: Peloton | None = None) -> str:
    """Genereer een A4-fiche-HTML voor één fire mission."""
    rows = ""
    sols = list(solutions)
    for s in sols:
        fired = fm.rounds_fired.get(s.piece, 0)
        remaining = fm.rounds_remaining(s.piece)
        rem_style = ' style="color:red"' if remaining < 0 else ''
        rows += (
            f"<tr><td>{s.piece}</td><td>{s.charge}</td>"
            f"<td>{s.elevation_mils:.0f}</td>"
            f"<td>{s.azimuth_mils:.0f}</td>"
            f"<td>{s.deflection_mils:.0f}</td>"
            f"<td>{s.tof_s:.1f}</td>"
            f"<td>{s.range_m:.0f}</td>"
            f"<td>{fired}</td>"
            f"<td{rem_style}>{remaining}</td></tr>"
        )

    tgt = fm.target_position.to_mgrs() if fm.target_position else "—"
    h = fm.target_position.altitude_m if fm.target_position else 0

    ammo_block = ""
    if peloton is not None:
        ammo_rows = ""
        for p in peloton.pieces:
            he = peloton.ammo_of(p.name, fm.shell)
            ammo_rows += f"<tr><td>{p.name}</td><td>{he}</td></tr>"
        if ammo_rows:
            ammo_block = f"""
            <h3>Munitievoorraad ({fm.shell})</h3>
            <table><tr><th>Stuk</th><th>Resterend</th></tr>{ammo_rows}</table>
            """

    log_html = "<br>".join(line for line in fm.log) if fm.log else "<i>geen entries</i>"

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  body {{ font-family: sans-serif; font-size: 11pt; }}
  h1 {{ font-size: 16pt; margin: 0 0 4px 0; }}
  h2 {{ font-size: 12pt; margin: 14px 0 4px 0; border-bottom: 1px solid #888; }}
  h3 {{ font-size: 11pt; margin: 10px 0 2px 0; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 4px; }}
  th, td {{ border: 1px solid #888; padding: 3px 6px; text-align: left; font-size: 10pt; }}
  th {{ background: #eee; }}
  .kv {{ width: 100%; }}
  .kv td {{ border: none; padding: 2px 8px 2px 0; }}
  .kv td.l {{ width: 22%; color: #555; }}
</style></head><body>

<h1>Fire Mission Fiche — {fm.id}</h1>
<div style="color:#666; font-family: monospace;">{fm.call_for_fire_brief()}</div>

<h2>1. Waarnemer (FO)</h2>
<table class="kv">
 <tr><td class="l">Call-sign</td><td>{fm.observer.call_sign}</td></tr>
 <tr><td class="l">Positie</td><td>{fm.observer.position.to_mgrs()} @ {fm.observer.position.altitude_m:.0f} m</td></tr>
</table>

<h2>2. Doel</h2>
<table class="kv">
 <tr><td class="l">Locatie</td><td>{tgt} @ {h:.0f} m</td></tr>
 <tr><td class="l">Beschrijving</td><td>{fm.target_description or '—'}</td></tr>
 <tr><td class="l">Type</td><td>{fm.target_type.value}</td></tr>
</table>

<h2>3. Method of Engagement</h2>
<table class="kv">
 <tr><td class="l">Munitie / Fuze</td><td>{fm.shell} / {fm.fuze.value.upper()}</td></tr>
 <tr><td class="l">Method of Fire</td><td>{fm.method_of_fire.value}</td></tr>
 <tr><td class="l">Sheaf</td><td>{fm.sheaf.value}</td></tr>
 <tr><td class="l">Rondes / stuk</td><td>{fm.rounds_per_piece}</td></tr>
 <tr><td class="l">Control</td><td>{fm.control.value}</td></tr>
</table>

<h2>4. Vuurelementen + Munitie</h2>
<table>
 <tr><th>Stuk</th><th>Lading</th><th>Elev (str)</th><th>Azimut (str)</th>
     <th>Defl vs PDF</th><th>TOF (s)</th><th>Dracht (m)</th>
     <th>Afgevuurd</th><th>Restant</th></tr>
 {rows}
</table>

{ammo_block}

<h2>5. Mission Log</h2>
<div style="font-family: monospace; font-size: 9pt;">{log_html}</div>

<div style="margin-top: 20px; font-size: 8pt; color:#888;">
  MortarCalc — groep {fm.group_name} — status {fm.state.value} — ontvangen {fm.received_at.isoformat(timespec='seconds')}
</div>
</body></html>"""


def export_fm_to_pdf(
    path: str | Path,
    fm: FireMission,
    solutions: Iterable[PieceSolution],
    peloton: Peloton | None = None,
) -> None:
    """Render FM-fiche naar PDF via QTextDocument + QPrinter (PdfFormat)."""
    # Imports binnen functie zodat module zonder Qt-context geïmporteerd kan worden
    from PyQt6.QtGui import QTextDocument, QPageLayout, QPageSize
    from PyQt6.QtCore import QMarginsF
    from PyQt6.QtPrintSupport import QPrinter

    html = fm_to_html(fm, solutions, peloton)
    doc = QTextDocument()
    doc.setHtml(html)

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(path))
    layout = QPageLayout(
        QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
        QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter,
    )
    printer.setPageLayout(layout)
    doc.print(printer)
