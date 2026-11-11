"""Génère report.md depuis desk.db.  Usage : python3 report.py"""
import sqlite3, os, json, datetime
B = os.path.abspath(os.environ.get("MEMEDESK_DATA") or os.path.dirname(os.path.abspath(__file__)))
c = sqlite3.connect(os.path.join(B, "desk.db")); c.row_factory = sqlite3.Row
one = lambda q, a=(): c.execute(q, a).fetchone()[0]
cy = c.execute("SELECT MIN(ts), MAX(ts), COUNT(*) FROM cycles").fetchone()
L = [f"# Desk memecoins Solana — rapport (PAPIER)", "", f"Généré le {datetime.datetime.now().astimezone():%Y-%m-%d %H:%M} (heure de Paris)", "",
     f"- Cycles : {cy[2]} (de {cy[0]} à {cy[1]})",
     f"- Candidats scannés (Scout, tokens distincts) : {one('SELECT COUNT(DISTINCT mint) FROM candidates')} ({one('SELECT COUNT(*) FROM candidates')} observations)",
     f"- Tokens éliminés (Filter, distincts) : {one('SELECT COUNT(DISTINCT mint) FROM kills')} ({one('SELECT COUNT(*) FROM kills')} lignes de kill)",
     f"- Notés par l'Analyst : {one('SELECT COUNT(DISTINCT mint) FROM scores')} tokens ; passés (≥ 70) : {one('SELECT COUNT(DISTINCT mint) FROM scores WHERE passed=1')}", ""]
L += ["## Éliminations par motif", "", "| Motif | Tokens distincts | Occurrences |", "|---|---:|---:|"]
for r in c.execute("SELECT reason, COUNT(DISTINCT mint), COUNT(*) FROM kills GROUP BY reason ORDER BY 2 DESC"):
    L.append(f"| {r[0]} | {r[1]} | {r[2]} |")
closed = c.execute("SELECT * FROM positions WHERE status='closed' ORDER BY id").fetchall()
opn = c.execute("SELECT * FROM positions WHERE status='open' ORDER BY id").fetchall()
wins = [p for p in closed if p["pnl_usd"] > 0]
eq = c.execute("SELECT equity FROM equity ORDER BY rowid DESC LIMIT 1").fetchone()
eqv = eq[0] if eq else 10000.0
mx = one("SELECT MAX(equity) FROM equity") or 10000; mn = one("SELECT MIN(equity) FROM equity") or 10000
L += ["", "## Trades (papier, capital virtuel 10 000 $)", "",
      f"- Trades : {len(closed) + len(opn)} (clôturés {len(closed)}, ouverts {len(opn)})",
      f"- Taux de réussite : {len(wins)/len(closed)*100:.1f} %" if closed else "- Taux de réussite : n/a (aucun trade clôturé)",
      f"- PnL réalisé : {sum(p['pnl_usd'] for p in closed):+.2f} $",
      f"- Equity actuelle : {eqv:,.2f} $ ({(eqv/10000-1)*100:+.2f} %) — max {mx:,.2f} $, min {mn:,.2f} $", ""]
if closed:
    L += ["| # | Token | Entrée | Sortie | Motif | PnL $ | PnL % |", "|---|---|---|---|---|---:|---:|"]
    for p in closed:
        L.append(f"| {p['id']} | {p['symbol']} | {p['entry_ts']} @ {p['entry_price']:.8g} | {p['exit_ts']} @ {p['exit_price']:.8g} | {p['exit_reason']} | {p['pnl_usd']:+.2f} | {p['pnl_pct']:+.1f} |")
L += ["", "## Positions ouvertes", ""]
if opn:
    L += ["| # | Token | Entrée | Dernier | Stop | Trailing | PnL latent $ |", "|---|---|---|---|---|---|---:|"]
    for p in opn:
        lp = p["last_price"] or p["entry_price"]
        L.append(f"| {p['id']} | {p['symbol']} | {p['entry_price']:.8g} | {lp:.8g} | {p['stop_price']:.8g} | {'actif' if p['trail_active'] else 'non'} | {lp*p['qty']-p['cost_usd']:+.2f} |")
else:
    L.append("Aucune.")
L += ["", "## Meilleurs scores Analyst", "", "| Token | Score | Composantes |", "|---|---:|---|"]
for r in c.execute("SELECT symbol, MAX(score) s, components FROM scores GROUP BY mint ORDER BY s DESC LIMIT 15"):
    comp = json.loads(r[2]); L.append(f"| {r[0]} | {r[1]} | " + ", ".join(f"{k} {v}" for k, v in comp.items() if k != "holder_note") + " |")
open(os.path.join(B, "report.md"), "w").write("\n".join(L) + "\n")
print(os.path.join(B, "report.md"))
