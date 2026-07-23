"""Elaborazione telemetria: resampling su base comune, mappa per dead-reckoning,
rilevamento giri per gate-crossing, statistiche per giro/sessione."""
import numpy as np
from ldparser import LD, read_ldx_beacons

BASE_FS = 50.0  # Hz, base temporale comune per grafici/mappa

# Canali inviati subito al client (gli altri si caricano on-demand).
CORE_CHANNELS = [
    "SPEED", "THROTTLE", "BRAKE", "RPMS", "GEAR",
    "STEERANGLE", "G_LAT", "G_LON", "FUEL",
]


def _resample(ch, tg):
    t = np.arange(ch.n) / ch.freq
    return np.interp(tg, t, ch.data).astype(np.float32)


def dead_reckon(t, v, yaw):
    """Ricostruzione traiettoria (x,y) da velocita' [m/s] e yaw rate [rad/s]."""
    dt = np.gradient(t)
    head = np.cumsum(yaw * dt)
    x = np.cumsum(v * np.sin(head) * dt)
    y = np.cumsum(v * np.cos(head) * dt)
    return x, y


def detect_lap_crossings(t, x, y, gate_t):
    """Trova i tempi in cui la traiettoria attraversa una 'porta' definita
    nel punto raggiunto a gate_t, nella stessa direzione di marcia."""
    gi = int(np.argmin(np.abs(t - gate_t)))
    gi = max(1, min(gi, len(t) - 2))
    P = np.array([x[gi], y[gi]])
    d = np.array([x[gi + 1] - x[gi - 1], y[gi + 1] - y[gi - 1]])
    nd = np.linalg.norm(d)
    if nd == 0:
        return [gate_t]
    d /= nd
    rel = np.column_stack([x - P[0], y - P[1]])
    proj = rel @ d
    lat = rel @ np.array([-d[1], d[0]])
    crossings = []
    for i in range(1, len(proj)):
        if proj[i - 1] < 0 <= proj[i] and abs(lat[i]) < 40:
            if not crossings or (t[i] - crossings[-1]) > 20:  # anti-rimbalzo
                crossings.append(float(t[i]))
    return crossings if crossings else [float(gate_t)]


def _fmt_lap(sec):
    m = int(sec // 60)
    return "%d:%06.3f" % (m, sec - 60 * m)


def optimal_lap(payload, n=3):
    """Giro ottimale: somma dei migliori n settori (per distanza) tra i giri completi.
    Ritorna None se non ci sono giri completi sufficienti."""
    laps = [l for l in payload.get("laps", []) if l.get("complete")]
    ld = payload.get("lap_data", {})
    best = [None] * n          # (tempo_settore, n_giro) per settore
    per_lap = {}
    for l in laps:
        kk = str(l["n"])
        if kk not in ld:
            continue
        dist = np.asarray(ld[kk]["dist"], float)
        time = np.asarray(ld[kk]["time"], float)
        if len(dist) < n + 1 or dist[-1] <= 0:
            continue
        L = dist[-1]
        bounds = [0.0] + [L * i / n for i in range(1, n)] + [L]
        tb = np.interp(bounds, dist, time)
        secs = [float(tb[i + 1] - tb[i]) for i in range(n)]
        per_lap[l["n"]] = [round(s, 3) for s in secs]
        for i, s in enumerate(secs):
            if best[i] is None or s < best[i][0]:
                best[i] = (s, l["n"])
    if any(b is None for b in best):
        return None
    opt = sum(b[0] for b in best)
    return {
        "time": round(opt, 3), "time_str": _fmt_lap(opt),
        "sectors": [{"i": i + 1, "time": round(b[0], 3),
                     "time_str": _fmt_lap(b[0]), "lap": b[1]} for i, b in enumerate(best)],
        "per_lap": per_lap,
    }


def _cumtrapz(y, t):
    dt = np.diff(t)
    seg = (y[1:] + y[:-1]) / 2 * dt
    return np.concatenate([[0.0], np.cumsum(seg)])


# canali inclusi nei dati per-giro (confronto)
LAP_CHANNELS = ["SPEED", "THROTTLE", "BRAKE", "RPMS", "GEAR", "STEERANGLE", "G_LAT", "G_LON"]
N_LAP = 500  # punti per giro (griglia per distanza)


def _lap_resample(tg, channels, x, y, t0, t1):
    """Ricampiona un giro su una griglia di N_LAP punti uniformi in distanza dal traguardo."""
    mask = (tg >= t0) & (tg < t1)
    if mask.sum() < 4:
        return None
    t_lap = tg[mask] - t0
    spd_kmh = channels["SPEED"]["values"][mask]
    v_ms = spd_kmh / 3.6
    dist = _cumtrapz(v_ms, t_lap)          # metri dal traguardo
    dtot = dist[-1]
    if dtot <= 0:
        return None
    # griglia uniforme in distanza
    dgrid = np.linspace(0, dtot, N_LAP)
    out = {
        "dist": dgrid,
        "time": np.interp(dgrid, dist, t_lap),     # tempo cumulato per delta
        "x": np.interp(dgrid, dist, x[mask]),
        "y": np.interp(dgrid, dist, y[mask]),
        "channels": {},
    }
    out["x"] = out["x"] - out["x"][0]
    out["y"] = out["y"] - out["y"][0]
    for name in channels:                       # tutti i canali, per il selettore completo
        out["channels"][name] = np.interp(dgrid, dist, channels[name]["values"][mask])
    return out


def _lap_stats(tg, channels, t0, t1):
    mask = (tg >= t0) & (tg < t1)
    spd = channels.get("SPEED", {}).get("values")
    rpm = channels.get("RPMS", {}).get("values")
    thr = channels.get("THROTTLE", {}).get("values")
    s = {}
    if spd is not None and mask.any():
        seg = spd[mask]
        s["v_max"] = round(float(seg.max()), 1)
        s["v_min"] = round(float(seg.min()), 1)
        s["v_avg"] = round(float(seg.mean()), 1)
    if rpm is not None and mask.any():
        s["rpm_max"] = round(float(rpm[mask].max()), 0)
    if thr is not None and mask.any():
        s["full_throttle_pct"] = round(float((thr[mask] >= 98).mean() * 100), 0)
    return s


def _stats(seg):
    seg = seg[np.isfinite(seg)]
    if seg.size == 0:
        return {"min": 0, "max": 0, "avg": 0}
    return {"min": round(float(seg.min()), 2),
            "max": round(float(seg.max()), 2),
            "avg": round(float(seg.mean()), 2)}


def process(ld_path, ldx_path=None):
    """Elabora una sessione e restituisce il payload completo (dict serializzabile)."""
    ld = LD(ld_path)
    if not ld.channels:
        raise ValueError("Nessun dato nei canali (sessione vuota).")

    dur = ld.duration
    meta_date, meta_time = ld.date, ld.time
    tg = np.arange(0, dur, 1.0 / BASE_FS)

    # tutti i canali ricampionati sulla base comune; libero i dati grezzi man mano
    # (una sessione lunga -es. F1- terrebbe altrimenti in RAM tutti i canali due volte)
    channels = {}
    for c in ld.channels:
        vals = _resample(c, tg)
        if c.name == "SPEED" and (c.unit or "").lower() in ("m/s", ""):
            channels["SPEED"] = {"unit": "km/h", "values": vals * np.float32(3.6)}
        else:
            channels[c.name] = {"unit": c.unit, "values": vals}
    del ld                       # non serve piu': libera l'oggetto e i canali grezzi

    # mappa (dead-reckoning): riuso i canali gia' ricampionati (niente seconda copia)
    sp = channels.get("SPEED")
    ro = channels.get("ROTY")
    if sp is not None and ro is not None:
        v = np.asarray(sp["values"], dtype=np.float32) / np.float32(3.6)   # m/s
        w = np.asarray(ro["values"], dtype=np.float32)                     # rad/s
        x, y = dead_reckon(tg, v, w)
        x = x.astype(np.float32); y = y.astype(np.float32)
        del v, w
    else:
        x = y = np.zeros_like(tg, dtype=np.float32)

    # giri: i tempi vengono SEMPRE dai beacon del .ldx (istanti di passaggio sul traguardo
    # salvati dal gioco). Nessuna ricostruzione: se mancano, la sessione non e' cronometrabile.
    beacons = read_ldx_beacons(ldx_path) if ldx_path else []
    if len(beacons) < 2:
        n = len(beacons)
        raise ValueError(
            f"Tempi non leggibili dal file: il .ldx contiene solo {n} "
            f"passaggi sul traguardo (ne servono almeno 2 per un giro). "
            f"Assicurati che accanto al .ld ci sia il .ldx completo della sessione.")
    crossings = beacons

    # distanza cumulata (m) integrando la velocita': serve a capire quali intervalli
    # tra due beacon sono davvero un giro completo (esclude out-lap, rientri, passaggi spuri)
    sp_kmh = channels.get("SPEED", {}).get("values")
    cumd = None
    if sp_kmh is not None and len(sp_kmh) == len(tg) and len(tg) > 1:
        sp_ms = np.asarray(sp_kmh, float) / 3.6
        cumd = np.concatenate([[0.0], np.cumsum(sp_ms[:-1] * np.diff(tg))])

    def seg_dist(a, b):
        if cumd is None:
            return None
        return float(np.interp(b, tg, cumd) - np.interp(a, tg, cumd))

    seg_dists = [seg_dist(crossings[i], crossings[i + 1]) for i in range(len(crossings) - 1)]
    ref_dist = 0.0
    valid_dists = [d for d in seg_dists if d and d > 0]
    if valid_dists:
        ref_dist = float(np.median(valid_dists))

    seg_times = [crossings[i + 1] - crossings[i] for i in range(len(crossings) - 1)]
    dist_ok_times = [seg_times[i] for i in range(len(seg_times))
                     if seg_dists[i] and ref_dist > 0
                     and 0.75 * ref_dist <= seg_dists[i] <= 1.25 * ref_dist]
    # riferimento = giro piu' veloce (robusto anche con pochi giri): i giri-box hanno
    # tempo molto maggiore e vengono scartati
    ref_time = min(dist_ok_times) if dist_ok_times else (min(seg_times) if seg_times else 0.0)

    def is_full_lap(i):
        d = seg_dists[i]
        if d is None or ref_dist <= 0:      # senza velocita' non filtro
            return True
        if not (d > 500 and 0.75 * ref_dist <= d <= 1.25 * ref_dist):
            return False
        if ref_time > 0 and (crossings[i + 1] - crossings[i]) > 1.8 * ref_time:
            return False                    # rientro/sosta ai box: non e' un giro
        return True

    laps = []
    bounds = crossings
    lap_data = {}
    for i in range(len(bounds) - 1):
        t0, t1 = bounds[i], bounds[i + 1]
        complete = is_full_lap(i)
        st = _lap_stats(tg, channels, t0, t1)
        lap = {
            "n": i + 1,
            "t0": round(t0, 3),
            "t1": round(t1, 3),
            "time": round(t1 - t0, 3),
            "time_str": _fmt_lap(t1 - t0) if complete else "-",
            "complete": complete,
        }
        lap.update(st)
        laps.append(lap)
        if complete:
            ld_lap = _lap_resample(tg, channels, x, y, t0, t1)
            if ld_lap:
                lap_data[str(i + 1)] = ld_lap

    best = min((l for l in laps if l["complete"]), key=lambda l: l["time"], default=None)

    # meteo (se disponibile): temperatura aria e asfalto
    weather = {}
    if "AIR_TEMP" in channels:
        weather["air_temp"] = round(float(np.nanmean(channels["AIR_TEMP"]["values"])), 1)
    if "ROAD_TEMP" in channels:
        weather["road_temp"] = round(float(np.nanmean(channels["ROAD_TEMP"]["values"])), 1)

    return {
        "meta": {
            "date": meta_date, "time": meta_time,
            "duration": round(dur, 1),
            "n_samples": len(tg), "fs": BASE_FS,
            "channel_names": sorted(channels.keys()),
            "n_beacons": len(beacons),
            "lap_channels": [c for c in LAP_CHANNELS if c in channels],
            "n_lap_points": N_LAP,
            "weather": weather,
        },
        "t": tg,
        "x": x, "y": y,
        "channels": channels,        # dict name -> {unit, values(np)}
        "laps": laps,
        "lap_data": lap_data,        # dict "lapN" -> {dist,time,x,y,channels} per il confronto
        "best_lap": best["n"] if best else None,
        "best_lap_str": best["time_str"] if best else "-",
        "best_lap_vmax": best.get("v_max") if best else None,
    }
