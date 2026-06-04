"""Parser dei file setup di Assetto Corsa EVO (.carsetup).
Formato: Protobuf (nessuno schema ufficiale pubblico). Decodifichiamo il wire format
in modo generico e mappiamo i gruppi a un albero leggibile e confrontabile.
Le etichette "amichevoli" sono dedotte dalla struttura e dai valori: dove non siamo
sicuri restano i percorsi strutturali (servono comunque per il confronto/diff)."""
import struct

CORNERS = ["AS", "AD", "PS", "PD"]   # anteriore sx/dx, posteriore sx/dx

# etichette dedotte per i sotto-campi dei gruppi ripetuti (per angolo)
SUB_LABELS = {
    "alza": {1: "Pressione (psi)", 2: "Camber (°)", 5: "Convergenza"},
    "molla": {1: "Rigidità molla"},
    "ammo": {1: "Bump", 2: "Bump (v)", 3: "Rebound", 4: "Rebound (v)"},
}


def _rv(b, i):
    s = r = 0
    while True:
        x = b[i]; i += 1; r |= (x & 0x7f) << s; s += 7
        if not x & 0x80:
            return r, i


def _decode(b, depth=0):
    i = 0; out = []
    while i < len(b):
        try:
            tag, i = _rv(b, i)
        except IndexError:
            break
        field, wt = tag >> 3, tag & 7
        if wt == 0:
            v, i = _rv(b, i); out.append((field, "int", v))
        elif wt == 5:
            if i + 4 > len(b):
                break
            out.append((field, "f32", round(struct.unpack("<f", b[i:i+4])[0], 4))); i += 4
        elif wt == 1:
            out.append((field, "f64", round(struct.unpack("<d", b[i:i+8])[0], 4))); i += 8
        elif wt == 2:
            ln, i = _rv(b, i); sub = b[i:i+ln]; i += ln
            inner = _decode(sub, depth+1) if depth < 5 else None
            # se decodifica in modo "pulito" e' un sotto-messaggio, altrimenti bytes/stringa
            if inner and _looks_clean(sub, inner):
                out.append((field, "msg", inner))
            else:
                try:
                    out.append((field, "str", sub.decode("utf-8")))
                except UnicodeDecodeError:
                    out.append((field, "bytes", sub.hex()))
        else:
            break
    return out


def _looks_clean(raw, inner):
    # euristica: se contiene byte ascii stampabili lunghi, e' una stringa
    if all(32 <= c < 127 for c in raw) and len(raw) > 3:
        return False
    return bool(inner)


def parse(path_or_bytes):
    b = path_or_bytes if isinstance(path_or_bytes, (bytes, bytearray)) else open(path_or_bytes, "rb").read()
    tree = _decode(b)
    car = ""
    params = []   # lista di righe {key, label, corner, value}

    # raggruppa i campi top-level ripetuti -> angoli
    groups = {}
    top_scalars = []
    for field, ty, val in tree:
        if ty == "str" and not car:
            car = val
        if ty == "msg":
            groups.setdefault(field, []).append(val)
        elif ty in ("f32", "f64", "int"):
            top_scalars.append((field, val))

    name_for = {2: "molla", 3: "ammo", 4: "alza"}  # gruppi ripetuti noti (per angolo)

    for field, reps in groups.items():
        per_corner = len(reps) == 4
        gname = name_for.get(field, f"g{field}")
        sublabels = SUB_LABELS.get(gname, {})
        for idx, rep in enumerate(reps):
            corner = CORNERS[idx] if per_corner else (str(idx+1) if len(reps) > 1 else "")
            for sf, sty, sval in rep:
                if sty in ("f32", "f64", "int"):
                    params.append({"key": f"{field}.{sf}.{idx}",
                                   "group": gname, "corner": corner,
                                   "label": sublabels.get(sf, f"campo {sf}"),
                                   "value": sval})
                elif sty == "msg":
                    for ssf, _t, ssv in rep_scalars(sval):
                        params.append({"key": f"{field}.{sf}.{ssf}.{idx}",
                                       "group": gname, "corner": corner,
                                       "label": f"{sublabels.get(sf,'campo '+str(sf))} · {ssf}",
                                       "value": ssv})
    for field, val in top_scalars:
        params.append({"key": f"t{field}", "group": "generale", "corner": "",
                       "label": f"campo {field}", "value": val})

    car_clean = car
    preset = ""
    if "_preset" in car:
        car_clean = car.split("_preset")[0]
        import re as _re
        m = _re.search(r"_preset_([a-z0-9]+_[a-z0-9]+)", car)
        if m:
            preset = m.group(1)
    car_clean = car_clean.replace("ks_", "").replace("_", " ").strip().title()

    return {"car": car_clean, "car_id": car, "preset": preset, "params": params}


def rep_scalars(msg):
    for f, ty, v in msg:
        if ty in ("f32", "f64", "int"):
            yield f, ty, v


if __name__ == "__main__":
    import sys, json
    r = parse(sys.argv[1])
    print("auto:", r["car_id"], "->", r["car"])
    print("parametri:", len(r["params"]))
    for p in r["params"]:
        print(f"  [{p['group']:8} {p['corner']:3}] {p['label']:22} = {p['value']}")
