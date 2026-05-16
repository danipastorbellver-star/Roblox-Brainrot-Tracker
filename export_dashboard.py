"""
export_dashboard.py — Exporta el SQLite a un JSON con métricas enriquecidas.

Métricas calculadas por juego:
  - players, visits, favorites (snapshot actual)
  - growth_24h, growth_7d (% de crecimiento)
  - acceleration (cambio en la tasa de crecimiento; +N pp = acelerando)
  - peak_players, peak_ts (máximo histórico)
  - pct_from_peak (cuán lejos del pico)
  - days_tracked (días desde la primera detección)
  - avg_growth_7d (crecimiento promedio diario en 7 días)
  - player_visit_ratio (% de visits que están actualmente jugando)
  - history: serie temporal hasta 60 puntos

Uso:
  python export_dashboard.py
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "tracker.db"
OUT_PATH = ROOT / "data" / "dashboard.json"


def pct(new: float, old: float) -> float | None:
    if old is None or old <= 0:
        return None
    return round((new - old) * 100 / old, 2)


def export():
    if not DB_PATH.exists():
        print(f"✗ No existe {DB_PATH}. Ejecuta tracker.py primero.")
        return

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    latest = con.execute("""
        SELECT s.* FROM snapshots s
        JOIN (
            SELECT place_id, MAX(ts) AS max_ts
            FROM snapshots GROUP BY place_id
        ) m ON s.place_id = m.place_id AND s.ts = m.max_ts
        ORDER BY s.player_count DESC
    """).fetchall()

    games = []
    for row in latest:
        history = con.execute("""
            SELECT ts, player_count FROM snapshots
            WHERE place_id = ?
            ORDER BY ts ASC
        """, (row["place_id"],)).fetchall()
        hist = [{"ts": h["ts"], "players": h["player_count"]} for h in history]
        hist = hist[-60:]

        n = len(hist)
        current = hist[-1]["players"] if hist else 0

        # Growth 24h y 7d (asume 1 ejecución diaria)
        g_24h = pct(current, hist[-2]["players"]) if n >= 2 else None
        g_7d = pct(current, hist[-8]["players"]) if n >= 8 else (
            pct(current, hist[0]["players"]) if n >= 2 else None
        )

        # Aceleración: cambio en la tasa de crecimiento (segunda derivada)
        acceleration = None
        if n >= 3:
            g_today = pct(current, hist[-2]["players"])
            g_yesterday = pct(hist[-2]["players"], hist[-3]["players"])
            if g_today is not None and g_yesterday is not None:
                acceleration = round(g_today - g_yesterday, 2)

        peak = max(hist, key=lambda h: h["players"]) if hist else None
        pct_from_peak = pct(current, peak["players"]) if peak else None

        # Crecimiento promedio diario en últimos 7 días
        avg_growth_7d = None
        if n >= 3:
            window = hist[-min(7, n):]
            daily = []
            for i in range(1, len(window)):
                g = pct(window[i]["players"], window[i-1]["players"])
                if g is not None:
                    daily.append(g)
            if daily:
                avg_growth_7d = round(sum(daily) / len(daily), 2)

        visits = row["visits"] or 0
        player_visit_ratio = (
            round((current / visits) * 100000, 2) if visits > 0 else None
        )

        games.append({
            "place_id": row["place_id"],
            "universe_id": row["universe_id"],
            "name": row["name"],
            "players": current,
            "visits": visits or None,
            "favorites": row["favorites"],
            "growth_24h": g_24h,
            "growth_7d": g_7d,
            "acceleration": acceleration,
            "avg_growth_7d": avg_growth_7d,
            "peak_players": peak["players"] if peak else current,
            "peak_ts": peak["ts"] if peak else None,
            "pct_from_peak": pct_from_peak,
            "days_tracked": n,
            "player_visit_ratio": player_visit_ratio,
            "history": hist,
            "url": f"https://www.roblox.com/games/{row['place_id']}",
        })

    con.close()

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total_games": len(games),
        "games": games,
    }
    OUT_PATH.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"✓ Exportado: {OUT_PATH} ({len(games)} juegos, {OUT_PATH.stat().st_size:,} bytes)")


if __name__ == "__main__":
    export()
