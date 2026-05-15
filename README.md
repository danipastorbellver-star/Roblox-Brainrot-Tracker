# Roblox Brainrot Tracker

Sistema de tracking diario de juegos "brainrot-style" en Roblox con análisis de crecimiento, notificaciones por Telegram y dashboard web.

## Cómo funciona

1. **`tracker.py`** se conecta a la API de Rolimons (lista pública de juegos con player counts) y filtra por palabras clave (`brainrot`, `obby`, `tsunami`, etc.) y mínimo de jugadores (5K por defecto). Luego enriquece con datos oficiales desde `games.roblox.com` y guarda un snapshot en SQLite.
2. **`notifier.py`** lee el SQLite, calcula crecimiento % vs hace 24h (o 7d), y envía el top 10 movers a Telegram.
3. **`export_dashboard.py`** vuelca el SQLite a `data/dashboard.json`.
4. **`dashboard.html`** lee ese JSON y muestra tabla + gráfico interactivo.
5. **GitHub Actions** ejecuta todo automáticamente cada día a las 9:00 UTC.

## Implementación paso a paso

### Paso 1 — Setup local (5 min)

```bash
# Clona o copia los archivos a una carpeta
cd roblox-tracker
python -m venv venv && source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Primera ejecución de prueba
python tracker.py
```

Si todo va bien verás algo como:
```
▶ Tracker iniciado — 2026-05-15T...
  Total juegos en Rolimons: 5,400
  Candidatos tras filtro: 87
  ...
✓ Guardados 87 snapshots en data/tracker.db
```

### Paso 2 — Probar el dashboard (2 min)

```bash
python export_dashboard.py
# Sirve los archivos en http://localhost:8000
python -m http.server 8000
```

Abre `http://localhost:8000/dashboard.html` en el navegador.

> **Nota:** la primera vez solo verás 1 punto por juego. Los gráficos cobran sentido después de 2-3 días de ejecuciones.

### Paso 3 — Bot de Telegram (3 min)

1. En Telegram, escribe a **@BotFather** → `/newbot` → guarda el token.
2. Escribe a tu bot recién creado (al menos un `/start`).
3. Visita `https://api.telegram.org/bot<TU_TOKEN>/getUpdates` y copia el `chat.id` que aparece.
4. Exporta variables y prueba:

```bash
export TELEGRAM_TOKEN="123456:ABC..."
export TELEGRAM_CHAT_ID="987654321"
python notifier.py
```

Sin variables, el mensaje se imprime en consola (útil para debug).

### Paso 4 — Automatización

**Opción A — GitHub Actions (recomendado, gratis y sin servidor):**

1. Crea un repo público o privado en GitHub.
2. Sube los archivos (`git init && git add . && git commit -m "init" && git push`).
3. En el repo → **Settings → Secrets and variables → Actions → New secret**:
   - `TELEGRAM_TOKEN`
   - `TELEGRAM_CHAT_ID`
4. Ya está. El workflow `.github/workflows/tracker.yml` corre cada día a las 9:00 UTC y commitea los datos.

Bonus: si haces público el repo, puedes activar **GitHub Pages** (Settings → Pages → branch `main` / root) y tu dashboard estará en `https://<tu-usuario>.github.io/<repo>/dashboard.html` con datos actualizados automáticamente.

**Opción B — Cron local:**

```bash
crontab -e
# Añade esta línea (ajusta la ruta absoluta):
0 9 * * * cd /ruta/a/roblox-tracker && /ruta/a/venv/bin/python tracker.py && /ruta/a/venv/bin/python export_dashboard.py && /ruta/a/venv/bin/python notifier.py
```

## Ajustes que querrás hacer

En `tracker.py` arriba del todo:

| Variable             | Por defecto       | Para qué                                          |
|----------------------|-------------------|---------------------------------------------------|
| `KEYWORDS`           | brainrot, obby, … | Palabras que deben aparecer en el nombre          |
| `MIN_PLAYERS`        | 5000              | Umbral para considerar un juego                   |
| `MAX_GAMES_TO_TRACK` | 200               | Tope para no saturar la API de Roblox             |

## Roadmap / ideas

- Alertas instantáneas cuando un juego supere +50% en 24h.
- Detectar juegos "emergentes" (de <5K a >10K en pocos días).
- Análisis de correlación entre favorites/visits y player count.
- Comparar vs juegos conocidos como referencia ("Steal a Brainrot" tuvo X jugadores el día Y).

## Limitaciones honestas

- La API de Rolimons puede caer o cambiar formato. Si pasa, hay que ajustar `tracker.py`.
- Los endpoints públicos de `games.roblox.com` están sujetos a rate limiting. El script ya hace pausas, pero si tienes problemas baja `MAX_GAMES_TO_TRACK`.
- No detecta juegos antes de que aparezcan en Rolimons (suele ser cuando ya tienen >100 jugadores).
