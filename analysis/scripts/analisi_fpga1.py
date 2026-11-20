#!/usr/bin/env python3
"""analisi_fpga1.py — impronta effettiva e costi fissi (fase_fpga1.sh).

Uso: python3 analisi_fpga1.py <cartella>
1. Impronta: per ogni run fpga_* (CPU ferma), core occupati in media durante
   il calcolo = (core-secondi occupati nella finestra) / durata, meno la media
   misurata nelle finestre di idle. Per le run cpu_* lo stesso valore e' un
   controllo (core usati dall'implementazione CPU).
2. Costi fissi: per ogni workload e classe, tempo di calcolo con 2 e 10 unita':
   pendenza = (t10 - t2) / 8 (costo per unita'), intercetta = t2 - 2 x pendenza.
   Lo stesso per il makespan della run (runs.tsv), che include la preparazione.
"""
import json, glob, os, sys, statistics as st
D = sys.argv[1]
S = []
for f in glob.glob(os.path.join(D, "stat_*.tsv")):
    for line in open(f):
        a, b = line.split(); S.append((float(a), float(b)))
S.sort()
def occupati(t0, t1):
    s = [x for x in S if t0 <= x[0] <= t1]
    return (s[-1][1] - s[0][1]) / (s[-1][0] - s[0][0]) if len(s) > 2 else float("nan")
base = []
for line in open(os.path.join(D, "idle_windows.tsv")).readlines()[1:]:
    n, a, b = line.split(); base.append(occupati(float(a) + 30, float(b)))
B = st.mean(base)
print("core occupati a riposo: " + ", ".join(f"{x:.2f}" for x in base) + f"  (media {B:.2f})\n")
win = {}
for line in open(os.path.join(D, "runs.tsv")):
    c = line.rstrip("\n").split("\t")
    if len(c) >= 4: win[c[0]] = (float(c[2]), float(c[3]))
N = {"qpdyn": "QP", "nbody": "NB", "deflate": "DE", "algo3": "IM"}
imp, tc, tm = {}, {}, {}
for f in sorted(glob.glob(os.path.join(D, "*_timeline.json")), key=os.path.getmtime):
    d = json.load(open(f)); tag = d["tag"]; p = tag.split("_")
    seg = [s for v in d["sequenze"].values() for s in v][0]
    w = N[seg["workload"]]; n = d["units"][seg["workload"]]
    c = occupati(seg["t_start"], seg["t_end"]) - B
    print(f"{tag:14} {w} {n:2d} u   calcolo {seg['calcolo_s']:7.1f} s   core occupati sopra il riposo {c:6.2f}")
    if p[0] in ("cpu", "fpga") and len(p) == 4:
        cl, u = p[0], int(p[2].rstrip("u"))
        tc.setdefault((cl, w, u), []).append(seg["calcolo_s"])
        tm.setdefault((cl, w, u), []).append(win[tag][1] - win[tag][0])
        if cl == "fpga": imp.setdefault(w, []).append(c)
print("\nImpronta effettiva c_w (core occupati in media dal runtime, CPU ferma):")
for w, v in imp.items():
    print(f"  {w}: {st.mean(v):5.2f} ± {st.stdev(v) if len(v) > 1 else 0:4.2f}  ({len(v)} run)")
print("\nCosti fissi (2 e 10 unita'): pendenza = costo per unita', intercetta = costo fisso")
for (cl, w) in sorted({(k[0], k[1]) for k in tc}):
    if (cl, w, 2) in tc and (cl, w, 10) in tc:
        for nome, dd in (("calcolo", tc), ("makespan", tm)):
            t2, t10 = st.mean(dd[(cl, w, 2)]), st.mean(dd[(cl, w, 10)])
            k = (t10 - t2) / 8; q = t2 - 2 * k
            print(f"  {cl:4} {w} {nome:8}: {k:6.2f} s/u, costo fisso {q:6.1f} s")
