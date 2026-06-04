"""Parser per file MoTeC .ld / .ldx (formato usato dall'export di Assetto Corsa EVO).
Formato binario ricostruito per reverse-engineering. Solo lettura."""
import struct
import re
import numpy as np


def _s(b):
    return b.split(b"\x00")[0].decode("latin-1", "replace").strip()


# (dtype_a, dtype) -> numpy dtype
_DTYPE = {
    (0x07, 2): np.float16, (0x07, 4): np.float32,
    (0x00, 2): np.int16,   (0x00, 4): np.int32,
    (0x03, 2): np.int16,   (0x03, 4): np.int32,
    (0x05, 2): np.int16,   (0x05, 4): np.int32,
}


class Channel:
    __slots__ = ("prev", "next", "data_ptr", "n", "dtype_a", "dtype",
                 "freq", "shift", "mul", "scale", "dec", "name", "short",
                 "unit", "_buf")

    @classmethod
    def parse(cls, raw, off):
        c = cls()
        c.prev, c.next, c.data_ptr, c.n = struct.unpack("<IIII", raw[off:off + 16])
        (_cnt, c.dtype_a, c.dtype, c.freq,
         c.shift, c.mul, c.scale, c.dec) = struct.unpack("<HHHHhhhh", raw[off + 16:off + 32])
        c.name = _s(raw[off + 32:off + 64])
        c.short = _s(raw[off + 64:off + 72])
        c.unit = _s(raw[off + 72:off + 84])
        c._buf = raw
        return c

    @property
    def numpy_dtype(self):
        return _DTYPE.get((self.dtype_a, self.dtype), np.float32)

    @property
    def data(self):
        raw = np.frombuffer(self._buf, dtype=self.numpy_dtype,
                            count=self.n, offset=self.data_ptr)
        out = raw.astype(np.float64)
        if self.scale != 1 or self.dec != 0 or self.shift != 0 or self.mul != 1:
            out = (out / self.scale * (10.0 ** -self.dec) + self.shift) * self.mul
        return out


class LD:
    def __init__(self, path):
        with open(path, "rb") as f:
            raw = f.read()
        self.raw = raw
        self.meta_ptr, self.data_ptr = struct.unpack("<II", raw[8:16])
        self.event_ptr, = struct.unpack("<I", raw[0x24:0x28])
        self.date = _s(raw[0x5E:0x5E + 16])
        self.time = _s(raw[0x7E:0x7E + 16])
        self.channels = self._read_channels(raw)

    def _read_channels(self, raw):
        chans, off, seen = [], self.meta_ptr, set()
        while off and off not in seen and off + 84 <= len(raw):
            seen.add(off)
            c = Channel.parse(raw, off)
            if c.n > 0 and c.freq > 0 and c.name:
                chans.append(c)
            off = c.next
        return chans

    def get(self, name):
        for c in self.channels:
            if c.name == name:
                return c
        return None

    @property
    def duration(self):
        if not self.channels:
            return 0.0
        return max(c.n / c.freq for c in self.channels)


def read_ldx_beacons(path):
    """Restituisce i tempi (in secondi) dei beacon dal file .ldx (XML)."""
    try:
        with open(path, "r", encoding="latin-1") as f:
            txt = f.read()
    except OSError:
        return []
    times = []
    for m in re.finditer(r'<Marker\b[^>]*\bTime="([^"]+)"', txt):
        try:
            times.append(float(m.group(1)) / 1e6)  # microsecondi -> secondi
        except ValueError:
            pass
    return sorted(times)
