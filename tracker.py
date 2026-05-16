"""
tracker.py — Recolecta datos de juegos "brainrot-style" de Roblox.

Estrategia:
  1. Pide a Rolimons la lista completa de juegos rastreados (sin auth, devuelve
     miles de juegos con su player count actual).
  2. Filtra por palabras clave + mínimo de jugadores.
  3. Enriquece con detalles oficiales desde games.roblox.com.
  4. Guarda un snapshot timestamped en SQLite.

Uso:
  python tracker.py
"""

import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# ─── Configuración ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "tracker.db"

# Palabras clave para identificar "brainrot-style". Edita libremente.
KEYWORDS = [
    "brainrot", "lucky block", "tsunami", "obby", "steal",
    "escape", "tycoon", "rng", "skibidi", "merge", "grow a",
    "race", "survive", "fisch", "anime",
]

MIN_PLAYERS = 5_000          # umbral mínimo para empezar a trackear
MAX_GAMES_TO_TRACK = 200     # tope para no saturar la API

# Endpoints
ROLIMONS_GAMELIST = "https://api.rolimons.com/games/v1/gamelist"
ROBLOX_GAMES_API = "https://games.roblox.com/v1/games"

# Mapeo del formato Rolimons (índices del array por juego)
# Formato real: [name, players, thumbnail_url, ...]
ROL_NAME, ROL_PLAYERS, ROL_THUMB = 0, 1, 2

HEADERS = {"User-Agent": "roblox-tracker/1.1"}


def get_with_retry(url: str, max_retries: int = 4, timeout: int = 15):
    """GET con reintentos y backoff exponencial ante rate limit / fallos.

    Devuelve el objeto Response si tiene éxito, o None si agota reintentos.
    """
    for attempt in range(max_retries):
        try:
            r = requests.get(url, timeout=timeout, headers=HEADERS)
            # Rate limited → espera y reintenta
            if r.status_code == 429:
                wait = 2 ** attempt + 1  # 2, 3, 5, 9 segundos
                print(f"    rate limit (429), esperando {wait}s…", file=sys.stderr)
                time.sleep(wait)
                continue
            if r.ok:
                return r
            # Otros errores HTTP: reintenta una vez con espera corta
            time.sleep(1.5)
        except requests.RequestException as e:
            time.sleep(2 ** attempt)  # backoff ante timeout/conexión
            if attempt == max_retries - 1:
                print(f"    fallo definitivo para {url[:60]}…: {e}", file=sys.stderr)
    return None


# ─── Base de datos ─────────────────────────────────────────────────────────────
def init_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            place_id      INTEGER NOT NULL,
            universe_id   INTEGER,
            name          TEXT NOT NULL,
            player_count  INTEGER NOT NULL,
            visits        INTEGER,
            favorites     INTEGER,
            up_votes      INTEGER,
            down_votes    INTEGER,
            ts            TEXT NOT NULL
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_place_ts ON snapshots(place_id, ts)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_ts ON snapshots(ts)")
    con.commit()
    return con


# ─── Recolección ──────────────────────────────────────────────────────────────
def fetch_rolimons_games() -> dict:
    """Devuelve dict {place_id: [name, players, thumb, ...]}."""
    r = requests.get(ROLIMONS_GAMELIST, timeout=30,
                     headers={"User-Agent": "roblox-tracker/1.0"})
    r.raise_for_status()
    data = r.json()
    return data.get("games", {})


def matches_keywords(name: str) -> bool:
    n = name.lower()
    return any(kw in n for kw in KEYWORDS)


def fetch_roblox_details(universe_ids: list[int]) -> list[dict]:
    """games.roblox.com acepta hasta ~50 IDs por llamada. Con reintentos."""
    results = []
    for i in range(0, len(universe_ids), 50):
        batch = universe_ids[i:i + 50]
        params = "&".join(f"universeIds={uid}" for uid in batch)
        url = f"{ROBLOX_GAMES_API}?{params}"
        r = get_with_retry(url, max_retries=4, timeout=20)
        if r is not None:
            results.extend(r.json().get("data", []))
        else:
            print(f"  ⚠ Batch {i}-{i+len(batch)} sin detalles "
                  f"(fallback a Rolimons)", file=sys.stderr)
        time.sleep(1)  # respetuosos con la API
    return results


def place_to_universe(place_ids: list[int]) -> dict[int, int]:
    """Convierte place_id → universe_id usando apis.roblox.com.

    Usa reintentos. Reporta cuántos fallaron para no perderlos en silencio.
    """
    mapping = {}
    failed = []
    for i, pid in enumerate(place_ids):
        url = f"https://apis.roblox.com/universes/v1/places/{pid}/universe"
        r = get_with_retry(url, max_retries=4, timeout=10)
        if r is not None:
            uid = r.json().get("universeId")
            if uid:
                mapping[pid] = uid
            else:
                failed.append(pid)
        else:
            failed.append(pid)
        # Pausa adaptativa: más lenta para no provocar rate limiting
        time.sleep(0.25)
        if (i + 1) % 25 == 0:
            print(f"    universe IDs: {i + 1}/{len(place_ids)}…")

    if failed:
        print(f"  ⚠ {len(failed)} place_ids sin universe_id "
              f"(se usará el player count de Rolimons como fallback)",
              file=sys.stderr)
    return mapping


# ─── Pipeline principal ────────────────────────────────────────────────────────
def run():
    now = datetime.now(timezone.utc).isoformat()
    print(f"▶ Tracker iniciado — {now}")

    print("  Descargando lista de juegos desde Rolimons…")
    rolimons = fetch_rolimons_games()
    print(f"  Total juegos en Rolimons: {len(rolimons):,}")

    # Filtra por keyword + min_players
    candidates = []
    for place_id_str, info in rolimons.items():
        try:
            name = info[ROL_NAME]
            players = info[ROL_PLAYERS]
        except (IndexError, TypeError):
            continue
        if players < MIN_PLAYERS:
            continue
        if not matches_keywords(name):
            continue
        candidates.append((int(place_id_str), name, players))

    candidates.sort(key=lambda x: -x[2])  # ordenados por player count desc
    candidates = candidates[:MAX_GAMES_TO_TRACK]
    print(f"  Candidatos tras filtro: {len(candidates)}")

    if not candidates:
        print("  No hay candidatos. Revisa MIN_PLAYERS o KEYWORDS.")
        return

    # Mapea place_id → universe_id para enriquecer
    place_ids = [c[0] for c in candidates]
    print("  Obteniendo universe IDs…")
    mapping = place_to_universe(place_ids)
    universe_ids = [u for u in mapping.values() if u]
    print(f"  Universe IDs obtenidos: {len(universe_ids)}")

    print("  Obteniendo detalles oficiales de Roblox…")
    details = fetch_roblox_details(universe_ids)
    detail_map = {d["id"]: d for d in details}

    # Guardar snapshot
    con = init_db()
    rows = []
    enriched = 0       # cuántos tienen datos oficiales de Roblox
    fallback = 0       # cuántos usan solo el dato de Rolimons
    skipped = 0        # cuántos se descartan por no tener ningún dato fiable

    for place_id, name, rolimons_players in candidates:
        uid = mapping.get(place_id)
        d = detail_map.get(uid, {}) if uid else {}

        # El player count de Roblox (playing) es el preferido, pero si no
        # está disponible usamos el de Rolimons, que también es fiable.
        roblox_playing = d.get("playing")
        if roblox_playing is not None and roblox_playing > 0:
            player_count = roblox_playing
            enriched += 1
        elif rolimons_players and rolimons_players > 0:
            player_count = rolimons_players
            fallback += 1
        else:
            # Sin ningún dato válido → no guardamos un 0 falso, lo saltamos
            skipped += 1
            continue

        rows.append((
            place_id,
            uid,
            d.get("name", name),
            player_count,
            d.get("visits"),
            d.get("favoritedCount"),
            None,  # up_votes — requiere otra llamada, opcional
            None,  # down_votes
            now,
        ))

    con.executemany(
        """INSERT INTO snapshots
           (place_id, universe_id, name, player_count, visits, favorites, up_votes, down_votes, ts)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    con.commit()
    con.close()

    print(f"✓ Guardados {len(rows)} snapshots en {DB_PATH}")
    print(f"  ├─ {enriched} con datos oficiales de Roblox (visits/favorites incl.)")
    print(f"  ├─ {fallback} con player count de Rolimons (sin enriquecer)")
    if skipped:
        print(f"  └─ {skipped} descartados (sin ningún dato fiable, NO se guardó 0)")


if __name__ == "__main__":
    try:
        run()
    except requests.RequestException as e:
        print(f"✗ Error de red: {e}", file=sys.stderr)
        sys.exit(1)
