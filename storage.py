"""Persistenza: SQLite per i metadati delle sessioni + payload elaborato su disco (json.gz)."""
import os
import re
import json
import gzip
import sqlite3
import uuid
from datetime import datetime, timezone

import numpy as np

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
DB_PATH = os.path.join(DATA_DIR, "ace.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
PROC_DIR = os.path.join(DATA_DIR, "processed")

for d in (DATA_DIR, UPLOAD_DIR, PROC_DIR):
    os.makedirs(d, exist_ok=True)


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                orig_name TEXT,
                car TEXT, track TEXT,
                date TEXT, time TEXT,
                duration REAL,
                n_laps INTEGER,
                best_lap_str TEXT,
                v_max REAL,
                distance_km REAL,
                uploader TEXT,
                created_at TEXT,
                sha TEXT
            )""")
        # migrazione soft per db gia' esistenti
        cols = [r[1] for r in c.execute("PRAGMA table_info(sessions)")]
        if "sha" not in cols:
            c.execute("ALTER TABLE sessions ADD COLUMN sha TEXT")
        if "air_temp" not in cols:
            c.execute("ALTER TABLE sessions ADD COLUMN air_temp REAL")
        if "road_temp" not in cols:
            c.execute("ALTER TABLE sessions ADD COLUMN road_temp REAL")
        c.execute("""
            CREATE TABLE IF NOT EXISTS setups (
                id TEXT PRIMARY KEY,
                name TEXT, car TEXT, track TEXT, preset TEXT,
                uploader TEXT, sha TEXT,
                params TEXT, created_at TEXT
            )""")
        scols = [r[1] for r in c.execute("PRAGMA table_info(setups)")]
        if "track" not in scols:
            c.execute("ALTER TABLE setups ADD COLUMN track TEXT")
        c.execute("""
            CREATE TABLE IF NOT EXISTS corners (
                track TEXT PRIMARY KEY,
                data TEXT
            )""")


SETUP_DIR = os.path.join(DATA_DIR, "setups")
os.makedirs(SETUP_DIR, exist_ok=True)


def get_corners(track):
    with _conn() as c:
        r = c.execute("SELECT data FROM corners WHERE track=?", (track,)).fetchone()
        return json.loads(r["data"]) if r else None


def save_corners(track, data):
    with _conn() as c:
        c.execute("INSERT INTO corners (track,data) VALUES (?,?) "
                  "ON CONFLICT(track) DO UPDATE SET data=excluded.data",
                  (track, json.dumps(data)))


def save_setup(raw_bytes, parsed, name, uploader, sha, car=None, track=None):
    import uuid as _uuid
    sid = _uuid.uuid4().hex[:12]
    with open(os.path.join(SETUP_DIR, sid + ".carsetup"), "wb") as f:
        f.write(raw_bytes)
    car_final = car or parsed["car"]            # preferisci la cartella auto
    track_final = track or ""
    with _conn() as c:
        c.execute("""INSERT INTO setups (id,name,car,track,preset,uploader,sha,params,created_at)
                     VALUES (?,?,?,?,?,?,?,?,?)""",
                  (sid, name, car_final, track_final, parsed.get("preset", ""), uploader, sha,
                   json.dumps(parsed["params"]),
                   datetime.now(timezone.utc).isoformat(timespec="seconds")))
    return sid


def find_setup_by_sha(sha):
    with _conn() as c:
        r = c.execute("SELECT id FROM setups WHERE sha=?", (sha,)).fetchone()
        return r["id"] if r else None


def list_setups():
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM setups ORDER BY car, created_at DESC")]


def get_setup(sid):
    with _conn() as c:
        r = c.execute("SELECT * FROM setups WHERE id=?", (sid,)).fetchone()
        return dict(r) if r else None


def setup_file(sid):
    return os.path.join(SETUP_DIR, sid + ".carsetup")


def delete_setup(sid):
    p = setup_file(sid)
    if os.path.exists(p):
        os.remove(p)
    with _conn() as c:
        c.execute("DELETE FROM setups WHERE id=?", (sid,))


def sha_of(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_by_sha(sha):
    with _conn() as c:
        r = c.execute("SELECT id FROM sessions WHERE sha=?", (sha,)).fetchone()
        return r["id"] if r else None


def parse_filename(name):
    """Estrae auto/pista dal nome file dell'export ACE (best-effort)."""
    stem = re.sub(r"\.(ld|ldx)$", "", name, flags=re.I)
    car, track = stem, ""
    m = re.match(r"(.+?)_preset", stem)
    if m:
        car = m.group(1).replace("_", " ")
    wk = r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)"
    # pista: segmento che inizia con Circuit/Track fino al giorno della settimana
    mt = re.search(r"_((?:Circuit|Track)[A-Za-z0-9_]*?)_" + wk, stem)
    if not mt:  # ripiego: chunk dopo "_mech_<n>_" fino al giorno
        mt = re.search(r"_mech_\d+_(.+?)_" + wk, stem)
    if mt:
        track = mt.group(1).replace("_", " ").strip()
    elif "Spa" in stem:
        track = "Spa Francorchamps"
    return car.strip(), track.strip()


def _to_jsonable(payload):
    def arr(a):
        return np.round(np.asarray(a, dtype=float), 3).tolist()

    def lapd(d):
        return {
            "dist": np.round(d["dist"], 1).tolist(),
            "time": np.round(d["time"], 3).tolist(),
            "x": np.round(d["x"], 1).tolist(),
            "y": np.round(d["y"], 1).tolist(),
            "channels": {k: np.round(v, 2).tolist() for k, v in d["channels"].items()},
        }

    # NB: NON salviamo gli array dell'intera sessione (t/x/y/channels a 50Hz):
    # i client usano solo i dati per-giro (lap_data). Risparmio enorme di spazio.
    out = {
        "meta": payload["meta"],
        "laps": payload["laps"],
        "lap_data": {k: lapd(v) for k, v in payload["lap_data"].items()},
        "best_lap": payload["best_lap"],
        "best_lap_str": payload["best_lap_str"],
        "best_lap_vmax": payload.get("best_lap_vmax"),
    }
    return out


def save_session(payload, ld_path, ldx_path, orig_name, uploader, sha=None):
    if sha is None:
        sha = sha_of(ld_path)
    sid = uuid.uuid4().hex[:12]
    sdir = os.path.join(UPLOAD_DIR, sid)
    os.makedirs(sdir, exist_ok=True)
    # conserva i file originali
    import shutil
    shutil.copy(ld_path, os.path.join(sdir, os.path.basename(ld_path)))
    if ldx_path and os.path.exists(ldx_path):
        shutil.copy(ldx_path, os.path.join(sdir, os.path.basename(ldx_path)))
    # payload elaborato
    with gzip.open(os.path.join(PROC_DIR, sid + ".json.gz"), "wt", encoding="utf-8") as f:
        json.dump(_to_jsonable(payload), f)

    car, track = parse_filename(orig_name)
    complete_laps = [l for l in payload["laps"] if l["complete"]]
    best_vmax = payload.get("best_lap_vmax") or 0
    best_dist = 0.0
    if payload["best_lap"] and str(payload["best_lap"]) in payload["lap_data"]:
        d = payload["lap_data"][str(payload["best_lap"])]["dist"]
        best_dist = round(float(d[-1]) / 1000, 2)
    w = payload["meta"].get("weather", {})
    with _conn() as c:
        c.execute("""INSERT INTO sessions
            (id,orig_name,car,track,date,time,duration,n_laps,best_lap_str,
             v_max,distance_km,uploader,created_at,sha,air_temp,road_temp)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, orig_name, car, track,
             payload["meta"]["date"], payload["meta"]["time"],
             payload["meta"]["duration"], len(complete_laps),
             payload["best_lap_str"], best_vmax, best_dist, uploader,
             datetime.now(timezone.utc).isoformat(timespec="seconds"), sha,
             w.get("air_temp"), w.get("road_temp")))
    return sid


def list_sessions():
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM sessions ORDER BY created_at DESC")]


def sessions_by_track(track):
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM sessions WHERE track=? ORDER BY best_lap_str", (track,))]


def get_session_meta(sid):
    with _conn() as c:
        r = c.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
        return dict(r) if r else None


def load_processed(sid):
    p = os.path.join(PROC_DIR, sid + ".json.gz")
    if not os.path.exists(p):
        return None
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return json.load(f)


def delete_session(sid):
    import shutil
    shutil.rmtree(os.path.join(UPLOAD_DIR, sid), ignore_errors=True)
    p = os.path.join(PROC_DIR, sid + ".json.gz")
    if os.path.exists(p):
        os.remove(p)
    with _conn() as c:
        c.execute("DELETE FROM sessions WHERE id=?", (sid,))


def _dir_size(path):
    tot = 0
    for root, _d, files in os.walk(path):
        for f in files:
            try:
                tot += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return tot


def disk_usage():
    return {"uploads": _dir_size(UPLOAD_DIR), "processed": _dir_size(PROC_DIR),
            "setups": _dir_size(SETUP_DIR), "total": _dir_size(DATA_DIR)}


def compact_processed(drop_raw=False):
    """Riscrive i file elaborati rimuovendo gli array dell'intera sessione non usati.
    Se drop_raw, elimina anche i file .ld/.ldx originali. Ritorna byte liberati."""
    DEAD = ("t", "x", "y", "channels")
    before = _dir_size(DATA_DIR)
    for fn in os.listdir(PROC_DIR):
        if not fn.endswith(".json.gz"):
            continue
        path = os.path.join(PROC_DIR, fn)
        try:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        if any(k in data for k in DEAD):
            for k in DEAD:
                data.pop(k, None)
            tmp = path + ".tmp"
            with gzip.open(tmp, "wt", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, path)
    if drop_raw:
        import shutil
        for sid in os.listdir(UPLOAD_DIR):
            shutil.rmtree(os.path.join(UPLOAD_DIR, sid), ignore_errors=True)
    after = _dir_size(DATA_DIR)
    return before - after
