#!/usr/bin/env python3
"""analisi_ecfg.py — tempo ed energia delle transizioni da misura_ecfg.py.

Uso:  python3 bin/analisi_ecfg.py <cartella>
Per ogni caricamento: durata della transizione (tready - t0, dal lancio
all'annuncio @@READY) ed energia sopra la base locale, integrata su
[t0 - 1, tready + 1]; la base e' la potenza media su [t0 - 17, t0 - 2].
"""
import glob, os, sys, statistics as st
D = sys.argv[1]
DOPO = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0   # secondi integrati dopo @@READY
pw = []
for f in glob.glob(os.path.join(D, "*power_*.log")):
    for line in open(f):
        v = []
        for x in line.split():
            try: v.append(float(x))
            except ValueError: pass
        if len(v) >= 2 and v[0] > 1e9: pw.append((v[0], v[1]))
pw.sort()
def media(a, b):
    s = [p for t, p in pw if a <= t <= b]; return st.mean(s) if s else float("nan")
def integ(a, b, base):
    s = [(t, p - base) for t, p in pw if a <= t <= b]
    return sum((y[0]-x[0])*(x[1]+y[1])/2 for x, y in zip(s, s[1:]))
ris = {}
for line in open(os.path.join(D, "caricamenti.tsv")).readlines()[1:]:
    w, r, t0, t1, _, rc = line.split(); t0, t1 = float(t0), float(t1)
    if rc != "0": print(f"{w} {r}: codice {rc}, scartato"); continue
    base = media(t0 - 17, t0 - 2)
    E = integ(t0 - 1, t1 + DOPO, base)
    ris.setdefault(w, []).append((t1 - t0, E, base))
for w, v in ris.items():
    d = [x[0] for x in v]; e = [x[1] for x in v]; b = [x[2] for x in v]
    print(f"{w:8} n={len(v):2d}  durata {st.mean(d):5.2f} ± {st.stdev(d):4.2f} s   "
          f"energia {st.mean(e):7.0f} ± {st.stdev(e):5.0f} J   base {st.mean(b):6.1f} W")
