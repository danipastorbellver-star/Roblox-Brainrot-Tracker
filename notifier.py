"""
notifier.py — Envía un reporte por Telegram con el top movers de una categoría.

Variables de entorno requeridas:
  TELEGRAM_TOKEN    — token del bot (de @BotFather)
  TELEGRAM_CHAT_ID  — tu chat ID (envía /start a tu bot y mira getUpdates)

Uso:
  python notifier.py brainrot            # reporte diario brainrot
  python notifier.py horror              # reporte diario horror
  python notifier.py brainrot --weekly   # reporte semanal
"""

import os
import sqlite3
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).parent

CATEGORIES = {
    "brainrot": {"label": "Brainrot", "db": ROOT / "data" / "tracker_brainrot.db"},
    "horror":   {"label": "Horror",   "db": ROOT / "data" / "tracker_horror.db"},
}


def get_top_movers(db_path: Path, period_hours: int = 24, top_n: int = 10) -> list[tuple]:
    """Devuelve (name, current, old, growth_pct) ordenado por crecimiento."""
    if not db_path.exists():
        return []
    con = sqlite3.connect(db_path)
    rows = con.execute(f"""
        WITH bounds AS (
            SELECT place_id,
                   MIN(ts) FILTER (WHERE ts >= datetime('now', '-{period_hours} hours')) AS first_ts,
                   MAX(ts) AS last_ts
            FROM snapshots
            GROUP BY place_id
            HAVING first_ts IS NOT NULL AND last_ts > first_ts
        )
        SELECT s_new.name,
               s_new.player_count AS current,
               s_old.player_count AS old,
               ROUND((s_new.player_count - s_old.player_count) * 100.0 / s_old.player_count, 1) AS growth
        FROM bounds b
        JOIN snapshots s_old ON s_old.place_id = b.place_id AND s_old.ts = b.first_ts
        JOIN snapshots s_new ON s_new.place_id = b.place_id AND s_new.ts = b.last_ts
        WHERE s_old.player_count > 500
        ORDER BY growth DESC
        LIMIT ?
    """, (top_n,)).fetchall()
    con.close()
    return rows


def emoji(growth: float) -> str:
    if growth >= 50: return "🚀"
    if growth >= 20: return "🔥"
    if growth >= 5:  return "📈"
    if growth >= -5: return "➡️"
    return "📉"


def format_report(rows: list[tuple], title: str) -> str:
    if not rows:
        return f"*{title}*\n\nSin datos suficientes todavía. Necesitas al menos 2 snapshots."
    lines = [f"🎮 *{title}*", ""]
    for name, current, old, growth in rows:
        safe_name = name.replace("*", "").replace("_", " ")[:40]
        lines.append(
            f"{emoji(growth)} *{safe_name}*\n"
            f"   `{current:>6,}` jugadores ({growth:+.1f}%)"
        )
    return "\n".join(lines)


def send_telegram(message: str):
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("✗ Faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID en entorno", file=sys.stderr)
        print("--- Mensaje que se hubiera enviado ---")
        print(message)
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(url, json={
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }, timeout=15)
    if r.ok:
        print("✓ Reporte enviado a Telegram")
    else:
        print(f"✗ Error Telegram: {r.status_code} {r.text}", file=sys.stderr)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    category = args[0] if args else "brainrot"
    weekly = "--weekly" in sys.argv

    if category not in CATEGORIES:
        print(f"✗ Categoría desconocida: '{category}'. "
              f"Opciones: {', '.join(CATEGORIES)}", file=sys.stderr)
        sys.exit(1)

    cfg = CATEGORIES[category]
    period = 24 * 7 if weekly else 24
    span = "últimos 7 días" if weekly else "últimas 24h"
    rows = get_top_movers(cfg["db"], period_hours=period)
    msg = format_report(rows, f"{cfg['label']} — Top movers ({span})")
    send_telegram(msg)
