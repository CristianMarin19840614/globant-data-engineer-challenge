"""Generate the optional offline dashboard using the API's SQL definitions.

Run: python dashboard.py [--year 2021] [--db data/challenge.db] [--output dashboard.html]
Requires the project's requirements.txt. No server or extra packages are needed.
The database is opened read-only; missing data is never created or loaded here.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
from html import escape
from pathlib import Path
import sqlite3

from api import HIRES_BY_QUARTER, DEPARTMENTS_ABOVE_AVERAGE
from database import DB_PATH


def read_data(db_path, year):
    """Read a consistent snapshot and reconcile the two API query results."""
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('BEGIN')
        quarters = [dict(r) for r in conn.execute(HIRES_BY_QUARTER, (str(year),))]
        above = [dict(r) for r in conn.execute(DEPARTMENTS_ABOVE_AVERAGE, (str(year),))]
        total = conn.execute("SELECT COUNT(*) FROM hired_employees WHERE strftime('%Y', datetime) = ?", (str(year),)).fetchone()[0]
        active = conn.execute("SELECT COUNT(DISTINCT department_id) FROM hired_employees WHERE strftime('%Y', datetime) = ?", (str(year),)).fetchone()[0]
        catalog = conn.execute('SELECT COUNT(*) FROM departments').fetchone()[0]
    totals = [sum(r[q] for r in quarters) for q in ('Q1', 'Q2', 'Q3', 'Q4')]
    if sum(totals) != total:
        raise ValueError('Quarter totals do not reconcile with hired_employees. Check foreign keys.')
    return quarters, above, totals, total, active, catalog


def bars(labels, values, title, mean=None):
    """Accessible horizontal SVG bars, always starting at zero."""
    width, left, plot = 900, 245, 565
    height = 65 + 43 * len(labels)
    maximum = max([1, *values, mean or 0]) * 1.15
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title, quote=True)}">', f'<title>{escape(title)}</title>']
    for i, (label, value) in enumerate(zip(labels, values)):
        y = 35 + i * 43
        size = value / maximum * plot
        parts.append(f'<text x="{left-12}" y="{y+19}" text-anchor="end">{escape(str(label))}</text><rect x="{left}" y="{y}" width="{size:.2f}" height="27" rx="3" fill="#4f46e5"/><text x="{left+size+9:.2f}" y="{y+19}">{value:,}</text>')
    if mean is not None:
        x = left + mean / maximum * plot
        parts.append(f'<line x1="{x:.2f}" x2="{x:.2f}" y1="25" y2="{height-20}" stroke="#b45309" stroke-width="2" stroke-dasharray="5 4"/><text x="{x:.2f}" y="17" text-anchor="middle" fill="#92400e">Promedio: {mean:.2f}</text>')
    parts.append(f'<text x="{left}" y="{height-2}">0</text><text x="{left+plot}" y="{height-2}" text-anchor="end">Contrataciones</text></svg>')
    return ''.join(parts)


def table(rows, columns):
    header = ''.join(f'<th scope="col">{escape(c)}</th>' for c in columns)
    body = ''.join('<tr>' + ''.join(f'<td>{escape(str(row[c]))}</td>' for c in columns) + '</tr>' for row in rows)
    return f'<div class="scroll"><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>'


def render(db_path, year, data):
    quarters, above, totals, total, active, catalog = data
    mean = total / active if active else None
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    q_chart = bars(['Q1', 'Q2', 'Q3', 'Q4'], totals, 'Contrataciones por trimestre')
    a_chart = bars([r['department'] for r in above], [r['hired'] for r in above], 'Departamentos sobre el promedio', mean) if above else '<p>No hay departamentos sobre el promedio.</p>'
    mean_text = f'{mean:.2f}' if mean is not None else 'Sin datos'
    return f'''<!doctype html>
<html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Globant · Contrataciones {year}</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#f5f6fa;color:#18202f;font:16px/1.55 system-ui,sans-serif}}main{{max-width:1160px;margin:auto;padding:35px 30px}}h1{{font-size:36px;letter-spacing:-1px;margin:8px 0}}h2{{font-size:24px;margin:0 0 8px}}p{{margin:8px 0 18px}}.eyebrow{{color:#4f46e5;font-weight:700;letter-spacing:2px}}.metrics{{display:flex;gap:40px;flex-wrap:wrap;margin:26px 0}}.metrics strong{{display:block;font-size:32px}}section{{background:white;padding:25px;margin:22px 0;border:1px solid #e0e3ec;border-radius:12px}}svg{{width:100%;height:auto;display:block}}svg text{{font:15px system-ui,sans-serif}}small,.muted{{color:#596375}}table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{padding:8px 12px;text-align:left;border-bottom:1px solid #e1e4ec}}th{{background:#eef0f8;position:sticky;top:0}}td:nth-child(n+3){{text-align:right}}.scroll{{overflow:auto;max-height:460px}}summary{{cursor:pointer;font-weight:600;margin:18px 0}}code{{background:#edf0f7;padding:2px 5px}}@media(max-width:600px){{main{{padding:20px 12px}}section{{padding:15px}}h1{{font-size:29px}}.metrics{{gap:18px}}svg{{min-width:680px}}.chart{{overflow:auto}}}}@media print{{.scroll{{max-height:none}}section{{break-inside:avoid}}}}
</style><main>
<div class="eyebrow">GLOBANT / DATA ENGINEER CHALLENGE</div>
<h1>Contrataciones {year}</h1>
<p class="muted">Registros válidos de SQLite. Consultas del Challenge #2, con el mismo SQL de la API.</p>
<div class="metrics"><div><strong>{total:,}</strong>Contrataciones del año</div><div><strong>{active} / {catalog}</strong>Departamentos con contratación</div><div><strong>{mean_text}</strong>Promedio por departamento activo</div></div>
{'<p>No hay contrataciones para este año. Las tablas están vacías.</p>' if not total else ''}
<section><h2>1. Contrataciones por trimestre</h2><p>Vista agregada de todos los puestos y departamentos. El detalle conserva department, job y Q1-Q4, en orden alfabético.</p><div class="chart">{q_chart}</div>
<details><summary>Detalle por departamento y puesto ({len(quarters):,} combinaciones)</summary>{table(quarters, ['department','job','Q1','Q2','Q3','Q4'])}</details>
<small>Fuente: api.py / HIRES_BY_QUARTER. hired_employees + departments + jobs.</small></section>
<section><h2>2. Departamentos sobre el promedio</h2><p>{len(above)} departamentos con contrataciones estrictamente mayores que {mean_text}. Orden: hired DESC.</p><div class="chart">{a_chart}</div>
{table(above, ['id','department','hired'])}<p class="muted">El promedio usa los {active} departamentos que contrataron durante {year}, igual que la API. El catálogo contiene {catalog} departamentos. Los departamentos sin contratación no entran en este denominador.</p>
<small>Fuente: api.py / DEPARTMENTS_ABOVE_AVERAGE. hired_employees + departments.</small></section>
<footer><p>Base: <code>{escape(Path(db_path).name)}</code> · Año: {year} · Generado: {stamp}</p><p class="muted">Instantánea local, sin actualización automática. Regenerar con <code>python dashboard.py --year {year}</code>. No incluye registros rechazados ni datos personales de empleados. Sin JavaScript, servidor ni conexión a Internet.</p></footer>
</main></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--year', type=int, default=2021)
    parser.add_argument('--db', type=Path, default=DB_PATH)
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('dashboard.html'))
    args = parser.parse_args()
    if not 1 <= args.year <= 9999:
        parser.error('--year must be between 1 and 9999')
    if args.output.resolve() == args.db.resolve():
        parser.error('Output must not overwrite the database')
    try:
        data = read_data(args.db, args.year)
        args.output.write_text(render(args.db, args.year, data), encoding='utf-8')
    except (sqlite3.Error, OSError, ValueError) as error:
        parser.exit(1, f'Dashboard error: {error}. Check --db and load the CSVs with load_csv.py first.\n')
    print(f'Dashboard: {args.output.resolve()}')
    print(f'{args.year}: {data[3]} hires; quarters={data[2]}; {len(data[1])} departments above average.')


if __name__ == '__main__':
    main()
