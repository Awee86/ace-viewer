"""ACE Viewer - visualizzatore telemetria MoTeC (.ld) per Assetto Corsa EVO.
Flask + SQLite, deploy su Railway. Auth HTTP Basic per piccoli gruppi."""
import os
import json
import tempfile
from functools import wraps

from flask import (Flask, request, render_template, redirect, url_for,
                   jsonify, abort, Response, send_file)

import analysis
import storage
import carsetup
import coach
from version import __version__

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # 64 MB upload
storage.init_db()


@app.context_processor
def inject_version():
    return {"app_version": __version__}


# ---------------------------------------------------------------- auth
def _users():
    raw = os.environ.get("USERS", "ace:ace")  # default solo per uso locale
    out = {}
    for pair in raw.split(","):
        if ":" in pair:
            u, p = pair.split(":", 1)
            out[u.strip()] = p.strip()
    return out


def require_auth(f):
    @wraps(f)
    def wrapper(*a, **kw):
        auth = request.authorization
        users = _users()
        if not auth or users.get(auth.username) != auth.password:
            return Response("Accesso riservato", 401,
                            {"WWW-Authenticate": 'Basic realm="ACE Viewer"'})
        request.user = auth.username
        return f(*a, **kw)
    return wrapper


def _ingest(ld_path, ldx_path, orig, uploader):
    """Elabora e salva una sessione, saltando i duplicati (per hash). Ritorna (sid, dup)."""
    sha = storage.sha_of(ld_path)
    existing = storage.find_by_sha(sha)
    if existing:
        return existing, True
    payload = analysis.process(ld_path, ldx_path)
    sid = storage.save_session(payload, ld_path, ldx_path, orig, uploader, sha=sha)
    return sid, False


# ---------------------------------------------------------------- pagine
def _laptime_to_sec(s):
    try:
        m, rest = s.split(":")
        return int(m) * 60 + float(rest)
    except (ValueError, AttributeError):
        return 1e9


def _driver_columns():
    raw = os.environ.get("DRIVERS", "Ernesto,Nico,Antonello")
    return [d.strip() for d in raw.split(",") if d.strip()]


def _datekey(s):
    try:
        d = (s["date"] or "").split("/")          # dd/mm/yyyy
        return d[2] + d[1].zfill(2) + d[0].zfill(2) + (s["time"] or "").replace(":", "")
    except (IndexError, AttributeError):
        return "0"


def _build_aggregate(sessions):
    """Colonna per pilota; dentro: Tracciato -> Auto (con best per auto) -> sessioni."""
    norm = lambda x: (x or "").strip().lower()
    by_driver = {}
    for s in sessions:
        e = by_driver.setdefault(norm(s["uploader"]), {"display": s["uploader"] or "—", "tracks": {}})
        t = e["tracks"].setdefault(s["track"] or "—", {})
        t.setdefault(s["car"] or "—", []).append(s)

    def pack(display, entry):
        tracks = []
        if entry:
            for tn in sorted(entry["tracks"]):
                cars = []
                for cn in sorted(entry["tracks"][tn]):
                    sess = entry["tracks"][tn][cn]
                    for s in sess:
                        s["datekey"] = _datekey(s)
                        s["lapsec"] = _laptime_to_sec(s["best_lap_str"])
                    sess = sorted(sess, key=lambda s: s["datekey"], reverse=True)
                    best = min((s["best_lap_str"] for s in sess), key=_laptime_to_sec)
                    cars.append({"car": cn, "sessions": sess, "best": best})
                tracks.append({"track": tn, "cars": cars,
                               "n": sum(len(c["sessions"]) for c in cars)})
        return {"driver": display, "tracks": tracks}

    columns, used = [], set()
    for name in _driver_columns():
        k = norm(name); used.add(k)
        columns.append(pack(name, by_driver.get(k)))
    for k, e in by_driver.items():
        if k not in used:
            columns.append(pack(e["display"], e))
    return columns


@app.route("/")
@require_auth
def index():
    sessions = storage.list_sessions()
    return render_template("index.html",
                           aggregate=_build_aggregate(sessions),
                           n_sessions=len(sessions))


@app.route("/upload", methods=["POST"])
@require_auth
def upload():
    files = request.files.getlist("files")
    ld_path = ldx_path = None
    tmp = tempfile.mkdtemp()
    orig = None
    for f in files:
        if not f.filename:
            continue
        dest = os.path.join(tmp, os.path.basename(f.filename))
        f.save(dest)
        low = f.filename.lower()
        if low.endswith(".ld"):
            ld_path, orig = dest, os.path.basename(f.filename)
        elif low.endswith(".ldx"):
            ldx_path = dest
    if not ld_path:
        return ("Serve almeno un file .ld", 400)
    if not ldx_path:
        cand = ld_path[:-3] + ".ldx"
        if os.path.exists(cand):
            ldx_path = cand
    try:
        _ingest(ld_path, ldx_path, orig, request.user)
    except Exception as e:
        return (f"Errore nel parsing: {e}", 400)
    return redirect(url_for("index"))


@app.route("/session/<sid>")
@require_auth
def session_view(sid):
    meta = storage.get_session_meta(sid)
    if not meta:
        abort(404)
    return render_template("session.html", s=meta)


@app.route("/session/<sid>/delete", methods=["POST"])
@require_auth
def session_delete(sid):
    storage.delete_session(sid)
    return redirect(url_for("index"))


# ---------------------------------------------------------------- API
@app.route("/api/session/<sid>")
@require_auth
def api_session(sid):
    p = storage.load_processed(sid)
    meta = storage.get_session_meta(sid)
    if not p or not meta:
        abort(404)
    core = set(p["meta"].get("lap_channels", []))
    lap_data = {n: {"dist": d["dist"], "time": d["time"], "x": d["x"], "y": d["y"],
                    "channels": {k: v for k, v in d["channels"].items() if k in core}}
                for n, d in p["lap_data"].items()}
    return jsonify({
        "meta": p["meta"],
        "track": meta["track"], "car": meta["car"], "driver": meta["uploader"],
        "laps": p["laps"],
        "lap_data": lap_data,
        "best_lap": p["best_lap"], "best_lap_str": p["best_lap_str"],
    })


@app.route("/api/lapchannel/<sid>/<int:lapn>/<name>")
@require_auth
def api_lapchannel(sid, lapn, name):
    """Un canale qualsiasi di un giro (ricampionato per distanza), su richiesta."""
    p = storage.load_processed(sid)
    if not p or str(lapn) not in p["lap_data"]:
        abort(404)
    ch = p["lap_data"][str(lapn)]["channels"].get(name)
    if ch is None:
        abort(404)
    return jsonify({"name": name, "values": ch})


@app.route("/api/track/<path:track>")
@require_auth
def api_track(track):
    """Tutte le sessioni (e i loro giri completi) sulla stessa pista, per il confronto."""
    out = []
    for s in storage.sessions_by_track(track):
        p = storage.load_processed(s["id"])
        if not p:
            continue
        laps = [{"n": l["n"], "time_str": l["time_str"], "time": l["time"],
                 "v_max": l.get("v_max")} for l in p["laps"] if l["complete"]]
        if laps:
            out.append({"id": s["id"], "driver": s["uploader"], "car": s["car"],
                        "date": s["date"], "time": s["time"], "laps": laps})
    return jsonify({"track": track, "sessions": out})


@app.route("/api/lap/<sid>/<int:lapn>")
@require_auth
def api_lap(sid, lapn):
    """Dati di un singolo giro (per distanza) di una sessione, per la sovrapposizione."""
    p = storage.load_processed(sid)
    meta = storage.get_session_meta(sid)
    if not p or not meta or str(lapn) not in p["lap_data"]:
        abort(404)
    lap = next((l for l in p["laps"] if l["n"] == lapn), {})
    core = set(p["meta"].get("lap_channels", []))
    d = p["lap_data"][str(lapn)]
    data = {"dist": d["dist"], "time": d["time"], "x": d["x"], "y": d["y"],
            "channels": {k: v for k, v in d["channels"].items() if k in core}}
    return jsonify({
        "sid": sid, "lap": lapn,
        "driver": meta["uploader"], "car": meta["car"],
        "time_str": lap.get("time_str", "-"), "time": lap.get("time"),
        "stats": {k: lap.get(k) for k in ("v_max", "v_min", "v_avg", "rpm_max", "full_throttle_pct")},
        "data": data,
    })


@app.route("/healthz")
def healthz():
    return "ok"


# ---------------------------------------------------------------- coach AI
@app.route("/coach")
@require_auth
def coach_view():
    return render_template("coach.html", driver=request.user.title())


@app.route("/api/coach", methods=["POST"])
@require_auth
def api_coach():
    d = request.get_json(silent=True) or {}
    messages = d.get("messages")
    if not messages:                                  # retrocompatibilita': singola domanda
        q = (d.get("question") or "").strip()
        if not q:
            return jsonify(error="Scrivi una domanda."), 400
        messages = [{"role": "user", "content": q}]
    return jsonify(coach.chat(messages, driver=request.user.title(), use_data=bool(d.get("use_data"))))


@app.route("/corners")
@require_auth
def corners_view():
    track = request.args.get("track", "")
    cmap = coach.get_or_build_corners(track) if track else []
    ref = coach.reference_path(track) if track else None
    tracks = sorted({s["track"] for s in storage.list_sessions() if s["track"]})
    return render_template("corners.html", track=track, corners=cmap, ref=ref, tracks=tracks)


@app.route("/api/corners", methods=["POST"])
@require_auth
def api_corners_save():
    d = request.json or {}
    track = d.get("track")
    cs = d.get("corners")
    if not track or cs is None:
        return jsonify(error="dati mancanti"), 400
    for i, c in enumerate(cs, 1):
        c["n"] = i
    storage.save_corners(track, cs)
    return jsonify(ok=True, corners=cs)


@app.route("/api/corners/rebuild", methods=["POST"])
@require_auth
def api_corners_rebuild():
    track = (request.json or {}).get("track")
    if not track:
        return jsonify(error="track mancante"), 400
    storage.save_corners(track, [])      # azzera
    cs = coach.get_or_build_corners(track)
    return jsonify(ok=True, corners=cs)


# ---------------------------------------------------------------- setup
@app.route("/api/ingest-setup", methods=["POST"])
def api_ingest_setup():
    token = os.environ.get("INGEST_TOKEN")
    if not token:
        return jsonify(error="ingest disabilitato"), 503
    if request.headers.get("X-Ingest-Token") != token:
        return jsonify(error="token non valido"), 401
    uploader = request.form.get("uploader", "agent")
    fs = request.files.getlist("files") + ([request.files["file"]] if "file" in request.files else [])
    f = next((x for x in fs if x and x.filename), None)
    if not f:
        return jsonify(error="nessun file"), 400
    raw = f.read()
    import hashlib
    sha = hashlib.sha256(raw).hexdigest()
    ex = storage.find_setup_by_sha(sha)
    if ex:
        return jsonify(id=ex, duplicate=True, status="ok")
    try:
        parsed = carsetup.parse(raw)
    except Exception as e:
        return jsonify(error=f"parse: {e}"), 400
    name = os.path.splitext(os.path.basename(f.filename))[0]
    car = request.form.get("car") or None
    track = request.form.get("track") or None
    sid = storage.save_setup(raw, parsed, name, uploader, sha, car=car, track=track)
    return jsonify(id=sid, duplicate=False, status="ok")


@app.route("/setups")
@require_auth
def setups_view():
    norm = lambda x: (x or "").strip().lower()
    by_driver = {}
    for s in storage.list_setups():
        e = by_driver.setdefault(norm(s["uploader"]), {"display": s["uploader"] or "—", "cars": {}})
        e["cars"].setdefault(s["car"] or "—", {}).setdefault(s["track"] or "—", []).append(s)

    def pack(display, entry):
        cars = []
        if entry:
            for cn in sorted(entry["cars"]):
                tracks = [{"track": tn, "setups": entry["cars"][cn][tn]}
                          for tn in sorted(entry["cars"][cn])]
                cars.append({"car": cn, "tracks": tracks})
        return {"driver": display, "cars": cars}

    columns, used = [], set()
    for name in _driver_columns():
        k = norm(name); used.add(k)
        columns.append(pack(name, by_driver.get(k)))
    for k, e in by_driver.items():
        if k not in used:
            columns.append(pack(e["display"], e))
    n = sum(len(t["setups"]) for c in columns for car in c["cars"] for t in car["tracks"])
    return render_template("setups.html", columns=columns, n=n)


@app.route("/api/setup/<sid>")
@require_auth
def api_setup(sid):
    s = storage.get_setup(sid)
    if not s:
        abort(404)
    return jsonify({"id": sid, "name": s["name"], "car": s["car"],
                    "uploader": s["uploader"], "params": json.loads(s["params"])})


@app.route("/setups/<sid>/download")
@require_auth
def setup_download(sid):
    s = storage.get_setup(sid)
    if not s:
        abort(404)
    return send_file(storage.setup_file(sid), as_attachment=True,
                     download_name=(s["name"] or "setup") + ".carsetup")


@app.route("/setups/<sid>/delete", methods=["POST"])
@require_auth
def setup_delete(sid):
    storage.delete_setup(sid)
    return redirect(url_for("setups_view"))


def _token_ok():
    tok = os.environ.get("INGEST_TOKEN")
    return tok and request.headers.get("X-Ingest-Token") == tok


@app.route("/api/setups-manifest")
def api_setups_manifest():
    """Elenco setup (per l'agente che sincronizza in download). Auth a token."""
    if not _token_ok():
        return jsonify(error="token non valido"), 401
    items = [{"id": s["id"], "car": s["car"], "track": s["track"], "name": s["name"],
              "uploader": s["uploader"], "sha": s["sha"]} for s in storage.list_setups()]
    return jsonify(setups=items)


@app.route("/api/setup-file/<sid>")
def api_setup_file(sid):
    if not _token_ok():
        return jsonify(error="token non valido"), 401
    s = storage.get_setup(sid)
    if not s:
        abort(404)
    return send_file(storage.setup_file(sid), as_attachment=False,
                     download_name=(s["name"] or "setup") + ".carsetup")


# ---------------------------------------------------------------- ingest agente
@app.route("/api/ingest", methods=["POST"])
def api_ingest():
    """Endpoint usato dall'agente locale. Auth via header X-Ingest-Token."""
    token = os.environ.get("INGEST_TOKEN")
    if not token:
        return jsonify(error="ingest disabilitato (INGEST_TOKEN non impostato)"), 503
    if request.headers.get("X-Ingest-Token") != token:
        return jsonify(error="token non valido"), 401

    uploader = request.form.get("uploader", "agent")
    files = request.files.getlist("files")
    ld_path = ldx_path = orig = None
    tmp = tempfile.mkdtemp()
    for f in files:
        if not f.filename:
            continue
        dest = os.path.join(tmp, os.path.basename(f.filename))
        f.save(dest)
        if f.filename.lower().endswith(".ld"):
            ld_path, orig = dest, os.path.basename(f.filename)
        elif f.filename.lower().endswith(".ldx"):
            ldx_path = dest
    if not ld_path:
        return jsonify(error="nessun file .ld"), 400
    if not ldx_path:
        cand = ld_path[:-3] + ".ldx"
        if os.path.exists(cand):
            ldx_path = cand
    try:
        sid, dup = _ingest(ld_path, ldx_path, orig, uploader)
    except Exception as e:
        return jsonify(error=f"parsing: {e}"), 400
    return jsonify(id=sid, duplicate=dup, status="ok")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
