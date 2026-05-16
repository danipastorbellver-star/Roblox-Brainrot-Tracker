"""
export_dashboard.py — Exporta los SQLite de cada categoría a un JSON único.

Estructura de salida:
{
  "updated_at": "...",
  "categories": {
    "brainrot": { "label": "Brainrot", "total_games": N, "games": [...] },
    "horror":   { "label": "Horror",   "total_games": M, "games": [...] }
  }
}

Uso:
  python export_dashboard.py
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
OUT_PATH = ROOT / "data" / "dashboard.json"

# Debe coincidir con CATEGORIES de tracker.py
CATEGORIES = {
    "brainrot": {"label": "Brainrot", "db": ROOT / "data" / "tracker_brainrot.db"},
    "horror":   {"label": "Horror",   "db": ROOT / "data" / "tracker_horror.db"},
}


def pct(new: float, old: float) -> float | None:
    if old is None or old <= 0:
        return None
    return round((new - old) * 100 / old, 2)


def build_category(db_path: Path) -> list[dict]:
    if not db_path.exists():
        return []

    con = sqlite3.connect(db_path)
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

        g_24h = pct(current, hist[-2]["players"]) if n >= 2 else None
        g_7d = pct(current, hist[-8]["players"]) if n >= 8 else (
            pct(current, hist[0]["players"]) if n >= 2 else None
        )

        acceleration = None
        if n >= 3:
            g_today = pct(current, hist[-2]["players"])
            g_yesterday = pct(hist[-2]["players"], hist[-3]["players"])
            if g_today is not None and g_yesterday is not None:
                acceleration = round(g_today - g_yesterday, 2)

        peak = max(hist, key=lambda h: h["players"]) if hist else None
        pct_from_peak = pct(current, peak["players"]) if peak else None

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
    return games


def export():
    categories = {}
    for key, cfg in CATEGORIES.items():
        games = build_category(cfg["db"])
        categories[key] = {
            "label": cfg["label"],
            "total_games": len(games),
            "games": games,
        }
        print(f"  {cfg['label']}: {len(games)} juegos")

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "categories": categories,
    }
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    total = sum(c["total_games"] for c in categories.values())
    print(f"✓ Exportado: {OUT_PATH} ({total} juegos totales, "
          f"{OUT_PATH.stat().st_size:,} bytes)")


if __name__ == "__main__":
    export()
