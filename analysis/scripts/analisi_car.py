#!/usr/bin/env python3
"""analisi_car.py — parametri per unita' dalla campagna fase_car.sh.

Uso:  python3 analisi_car.py <cartella della campagna>

Per ogni run cpu_<w>_r e fpga_<w>_r: tempo per unita' (calcolo dalla
timeline / 10) ed energia per unita' sopra l'idle, integrando il log di
potenza sulla finestra della run (runs.tsv) e sottraendo P_idle x durata,
con P_idle interpolata linearmente fra le finestre di idle dedicate.
Stampa la tabella dei parametri (media e dev. std. su 3 run) con Delta,
sigma e rho per una scheda, e il rallentamento QP|NB delle run qp1nb_r.
"""
import json, glob, os, sys, statistics as st

D = sys.argv[1]
NOMI = {"qpdyn": "QP", "nbody": "NB", "deflate": "DE", "algo3": "IM"}

# --- log di potenza: epoca e potenza (prime due colonne numeriche)
pw = []
for f in glob.glob(os.path.join(D, "*power_*.log")):
    for line in open(f):
        v = []
        for x in line.split():
            try: v.append(float(x))
            except ValueError: pass
        if len(v) >= 2 and v[0] > 1e9:
            pw.append((v[0], v[1]))
pw.sort()
def energia(t0, t1):
    s = [(t, p) for t, p in pw if t0 <= t <= t1]
    return sum((b[0]-a[0])*(a[1]+b[1])/2 for a, b in zip(s, s[1:]))
def potenza_media(t0, t1):
    s = [p for t, p in pw if t0 <= t <= t1]
    return st.mean(s) if s else float("nan")

# --- finestre di idle
idle = []
for line in open(os.path.join(D, "idle_windows.tsv")).readlines()[1:]:
    nome, a, b = line.split()
    a, b = float(a), float(b)
    idle.append(((a+b)/2, potenza_media(a+30, b), nome))
print("P_idle:", ", ".join(f"{n} {p:.1f} W" for _, p, n in idle))
def p_idle(t):
    if len(idle) == 1 or t <= idle[0][0]: return idle[0][1]
    for (ta, pa, _), (tb, pb, _) in zip(idle, idle[1:]):
        if ta <= t <= tb: return pa + (pb-pa)*(t-ta)/(tb-ta)
    return idle[-1][1]

# --- run
win = {}
for line in open(os.path.join(D, "runs.tsv")):
    c = line.rstrip("\n").split("\t")
    if len(c) >= 4: win[c[0]] = (float(c[2]), float(c[3]))
tl = {}
for f in glob.glob(os.path.join(D, "*_timeline.json")):
    d = json.load(open(f)); tl[d["tag"]] = d

par = {}   # (classe, w) -> lista di (t_unita, E_unita)
for tag, d in sorted(tl.items()):
    p = tag.split("_")
    if len(p) != 3 or p[0] not in ("cpu", "fpga"): continue
    classe, w = p[0], p[1]
    dev = "CPU" if classe == "cpu" else "FPGA"
    seg = next(s for k, v in d["sequenze"].items() if k.startswith(dev) for s in v)
    n = 10
    t0, t1 = win[tag]
    E = energia(t0, t1) - p_idle((t0+t1)/2) * (t1 - t0)
    par.setdefault((classe, w), []).append((seg["calcolo_s"]/n, E/n))
    print(f"{tag:10} t = {seg['calcolo_s']/n:7.2f} s/u   E = {E/n/1e3:7.3f} kJ/u   (T {t1-t0:6.1f} s)")

def m(v): return (st.mean(v), st.stdev(v) if len(v) > 1 else 0.0)
Pm = st.mean(p for _, p, _ in idle)
print(f"\nParametri per unita' (media ± dev. std.), P_idle medio {Pm:.1f} W, una scheda:")
print(f"{'w':3} {'t_F':>14} {'t_C':>14} {'E_F (J)':>16} {'E_C (J)':>16} {'Delta':>8} {'sigma':>7} {'rho':>8}")
for w in ("QP", "NB", "DE", "IM"):
    f = par.get(("fpga", w), []); c = par.get(("cpu", w), [])
    if not f or not c: print(w, "dati incompleti"); continue
    tF, sF = m([x[0] for x in f]); tC, sC = m([x[0] for x in c])
    EF, eF = m([x[1] for x in f]); EC, eC = m([x[1] for x in c])
    Dl = EC - EF; sig = tC/(tF+tC); rho = (Dl + Pm*tC)/(tF+tC)
    print(f"{w:3} {tF:7.2f}±{sF:5.2f} {tC:7.2f}±{sC:5.2f} {EF:8.0f}±{eF:6.0f} {EC:8.0f}±{eC:6.0f} {Dl:8.0f} {sig:7.4f} {rho:8.1f}")

# --- QP|NB diretto
tq = [x[0] for x in par.get(("cpu", "QP"), [])]
for tag in sorted(t for t in tl if t.startswith("qp1nb_")):
    d = tl[tag]
    c = next(s for s in d["sequenze"]["CPU"] if s["workload"] == "qpdyn")
    fp = next(s for k, v in d["sequenze"].items() if k.startswith("FPGA") for s in v)
    cop = min(1, (fp["t_end"]-c["t_start"])/(c["t_end"]-c["t_start"]))
    r = c["calcolo_s"]/st.mean(tq) if tq else float("nan")
    print(f"{tag}: QP 1 unita' in {c['calcolo_s']:.1f} s, rallentamento {r:.1f}, copertura FPGA {100*cop:.0f} %"
          + ("" if cop >= 0.999 else "  <-- NON VALIDA"))
