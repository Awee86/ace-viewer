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
    return np.interp(tg, t, ch.data)


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
    tg = np.arange(0, dur, 1.0 / BASE_FS)

    # tutti i canali ricampionati sulla base comune
    channels = {}
    for c in ld.channels:
        vals = _resample(c, tg)
        if c.name == "SPEED" and (c.unit or "").lower() in ("m/s", ""):
            channels["SPEED"] = {"unit": "km/h", "values": vals * 3.6}
        else:
            channels[c.name] = {"unit": c.unit, "values": vals}

    # mappa (dead-reckoning)
    spd = ld.get("SPEED")
    yaw = ld.get("ROTY")
    if spd is not None and yaw is not None:
        v = _resample(spd, tg)            # m/s
        w = _resample(yaw, tg)            # rad/s
        x, y = dead_reckon(tg, v, w)
    else:
        x = y = np.zeros_like(tg)

    # giri
    beacons = read_ldx_beacons(ldx_path) if ldx_path else []
    if len(beacons) >= 2:
        # i beacon dell'.ldx sono il riferimento esatto del traguardo: usali direttamente
        crossings = beacons
    else:
        # ripiego: nessun (o un solo) beacon -> ricostruisco i passaggi dalla mappa
        spd_ch = channels.get("SPEED", {}).get("values", tg)
        gate_t = beacons[0] if beacons else float(tg[int(np.argmax(spd_ch))])
        crossings = detect_lap_crossings(tg, x, y, gate_t)

    laps = []
    if len(crossings) >= 2:
        bounds = crossings
    else:
        bounds = [float(tg[0]), float(tg[-1])]  # sessione intera come unico segmento
    complete = len(crossings) >= 2
    lap_data = {}
    for i in range(len(bounds) - 1):
        t0, t1 = bounds[i], bounds[i + 1]
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
            "date": ld.date, "time": ld.time,
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
