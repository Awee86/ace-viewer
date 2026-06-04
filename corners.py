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


def detect_corners(dist, speed, min_sep_m=120.0, prominence=12.0):
    """Trova gli apici (minimi di velocita' prominenti) lungo il giro.
    Ritorna lista ordinata di {idx, dist_frac}."""
    d = np.asarray(dist, float)
    v = _smooth(speed, 7)
    n = len(v)
    if n < 10 or d[-1] <= 0:
        return []
    cand = [i for i in range(2, n - 2)
            if v[i] <= v[i-1] and v[i] <= v[i+1] and v[i] < v[i-2] and v[i] < v[i+2]]
    pro = []
    for i in cand:
        lo, hi = max(0, i - 50), min(n, i + 50)
        lmax = max(v[lo:i+1].max(), v[i:hi].max())
        if lmax - v[i] >= prominence:
            pro.append(i)
    filt = []
    for i in pro:
        if filt and (d[i] - d[filt[-1]]) < min_sep_m:
            if v[i] < v[filt[-1]]:
                filt[-1] = i
        else:
            filt.append(i)
    total = d[-1]
    return [{"idx": int(i), "dist_frac": round(float(d[i] / total), 4)} for i in filt]


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
    cs = detect_corners(lap["dist"], lap["channels"]["SPEED"])
    print(f"giro {bl}, lunghezza {lap['dist'][-1]:.0f} m, curve rilevate: {len(cs)}")
    for i, c in enumerate(cs, 1):
        met = corner_metrics(lap, c["dist_frac"])
        print(f"  Curva {i:2}  @{c['dist_frac']*100:4.1f}%  "
              f"apice {met['v_apice']:5.1f} km/h  ingresso {met['v_ingresso']:5.1f}  "
              f"uscita {met['v_uscita']:5.1f}  gas pieno +{met.get('gas_pieno_dopo_apice_m','?')}m")
