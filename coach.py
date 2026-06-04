"""Coach AI: identifica pista/auto/curva dalla domanda, raccoglie i dati reali
(metriche per-curva del pilota e dei compagni, mappa curve, setup) e interroga
l'API di Claude per dare consigli di guida e setup."""
import os
import re
import json
import requests

import storage
import corners as C

# Riferimento curve ufficiali per piste note: nro curve e nomi (in ordine di giro).
# La corrispondenza con la pista avviene per parole chiave nel nome.
TRACK_REF = {
    "red bull": {"count": 10, "names": [
        "1 - Niki Lauda", "2", "3 - Remus", "4", "5", "6", "7", "8", "9", "10 - Rindt"]},
    "spielberg": {"count": 10, "names": [
        "1 - Niki Lauda", "2", "3 - Remus", "4", "5", "6", "7", "8", "9", "10 - Rindt"]},
    "spa": {"count": 19, "names": [
        "1 - La Source", "2 - Eau Rouge", "3 - Raidillon", "4 - Kemmel", "5 - Les Combes",
        "6 - Les Combes", "7 - Malmedy", "8 - Bruxelles", "9 - Speaker's", "10 - Pouhon",
        "11 - Pouhon", "12 - Fagnes", "13 - Fagnes", "14 - Campus", "15 - Stavelot",
        "16 - Paul Frere", "17 - Blanchimont", "18 - Bus Stop", "19 - Bus Stop"]},
}


def track_reference(track):
    t = (track or "").lower()
    for key, ref in TRACK_REF.items():
        if key in t:
            return ref
    return None

SYSTEM = (
    "Sei un ingegnere di pista e coach di sim racing, esperto di Assetto Corsa EVO. "
    "Rispondi in italiano, in modo conciso e pratico. Ricevi dati REALI di telemetria "
    "per-curva del pilota e dei compagni di squadra, la mappa delle curve della pista e, "
    "se disponibile, il setup dell'auto. Basa i consigli sui numeri forniti: prima la "
    "tecnica di guida (punto di frenata, traiettoria, velocita' di apice, gestione del gas), "
    "poi le modifiche al setup pertinenti al problema descritto "
    "(es. sovrasterzo in trazione -> differenziale in power/coast, rigidita' e ammortizzatori "
    "posteriori, convergenza posteriore, ala). Confronta col compagno piu' veloce in quella "
    "curva quando i dati ci sono. Non inventare numeri: se mancano dati, dillo chiaramente."
)


def _norm(s):
    return (s or "").strip().lower()


def _fastest_lap_key(payload):
    bl = payload.get("best_lap")
    ld = payload.get("lap_data") or {}
    if bl and str(bl) in ld:
        return str(bl)
    return next(iter(ld), None)


def get_or_build_corners(track):
    """Mappa curve della pista: se non c'e', la costruisce dal giro piu' veloce
    disponibile, puntando al numero ufficiale di curve quando la pista e' nota."""
    cur = storage.get_corners(track)
    if cur:
        return cur
    ref = track_reference(track)
    target = ref["count"] if ref else None
    sess = storage.sessions_by_track(track)        # gia' ordinate per best_lap_str
    for meta in sess:
        payload = storage.load_processed(meta["id"])
        if not payload:
            continue
        key = _fastest_lap_key(payload)
        if not key:
            continue
        lap = payload["lap_data"][key]
        det = C.detect_corners(lap, target=target)
        if not det:
            continue
        names = None
        if ref and len(det) == ref["count"]:        # nomi ufficiali solo se il conteggio combacia
            names = ref["names"]
        data = [{"n": i + 1,
                 "name": names[i] if names else f"Curva {i+1}",
                 "dist_frac": c["dist_frac"]} for i, c in enumerate(det)]
        storage.save_corners(track, data)
        return data
    return []


def _driver_best_meta(driver, track, car=None):
    cand = [s for s in storage.list_sessions()
            if _norm(s["uploader"]) == _norm(driver) and s["track"] == track
            and (car is None or s["car"] == car)]
    if not cand:
        return None
    cand.sort(key=lambda s: s["best_lap_str"])
    return cand[0]


def _corner_table(meta, cmap):
    payload = storage.load_processed(meta["id"])
    if not payload:
        return None
    key = _fastest_lap_key(payload)
    lap = payload["lap_data"][key]
    rows = []
    for c in cmap:
        rows.append({"n": c["n"], "name": c.get("name", f"Curva {c['n']}"),
                     **C.corner_metrics(lap, c["dist_frac"])})
    return {"best_lap": meta["best_lap_str"], "curve": rows}


def _find_track(question, drivers_recent_track):
    tracks = sorted({s["track"] for s in storage.list_sessions() if s["track"]}, key=len, reverse=True)
    q = question.lower()
    for t in tracks:
        toks = [w for w in re.split(r"[^a-z0-9]+", t.lower()) if len(w) >= 3]
        if any(tok in q for tok in toks):
            return t
    return drivers_recent_track


def _find_corner_num(question):
    m = re.search(r"\b(?:curva|curve|turn|t|alla|alle)\s*(\d{1,2})\b", question.lower())
    if m:
        return int(m.group(1))
    m = re.search(r"\b(\d{1,2})\b", question)
    return int(m.group(1)) if m else None


def build_context(driver_display, question):
    sess_all = storage.list_sessions()
    mine = [s for s in sess_all if _norm(s["uploader"]) == _norm(driver_display)]
    recent_track = mine[0]["track"] if mine else (sess_all[0]["track"] if sess_all else None)

    track = _find_track(question, recent_track)
    if not track:
        return None, "Non trovo sessioni: caricane qualcuna prima di chiedere consigli."

    car = None
    my_here = [s for s in mine if s["track"] == track]
    if my_here:
        my_here.sort(key=lambda s: s["best_lap_str"])
        car = my_here[0]["car"]

    cmap = get_or_build_corners(track)
    cnum = _find_corner_num(question)
    if cnum and cmap:
        cmap_focus = [c for c in cmap if c["n"] == cnum] or cmap
    else:
        cmap_focus = cmap

    ctx = {"pilota": driver_display, "pista": track, "auto": car,
           "curva_chiesta": cnum, "mappa_curve": [{"n": c["n"], "name": c.get("name")} for c in cmap]}

    my_meta = _driver_best_meta(driver_display, track, car)
    if my_meta:
        ctx["tuoi_dati"] = _corner_table(my_meta, cmap_focus)

    teammates = {}
    for s in sess_all:
        dn = s["uploader"]
        if _norm(dn) == _norm(driver_display) or s["track"] != track:
            continue
        if dn not in teammates:
            tm = _driver_best_meta(dn, track, car) or _driver_best_meta(dn, track, None)
            if tm:
                teammates[dn] = _corner_table(tm, cmap_focus)
    if teammates:
        ctx["compagni"] = teammates

    if car:
        for st in storage.list_setups():
            if st["car"] == car and (st["track"] in (track, None, "") or True):
                params = json.loads(st["params"])
                ctx["setup_auto"] = {"nome": st["name"], "di": st["uploader"],
                                     "parametri": [{"g": p["group"], "ang": p["corner"],
                                                    "v": p["label"], "val": p["value"]} for p in params]}
                break

    return ctx, None


def reference_path(track):
    """Traiettoria di riferimento (giro piu' veloce) + posizione apici, per la mappa editabile."""
    cmap = get_or_build_corners(track)
    for meta in storage.sessions_by_track(track):
        payload = storage.load_processed(meta["id"])
        if not payload:
            continue
        key = _fastest_lap_key(payload)
        if not key:
            continue
        lap = payload["lap_data"][key]
        x, y = lap.get("x"), lap.get("y")
        if not x:
            continue
        n = len(x)
        step = max(1, n // 240)
        dd = lap["dist"]; total = dd[-1] or 1.0
        pts = [[round(float(x[i]), 1), round(float(y[i]), 1), round(float(dd[i] / total), 4)]
               for i in range(0, n, step)]
        apex = []
        for c in cmap:
            idx = C._idx_at_frac(lap["dist"], c["dist_frac"])
            apex.append({"n": c["n"], "name": c.get("name", f"Curva {c['n']}"),
                         "x": round(float(x[idx]), 1), "y": round(float(y[idx]), 1)})
        ref = track_reference(track)
        return {"points": pts, "apexes": apex,
                "official": ref["names"] if ref else None}
    return None


def ask(driver_display, question):
    ctx, err = build_context(driver_display, question)
    if err:
        return {"error": err}
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return {"error": "AI non configurata: imposta ANTHROPIC_API_KEY su Railway.",
                "context": ctx}
    model = os.environ.get("COACH_MODEL", "claude-sonnet-4-6")
    user_text = (f"Domanda di {driver_display}:\n{question}\n\n"
                 f"Dati disponibili (JSON):\n{json.dumps(ctx, ensure_ascii=False)}")
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
                          headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                   "content-type": "application/json"},
                          json={"model": model, "max_tokens": 1024,
                                "system": SYSTEM,
                                "messages": [{"role": "user", "content": user_text}]},
                          timeout=90)
    except requests.RequestException as e:
        return {"error": f"Errore di rete verso l'API: {e}"}
    if r.status_code != 200:
        return {"error": f"API Claude {r.status_code}: {r.text[:300]}"}
    data = r.json()
    answer = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    return {"answer": answer, "pista": ctx.get("pista"), "auto": ctx.get("auto"),
            "curva": ctx.get("curva_chiesta")}
