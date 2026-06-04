# ACE Viewer

Visualizzatore di telemetria per **Assetto Corsa EVO** che legge i file **MoTeC `.ld`/`.ldx`**
esportati dal gioco. Mostra, per ogni sessione: statistiche, tabella giri con tempi,
mappa del tracciato (ricostruita senza GPS) e i grafici di tutti i canali, sincronizzati.

Pensato per essere condiviso con pochi amici: login HTTP Basic, deploy su Railway.

La versione corrente è in `version.py` ed è mostrata nel footer della dashboard.

## Deploy rapido (script Windows)

- **Prima volta** — collega il repo a GitHub:
  `git-setup.bat https://github.com/TUO-UTENTE/ace-viewer.git`
  poi su Railway: *New Project → Deploy from GitHub repo*.
- **Ogni aggiornamento** — invia le modifiche (Railway redeploya da solo):
  `deploy.bat "cosa ho cambiato"`
  Quando il footer della dashboard mostra il nuovo numero di versione, il deploy è andato.

## Funzioni

- **Upload** di file `.ld` (+ `.ldx` opzionale per i beacon dei giri).
- **Parser MoTeC** integrato (nessuna dipendenza esterna oltre numpy/Flask).
- **Mappa del tracciato** ricostruita per *dead-reckoning* da velocità + yaw rate
  (ACE non esporta coordinate GPS), colorabile per canale.
- **Rilevamento giri**: usa il beacon dell'`.ldx` come linea del traguardo e conta i
  passaggi successivi → tempi sul giro. Servono ≥2 passaggi per un giro completo;
  con un solo passaggio viene mostrata la sessione intera.
- **Grafici uPlot** sincronizzati (velocità, pedali, motore+marcia, sterzo, G) con
  cursore collegato al puntino sulla mappa; tutti i 78 canali caricabili a richiesta.
- **Selezione giro** per isolare un giro su mappa e grafici.

## Avvio locale

```bash
pip install -r requirements.txt
export USERS="ernesto:lapassword,vito:altrapass"   # utenti:password separati da virgola
export DATA_DIR=./data                              # dove salvare db + telemetrie
python app.py                                        # http://localhost:5000
```

## Deploy su Railway

1. Push del repo su GitHub, poi **New Project → Deploy from GitHub** su Railway.
2. Railway rileva `railway.toml` / `Procfile` e builda con Nixpacks. Lo start command
   usa `$PORT` (gestito da Railway):
   `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
3. **Variabili d'ambiente** (Settings → Variables):
   - `USERS` = `ernesto:pwd1,nico:pwd2,antonello:pwd3` (login dashboard).
   - `INGEST_TOKEN` = una stringa segreta a piacere (serve all'agente locale per
     caricare le sessioni; senza, l'ingest automatico resta disattivato).
   - `DATA_DIR` = `/data` (consigliato puntarla al volume, vedi sotto).
4. **Volume persistente** (altrimenti perdi i dati ad ogni redeploy):
   crea un volume montato su `/data` e imposta `DATA_DIR=/data`.
5. Healthcheck già configurato su `/healthz`.

## Caricamento automatico (agente locale)

La dashboard online non può leggere il disco dei PC: per l'upload automatico c'è un
piccolo agente in `agent/` che gira sul PC di ognuno, sorveglia la cartella MoTeC e
carica le sessioni nuove via `POST /api/ingest` (autenticato con `INGEST_TOKEN`).

**Generare l'eseguibile `ace-agent.exe`** (senza Python per chi lo usa):
- *Via GitHub Actions* (consigliato): il workflow `.github/workflows/build-agent.yml`
  compila l'`.exe` su un runner Windows. Avvialo da Actions → build-agent → Run
  workflow, poi scarica l'artifact `ace-agent-windows`.
- *In locale su Windows*: nella cartella `agent/` esegui `build.bat` (richiede Python);
  l'eseguibile finisce in `agent/dist/ace-agent.exe`.

**Distribuzione**: dai a Nico e Antonello il file `ace-agent.exe` + `LEGGIMI.txt`.
Loro lo avviano una volta (crea `config.ini`), inseriscono URL dashboard, token e il
proprio nome, e lo lasciano in esecuzione mentre giocano. Le sessioni compaiono sulla
dashboard col nome di ciascuno; i duplicati vengono ignorati (lato agente e lato server).

## Endpoint API

- `POST /api/ingest` — usato dall'agente. Header `X-Ingest-Token`, campo form
  `uploader`, file `.ld` (+ `.ldx`). Risponde `{id, duplicate, status}`.
- `GET /api/session/<id>` — payload sessione (mappa, giri, canali core).
- `GET /api/session/<id>/channel/<nome>` — singolo canale on-demand.

## Struttura dati

- `DATA_DIR/ace.db` — metadati sessioni (SQLite).
- `DATA_DIR/uploads/<id>/` — file `.ld`/`.ldx` originali.
- `DATA_DIR/processed/<id>.json.gz` — payload elaborato (canali ricampionati a 50 Hz,
  mappa, giri). ~1.6 MB per una sessione da ~7 minuti.

## Note tecniche

- La conversione fisica dei canali usa `(raw/scale * 10^-dec + shift) * mul`; `SPEED`
  viene convertita in km/h.
- La mappa è una ricostruzione relativa: l'orientamento può non coincidere con quello
  reale del circuito, ma la forma e le proporzioni sono corrette (deriva tipica < 15 m
  su un giro di Spa).
- Per tempi sul giro affidabili, esporta sessioni che contengano più passaggi sul
  traguardo (prove libere / qualifica con più giri lanciati).

## Possibili estensioni

- Confronto sovrapposto di due giri (delta-time) su asse distanza.
- Endpoint di export/import del database (come in rc_viewer).
- Auto-rilevamento giri anche senza beacon, da chiusura della traiettoria.
