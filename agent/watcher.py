"""ACE Agent - sorveglia la cartella MoTeC e carica le sessioni sulla dashboard.

Funziona come eseguibile (.exe) o come script Python. Configurazione in config.ini
nella stessa cartella. Stato in uploaded.json per non ricaricare due volte.
"""
import os
import sys
import json
import time
import hashlib
import configparser

import requests

APP_NAME = "ACE Agent"
AGENT_VERSION = "1.5.1"


def base_dir():
    if getattr(sys, "frozen", False):          # eseguibile PyInstaller
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE = base_dir()
CONFIG_PATH = os.path.join(BASE, "config.ini")
STATE_PATH = os.path.join(BASE, "uploaded.json")
LOG_PATH = os.path.join(BASE, "agent.log")

DEFAULT_CONFIG = """; --- Configurazione ACE Agent ---
[agent]
; URL della dashboard su Railway (senza / finale)
dashboard_url = https://il-tuo-progetto.up.railway.app
; Token di ingest (stesso valore della variabile INGEST_TOKEN su Railway)
token = CAMBIAMI
; Il tuo nome (comparira' come "pilota" nelle sessioni)
uploader = Nico
; Cartella telemetrie MoTeC (lascia cosi' se usi il percorso standard)
motec_folder = %USERPROFILE%\\Saved Games\\ACE\\MoTec
; Cartella setup auto (lascia cosi' se usi il percorso standard)
setups_folder = %USERPROFILE%\\Saved Games\\ACE\\Car Setups
; Ogni quanti secondi controllare le cartelle
poll_seconds = 15
; Eta' minima del file in secondi prima di caricarlo (evita file a meta' scrittura)
min_age_seconds = 10
"""


def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S  ") + msg
    print(line)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_config():
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write(DEFAULT_CONFIG)
        log("Creato config.ini: aprilo, inserisci URL/token/nome e riavvia.")
        return None
    try:
        cp = configparser.ConfigParser(interpolation=None)
        cp.read(CONFIG_PATH, encoding="utf-8")
        a = cp["agent"]
        cfg = {
            "url": a.get("dashboard_url", "").rstrip("/"),
            "token": a.get("token", ""),
            "uploader": a.get("uploader", "agent"),
            "folder": os.path.expandvars(a.get("motec_folder", "")),
            "setups_folder": os.path.expandvars(a.get("setups_folder", "")),
            "poll": a.getint("poll_seconds", 15),
            "min_age": a.getint("min_age_seconds", 10),
        }
    except Exception as e:
        log(f"config.ini illeggibile: {e}")
        return None
    if not cfg["url"] or cfg["token"] in ("", "CAMBIAMI"):
        log("config.ini incompleto: imposta dashboard_url e token.")
        return None
    return cfg


def load_state():
    if os.path.exists(STATE_PATH):
        try:
            return set(json.load(open(STATE_PATH, encoding="utf-8")))
        except (OSError, ValueError):
            return set()
    return set()


def save_state(state):
    try:
        json.dump(sorted(state), open(STATE_PATH, "w", encoding="utf-8"))
    except OSError:
        pass


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_files(folder, ext):
    out = []
    for root, _d, names in os.walk(folder):
        for n in names:
            if n.lower().endswith(ext):
                out.append(os.path.join(root, n))
    return out


def upload(cfg, path, extra=None):
    ldx_path = path[:-3] + ".ldx"
    files = [("files", (os.path.basename(path), open(path, "rb"), "application/octet-stream"))]
    if os.path.exists(ldx_path):
        files.append(("files", (os.path.basename(ldx_path), open(ldx_path, "rb"), "application/octet-stream")))
    r = requests.post(cfg["url"] + "/api/ingest", headers={"X-Ingest-Token": cfg["token"]},
                      data={"uploader": cfg["uploader"]}, files=files, timeout=120)
    r.raise_for_status()
    return r.json()


def upload_setup(cfg, path, extra=None):
    data = {"uploader": cfg["uploader"]}
    if extra:
        data.update(extra)                       # car / track dalle sottocartelle
    files = [("files", (os.path.basename(path), open(path, "rb"), "application/octet-stream"))]
    r = requests.post(cfg["url"] + "/api/ingest-setup", headers={"X-Ingest-Token": cfg["token"]},
                      data=data, files=files, timeout=60)
    r.raise_for_status()
    return r.json()


def _process(path, upload_fn, label, cfg, state, now, extra=None):
    sha = None
    try:
        if now - os.path.getmtime(path) < cfg["min_age"]:
            return
        sha = sha256(path)
        if sha in state:
            return
        log(f"{label} {os.path.basename(path)} ...")
        res = upload_fn(cfg, path, extra)
        state.add(sha); save_state(state)
        log("  duplicato sul server" if res.get("duplicate") else f"  ok -> id {res.get('id')}")
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else 0
        if code in (400, 422):
            if sha:
                state.add(sha); save_state(state)
            log("  ignorato (file non valido)")
        elif code in (401, 403):
            log("  TOKEN NON VALIDO: correggi 'token' in config.ini e riavvia.")
        else:
            log(f"  errore server {code}: riprovo dopo")
    except requests.RequestException as e:
        log(f"  errore rete: {e} (riprovo dopo)")
    except Exception as e:
        log(f"  errore: {e}")


def _safe(s):
    s = s or "Varie"
    for ch in '<>:"/\\|?*':
        s = s.replace(ch, "_")
    return s.strip() or "Varie"


def sync_setups_down(cfg, state):
    """Scarica i setup degli altri e li scrive in Car Setups\\<Auto>\\<Pista>\\.
    I file scaricati entrano nello stato, quindi non vengono ri-caricati (no loop)."""
    sf = cfg.get("setups_folder")
    if not sf:
        return
    try:
        man = requests.get(cfg["url"] + "/api/setups-manifest",
                           headers={"X-Ingest-Token": cfg["token"]}, timeout=30)
        man.raise_for_status()
        setups = man.json().get("setups", [])
    except requests.RequestException as e:
        log(f"  sync setup: errore rete ({e})")
        return
    for s in setups:
        if s["sha"] in state:        # mio, o gia' scaricato
            continue
        try:
            r = requests.get(cfg["url"] + f"/api/setup-file/{s['id']}",
                             headers={"X-Ingest-Token": cfg["token"]}, timeout=60)
            r.raise_for_status()
        except requests.RequestException as e:
            log(f"  sync setup {s['name']}: errore download ({e})")
            continue
        dest_dir = os.path.join(sf, _safe(s.get("car")), _safe(s.get("track")))
        os.makedirs(dest_dir, exist_ok=True)
        fname = _safe(f"{s['name']} [{s['uploader']}]") + ".carsetup"
        with open(os.path.join(dest_dir, fname), "wb") as f:
            f.write(r.content)
        state.add(s["sha"]); save_state(state)
        log(f"Scaricato setup '{s['name']}' di {s['uploader']} -> {s.get('car')}/{s.get('track')}")


def scan_once(cfg, state):
    now = time.time()
    if os.path.isdir(cfg["folder"]):
        for ld in find_files(cfg["folder"], ".ld"):
            _process(ld, upload, "Carico", cfg, state, now)
    else:
        log(f"Cartella telemetria non trovata: {cfg['folder']}")
    sf = cfg.get("setups_folder")
    if sf and os.path.isdir(sf):
        for sp in find_files(sf, ".carsetup"):
            rel = os.path.relpath(sp, sf).split(os.sep)
            extra = {}
            if len(rel) >= 2:
                extra["car"] = rel[0]            # cartella auto
            if len(rel) >= 3:
                extra["track"] = rel[1]          # cartella pista
            _process(sp, upload_setup, "Setup", cfg, state, now, extra)
    sync_setups_down(cfg, state)                 # scarica i setup degli altri


def _run():
    once = "--once" in sys.argv
    log(f"{APP_NAME} v{AGENT_VERSION} avviato.")
    cfg = load_config()
    if not cfg:
        if not once:
            input("Premi Invio per chiudere...")
        return
    log(f"Sorveglio: {cfg['folder']}  ->  {cfg['url']}  (pilota: {cfg['uploader']})")
    state = load_state()
    if once:
        scan_once(cfg, state)
        return
    while True:
        scan_once(cfg, state)
        time.sleep(cfg["poll"])


def main():
    try:
        _run()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        log(f"ERRORE imprevisto: {e}")
        if "--once" not in sys.argv:
            input("Premi Invio per chiudere...")


if __name__ == "__main__":
    main()
