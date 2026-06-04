"""Rilevamento automatico delle curve da un giro (ricampionato in distanza) e
calcolo di metriche per-curva (ingresso, apice, riapertura gas, uscita).
Pura analisi numerica: niente dipendenze oltre numpy."""
import numpy as np


def _smooth(a, w=7):
    a = np.asarray(a, float)
    if len(a) < w or w < 2:
        return a
    k = np.ones(w) / w
    return np.convolve(a, k, mode="same")


def _zones(ag, d, thr, min_len_m):
    on = ag > thr
    n = len(on); runs = []; i = 0
    while i < n:
        if on[i]:
            j = i
            while j < n - 1 and (on[j + 1] or (j + 2 < n and on[j + 2]) or (j + 3 < n and on[j + 3])):
                j += 1
            runs.append((i, j)); i = j + 1
        else:
            i += 1
    return [(a, b) for a, b in runs if d[b] - d[a] >= min_len_m]


def _speed_minima(d, v, prom=10.0):
    n = len(v)
    out = []
    for i in range(2, n - 2):
        if v[i] <= v[i-1] and v[i] <= v[i+1] and v[i] < v[i-2] and v[i] < v[i+2]:
            lo, hi = max(0, i - 40), min(n, i + 40)
            if max(v[lo:i+1].max(), v[i:hi].max()) - v[i] >= prom:
                out.append(i)
    return out


def _apices(ag, d, v, thr, min_len_m, min_sep_m, extra=None):
    cs = [a + int(np.argmin(v[a:b + 1])) for a, b in _zones(ag, d, thr, min_len_m)]
    if extra:
        cs = sorted(set(cs) | set(extra))
    f = []
    for ai in sorted(cs):
        if f and d[ai] - d[f[-1]] < min_sep_m:
            if v[ai] < v[f[-1]]:
                f[-1] = ai
        else:
            f.append(ai)
    return f


def detect_corners(lap, target=None, thr=0.30, min_len_m=25.0, min_sep_m=55.0):
    """Rileva le curve unendo i tratti ad alta accelerazione laterale (curve veloci)
    e i minimi di velocita' prominenti (curve lente). Se 'target' (numero ufficiale)
    e' dato, cerca i parametri che si avvicinano di piu' (preferendo >= target)."""
    d = np.asarray(lap["dist"], float)
    v = _smooth(np.asarray(lap["channels"]["SPEED"], float), 5)
    n = len(v)
    if n < 10 or d[-1] <= 0:
        return []
    ch = lap["channels"]
    def _has(name):
        x = ch.get(name)
        return x is not None and len(x) > 0
    if _has("G_LAT"):
        ag = _smooth(np.abs(np.asarray(ch["G_LAT"], float)), 7)
    elif _has("STEERANGLE"):
        ag = _smooth(np.abs(np.asarray(ch["STEERANGLE"], float)), 7)
        ag = ag / (ag.max() or 1.0)
    else:
        vmax = v.max() or 1.0
        ag = (vmax - v) / vmax
    sm = _speed_minima(d, v)

    if target:
        best, best_err = None, 1e9
        for t in (0.50, 0.45, 0.40, 0.35, 0.32, 0.30, 0.28, 0.26, 0.24, 0.22):
            for ml in (38, 32, 28, 25, 22, 20):
                for sep in (95, 80, 70, 60, 55, 50, 46):
                    ap = _apices(ag, d, v, t, ml, sep, extra=sm)
                    err = abs(len(ap) - target)
                    better = err < best_err or (err == best_err and best is not None
                              and len(ap) >= target and len(best) < target)
                    if better:
                        best, best_err = ap, err
        ap = best or []
    else:
        ap = _apices(ag, d, v, thr, min_len_m, min_sep_m, extra=sm)

    total = d[-1]
    return [{"idx": int(i), "dist_frac": round(float(d[i] / total), 4)} for i in ap]


def _idx_at_frac(dist, frac):
    d = np.asarray(dist, float)
    return int(np.argmin(np.abs(d - frac * d[-1])))


def corner_metrics(lap, frac):
    """Metriche di una curva (alla frazione di giro 'frac') per un dato giro."""
    d = np.asarray(lap["dist"], float)
    v = np.asarray(lap["channels"]["SPEED"], float)
    thr = np.asarray(lap["channels"].get("THROTTLE", []), float)
    brk = np.asarray(lap["channels"].get("BRAKE", []), float)
    glat = np.asarray(lap["channels"].get("G_LAT", []), float)
    n = len(v)
    ai = _idx_at_frac(d, frac)
    lo, hi = max(0, ai - 30), min(n, ai + 30)
    j = lo + int(np.argmin(v[lo:hi]))
    m = {"v_apice": round(float(v[j]), 1),
         "v_ingresso": round(float(v[max(0, j - 25)]), 1),
         "v_uscita": round(float(v[min(n - 1, j + 30)]), 1)}
    if brk.size:
        start = j
        while start > 0 and brk[start] >= 8:
            start -= 1
        # start ora e' appena prima della frenata; cerca l'inizio reale
        s2 = start
        while s2 > 0 and brk[s2] < 8:
            s2 -= 1
        if s2 > 0:
            while s2 > 0 and brk[s2] >= 8:
                s2 -= 1
            m["frenata_prima_apice_m"] = round(float(d[j] - d[s2]), 0)
            m["v_inizio_frenata"] = round(float(v[s2]), 1)
    if thr.size:
        k = j
        while k < n - 1 and thr[k] < 90:
            k += 1
        m["gas_pieno_dopo_apice_m"] = round(float(d[k] - d[j]), 0)
    if glat.size:
        m["g_lat_max"] = round(float(np.nanmax(np.abs(glat[lo:hi]))), 2)
    return m


if __name__ == "__main__":
    import sys
    import analysis
    payload = analysis.process(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    bl = str(payload["best_lap"])
    lap = payload["lap_data"][bl]
    cs = detect_corners(lap, target=int(sys.argv[3]) if len(sys.argv) > 3 else None)
    print(f"giro {bl}, lunghezza {lap['dist'][-1]:.0f} m, curve rilevate: {len(cs)}")
    for i, c in enumerate(cs, 1):
        met = corner_metrics(lap, c["dist_frac"])
        print(f"  Curva {i:2}  @{c['dist_frac']*100:4.1f}%  "
              f"apice {met['v_apice']:5.1f} km/h  ingresso {met['v_ingresso']:5.1f}  "
              f"uscita {met['v_uscita']:5.1f}  gas pieno +{met.get('gas_pieno_dopo_apice_m','?')}m")
