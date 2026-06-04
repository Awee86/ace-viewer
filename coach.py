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


SYSTEM = (
    "Sei un coach e ingegnere di pista di sim racing, specializzato in Assetto Corsa EVO ma "
    "competente su guida, setup, gomme, strategia, telemetria e corse in generale. "
    "Parli italiano, in modo amichevole, diretto e concreto. Sei conversazionale: tieni conto "
    "di tutto lo scambio e fai domande quando ti servono dettagli per essere utile "
    "(auto, pista, gomme, cosa fa la macchina, in quale punto). "
    "Quando suggerisci modifiche al setup spiega brevemente il perche' e l'effetto atteso, e "
    "proponi un cambiamento alla volta cosi' e' testabile. Se l'utente ti da numeri o telemetria, "
    "usali; altrimenti ragiona sui principi senza inventare dati specifici."
)


def data_summary(driver):
    """Riepilogo COMPATTO e opzionale dei dati del pilota (per la spunta 'usa i miei dati')."""
    mine = [s for s in storage.list_sessions() if _norm(s["uploader"]) == _norm(driver)]
    if not mine:
        return "Nessuna sessione caricata da questo pilota."
    by = {}
    for s in mine:
        by.setdefault((s["track"], s["car"]), []).append(s["best_lap_str"])
    lines = [f"Dati di {driver} (best lap per pista/auto):"]
    for (trk, car), laps in sorted(by.items()):
        lines.append(f"- {trk} · {car}: {min(laps)}")
    # mappa curve note
    for trk in sorted({s["track"] for s in mine}):
        cm = storage.get_corners(trk)
        if cm:
            names = ", ".join(f"{c['n']}={c['name']}" for c in cm)
            lines.append(f"Curve {trk}: {names}")
    return "\n".join(lines)


def _resolve_track(name):
    tracks = sorted({s["track"] for s in storage.list_sessions() if s["track"]}, key=len, reverse=True)
    if not name:
        return tracks[0] if tracks else None
    nl = name.lower()
    for t in tracks:
        if t.lower() == nl:
            return t
    qtok = [w for w in re.split(r"[^a-z0-9]+", nl) if len(w) >= 3]
    for t in tracks:
        ttok = [w for w in re.split(r"[^a-z0-9]+", t.lower()) if len(w) >= 3]
        if any(w in ttok for w in qtok) or any(w in nl for w in ttok):
            return t
    return None


def _resolve_car(name, track):
    cars = sorted({s["car"] for s in storage.list_sessions()
                   if s["car"] and (track is None or s["track"] == track)}, key=len, reverse=True)
    if not name:
        return None
    nl = name.lower()
    for c in cars:
        if c.lower() == nl or nl in c.lower() or c.lower() in nl:
            return c
    qtok = [w for w in re.split(r"[^a-z0-9]+", nl) if len(w) >= 2]
    for c in cars:
        if any(w in c.lower() for w in qtok):
            return c
    return None


TOOLS = [
    {"name": "lista_sessioni",
     "description": "Elenca le sessioni caricate (pista, auto, miglior giro, giri, data). Filtra per pilota se indicato.",
     "input_schema": {"type": "object", "properties": {
         "pilota": {"type": "string", "description": "Nome pilota; vuoto = tutti"}}}},
    {"name": "analizza_best_lap",
     "description": "Metriche per-curva del miglior giro di un pilota su una pista/auto: velocita' ingresso/apice/uscita, distanza di frenata prima dell'apice, dove torna a gas pieno, g laterale max. Default pilota = utente corrente.",
     "input_schema": {"type": "object", "properties": {
         "pista": {"type": "string"}, "auto": {"type": "string"}, "pilota": {"type": "string"}},
         "required": ["pista"]}},
    {"name": "confronta_compagni",
     "description": "Confronta le metriche per-curva del miglior giro dell'utente con quelle dei compagni sulla stessa pista/auto.",
     "input_schema": {"type": "object", "properties": {
         "pista": {"type": "string"}, "auto": {"type": "string"}},
         "required": ["pista"]}},
    {"name": "leggi_setup",
     "description": "Parametri del setup di un'auto (pressioni, camber, molle, ammortizzatori, ali, ecc.).",
     "input_schema": {"type": "object", "properties": {
         "auto": {"type": "string"}, "pista": {"type": "string"}, "pilota": {"type": "string"}},
         "required": ["auto"]}},
]


def _h_lista(args, driver):
    who = args.get("pilota")
    out = []
    for s in storage.list_sessions():
        if who and _norm(s["uploader"]) != _norm(who):
            continue
        out.append({"pilota": s["uploader"], "pista": s["track"], "auto": s["car"],
                    "best": s["best_lap_str"], "giri": s["n_laps"], "data": s["date"]})
    return {"sessioni": out[:60]}


def _h_analizza(args, driver):
    track = _resolve_track(args.get("pista"))
    if not track:
        return {"errore": "pista non trovata tra le sessioni caricate"}
    pilota = args.get("pilota") or driver
    car = _resolve_car(args.get("auto"), track)
    meta = _driver_best_meta(pilota, track, car)
    if not meta:
        return {"errore": f"nessuna sessione di {pilota} su {track}" + (f" con {car}" if car else "")}
    tab = _corner_table(meta, get_or_build_corners(track))
    return {"pilota": pilota, "pista": track, "auto": meta["car"],
            "best_lap": meta["best_lap_str"], "v_max": meta.get("v_max"),
            "meteo": {"aria": meta.get("air_temp"), "asfalto": meta.get("road_temp")},
            "curve": tab["curve"] if tab else []}


def _h_confronta(args, driver):
    track = _resolve_track(args.get("pista"))
    if not track:
        return {"errore": "pista non trovata"}
    car = _resolve_car(args.get("auto"), track)
    cmap = get_or_build_corners(track)
    piloti = {}
    names = [driver] + sorted({s["uploader"] for s in storage.list_sessions()
                               if s["track"] == track and _norm(s["uploader"]) != _norm(driver)})
    for nm in names:
        meta = _driver_best_meta(nm, track, car) or _driver_best_meta(nm, track, None)
        if meta:
            tab = _corner_table(meta, cmap)
            piloti[nm] = {"best_lap": meta["best_lap_str"], "auto": meta["car"],
                          "curve": tab["curve"] if tab else []}
    if len(piloti) < 2:
        return {"avviso": "dati di un solo pilota disponibili per questa pista", "piloti": piloti}
    return {"pista": track, "piloti": piloti}


def _h_setup(args, driver):
    target_car = _resolve_car(args.get("auto"), None) or args.get("auto")
    cands = storage.list_setups()
    if target_car:
        tl = target_car.lower()
        cands = [s for s in cands if s["car"] and (tl in s["car"].lower() or s["car"].lower() in tl)] or storage.list_setups()
    if not cands:
        return {"errore": "nessun setup caricato"}
    cands.sort(key=lambda s: 0 if _norm(s["uploader"]) == _norm(args.get("pilota") or driver) else 1)
    s = cands[0]
    params = json.loads(s["params"])
    return {"auto": s["car"], "nome": s["name"], "di": s["uploader"], "pista": s.get("track"),
            "parametri": [{"gruppo": p["group"], "angolo": p["corner"],
                           "voce": p["label"], "valore": p["value"]} for p in params]}


_DISPATCH = {"lista_sessioni": _h_lista, "analizza_best_lap": _h_analizza,
             "confronta_compagni": _h_confronta, "leggi_setup": _h_setup}


def chat(messages, driver=None, use_data=False):
    """Chat libera multi-turno. Con use_data=True il coach ha STRUMENTI per leggere
    la telemetria per-curva, i setup e confrontare i piloti, su richiesta."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return {"error": "AI non configurata: imposta ANTHROPIC_API_KEY su Railway."}
    msgs = [{"role": m.get("role"), "content": m.get("content", "")}
            for m in messages if m.get("role") in ("user", "assistant") and m.get("content")][-24:]
    if not msgs or msgs[-1]["role"] != "user":
        return {"error": "Messaggio mancante."}
    system = SYSTEM
    tools = None
    if use_data and driver:
        tools = TOOLS
        system += (f"\n\nPilota corrente: {driver}. Hai strumenti per leggere i DATI REALI: "
                   "analizza_best_lap (telemetria per-curva), confronta_compagni, leggi_setup, "
                   "lista_sessioni. Quando l'utente chiede del suo giro, del setup o un confronto, "
                   "USA gli strumenti per ottenere i numeri e poi dai un parere concreto basato su quelli. "
                   "Non dire che non hai accesso ai dati: chiamali. Se uno strumento torna un errore, "
                   "spiega cosa manca (es. pista non caricata).")
    model = os.environ.get("COACH_MODEL", "claude-sonnet-4-6")

    for _ in range(6):
        payload = {"model": model, "max_tokens": 1100, "system": system, "messages": msgs}
        if tools:
            payload["tools"] = tools
        try:
            r = requests.post("https://api.anthropic.com/v1/messages",
                              headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                       "content-type": "application/json"},
                              json=payload, timeout=90)
        except requests.RequestException as e:
            return {"error": f"Errore di rete verso l'API: {e}"}
        if r.status_code != 200:
            return {"error": f"API Claude {r.status_code}: {r.text[:300]}"}
        data = r.json()
        blocks = data.get("content", [])
        tool_uses = [b for b in blocks if b.get("type") == "tool_use"]
        if not tool_uses:
            answer = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            return {"answer": answer}
        msgs.append({"role": "assistant", "content": blocks})
        results = []
        for tu in tool_uses:
            try:
                out = _DISPATCH.get(tu["name"], lambda a, d: {"errore": "strumento sconosciuto"})(tu.get("input", {}), driver)
            except Exception as e:
                out = {"errore": str(e)}
            results.append({"type": "tool_result", "tool_use_id": tu["id"],
                            "content": json.dumps(out, ensure_ascii=False)})
        msgs.append({"role": "user", "content": results})
    return {"answer": "Ho raccolto i dati ma non sono riuscito a concludere l'analisi, riprova a precisare pista e auto."}


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
