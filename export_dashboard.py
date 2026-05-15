"""
export_dashboard.py — Exporta el SQLite a un JSON que consume dashboard.html.

Uso:
  python export_dashboard.py
"""

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "tracker.db"
OUT_PATH = ROOT / "data" / "dashboard.json"


def export():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    # Snapshot más reciente por juego
    latest = con.execute("""
        SELECT s.* FROM snapshots s
        JOIN (
            SELECT place_id, MAX(ts) AS max_ts
            FROM snapshots GROUP BY place_id
        ) m ON s.place_id = m.place_id AND s.ts = m.max_ts
        ORDER BY s.player_count DESC
    """).fetchall()

    # Series temporales (hasta 30 puntos por juego para no inflar el JSON)
    series = {}
    for row in latest:
        history = con.execute("""
            SELECT ts, player_count FROM snapshots
            WHERE place_id = ?
            ORDER BY ts DESC LIMIT 30
        """, (row["place_id"],)).fetchall()
        series[row["place_id"]] = [
            {"ts": h["ts"], "players": h["player_count"]}
            for h in reversed(history)
        ]

    con.close()

    def growth(history: list, hours: int) -> float | None:
        """Crecimiento % comparando primer y último punto en la ventana."""
        if len(history) < 2: return None
        cutoff_idx = max(0, len(history) - hours - 1) if hours <= len(history) else 0
        old = history[cutoff_idx]["players"]
        new = history[-1]["players"]
        if old == 0: return None
        return round((new - old) * 100 / old, 1)

    games = []
    for row in latest:
        hist = series[row["place_id"]]
        games.append({
            "place_id": row["place_id"],
            "universe_id": row["universe_id"],
            "name": row["name"],
            "players": row["player_count"],
            "visits": row["visits"],
            "favorites": row["favorites"],
            "growth_24h": growth(hist, 1),
            "growth_7d": growth(hist, 7),
            "history": hist,
            "url": f"https://www.roblox.com/games/{row['place_id']}",
        })

    payload = {
        "updated_at": games[0]["history"][-1]["ts"] if games else None,
        "total_games": len(games),
        "games": games,
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"✓ Exportado: {OUT_PATH} ({len(games)} juegos)")


if __name__ == "__main__":
    export()
