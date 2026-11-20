#!/usr/bin/env python3
"""analisi_casuali.py — modello contro misura sulle allocazioni casuali.

Uso: python3 analisi_casuali.py <cartella campagna> <casuali_REGIME.tsv> [--png grafico.png]

Per ogni run: makespan misurato (runs.tsv), energia del nodo integrando il log di
potenza sulla finestra della run, P_idle interpolata fra le finestre di idle.
Previsione: T_prev dal file, E_prev = P_idle(sessione) * T_prev + E_app_prev.
Stampa la tabella, gli errori relativi (medio, mediano, massimo), la correlazione
di rango (Spearman) e quante allocazioni casuali consumano meno dell'ottimo
misurato. Scrive <cartella>/modello_vs_misura.csv e, se matplotlib e' presente,
un grafico a due pannelli (energia e makespan).
"""
import glob, os, sys, statistics as st
D, LISTA = sys.argv[1], sys.argv[2]
PNG = sys.argv[sys.argv.index("--png") + 1] if "--png" in sys.argv else os.path.join(D, "modello_vs_misura.png")

prev = {}
for line in open(LISTA):
    if line.startswith("#") or not line.strip(): continue
    t, a, T, Ea = line.rstrip("\n").split("\t")
    prev[t] = (a, float(T), float(Ea))

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
def energia(a, b):
    s = [(t, p) for t, p in pw if a <= t <= b]
    return sum((y[0]-x[0])*(x[1]+y[1])/2 for x, y in zip(s, s[1:]))
idle = []
for line in open(os.path.join(D, "idle_windows.tsv")).readlines()[1:]:
    n, a, b = line.split(); a, b = float(a), float(b)
    idle.append(((a+b)/2, media(a+30, b)))
def pidle(t):
    if t <= idle[0][0]: return idle[0][1]
    for (ta, pa), (tb, pb) in zip(idle, idle[1:]):
        if ta <= t <= tb: return pa + (pb-pa)*(t-ta)/(tb-ta)
    return idle[-1][1]

rows = []
for line in open(os.path.join(D, "runs.tsv")):
    c = line.rstrip("\n").split("\t")
    if len(c) < 4: continue
    tag, t0, t1 = c[0], float(c[2]), float(c[3])
    base = "opt" if tag.startswith("opt") else tag
    if base not in prev: continue
    a, Tp, Ea = prev[base]
    P = pidle((t0+t1)/2)
    Tm, Em = t1 - t0, energia(t0, t1)/1e3
    Ep = P*Tp/1e3 + Ea
    rows.append((tag, a, Tp, Tm, Ep, Em))

print(f"P_idle finestre: " + ", ".join(f"{p:.1f}" for _, p in idle) + " W\n")
print(f"{'run':7} {'allocazione':24} {'T prev':>8} {'T mis':>8} {'err':>7} {'E prev':>8} {'E mis':>8} {'err':>7}")
eT, eE = [], []
for tag, a, Tp, Tm, Ep, Em in rows:
    dT, dE = (Tm/Tp-1)*100, (Em/Ep-1)*100
    if not tag.startswith("opt"): eT.append(dT); eE.append(dE)
    print(f"{tag:7} {a:24} {Tp:8.1f} {Tm:8.1f} {dT:+6.1f}% {Ep:8.1f} {Em:8.1f} {dE:+6.1f}%")

def spearman(x, y):
    rx = {v: i for i, v in enumerate(sorted(range(len(x)), key=lambda k: x[k]))}
    ry = {v: i for i, v in enumerate(sorted(range(len(y)), key=lambda k: y[k]))}
    n = len(x); d2 = sum((rx[i]-ry[i])**2 for i in range(n))
    return 1 - 6*d2/(n*(n*n-1))
cas = [r for r in rows if not r[0].startswith("opt")]
opt = [r for r in rows if r[0].startswith("opt")]
print(f"\nAllocazioni casuali: {len(cas)}")
for nome, e in (("makespan", eT), ("energia", eE)):
    ae = [abs(v) for v in e]
    print(f"  errore {nome:8}: medio {st.mean(e):+.1f} %, assoluto medio {st.mean(ae):.1f} %, "
          f"mediano {st.median(ae):.1f} %, massimo {max(ae):.1f} %")
print(f"  correlazione di rango (Spearman), energia: {spearman([r[4] for r in cas], [r[5] for r in cas]):.3f}")
if opt:
    Eo = st.median(r[5] for r in opt)
    meno = [r[0] for r in cas if r[5] < Eo]
    print(f"  ottimo misurato (mediana di {len(opt)} run): {Eo:.1f} kJ; allocazioni casuali sotto l'ottimo: {len(meno)} {meno}")

with open(os.path.join(D, "modello_vs_misura.csv"), "w") as f:
    f.write("run;allocazione;T_prev;T_mis;E_prev;E_mis\n")
    for r in rows: f.write(";".join([r[0], r[1]] + [f"{v:.1f}" for v in r[2:]]) + "\n")
print(f"\nscritto {os.path.join(D, 'modello_vs_misura.csv')}")
try:
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 2, figsize=(8, 3.8))
    for k, (i, j, nome) in enumerate(((4, 5, "Energy (kJ)"), (2, 3, "Makespan (s)"))):
        x = [r[i] for r in cas]; y = [r[j] for r in cas]
        ax[k].scatter(x, y, s=14, label="random")
        ax[k].scatter([r[i] for r in opt], [r[j] for r in opt], s=30, marker="*", label="optimum")
        lo, hi = min(x+y), max(x+y); ax[k].plot([lo, hi], [lo, hi], "k--", lw=0.8)
        ax[k].set_xlabel("model " + nome); ax[k].set_ylabel("measured " + nome)
    ax[0].legend(); fig.tight_layout(); fig.savefig(PNG, dpi=150)
    print(f"scritto {PNG}")
except ImportError:
    print("matplotlib non disponibile: usa il CSV per il grafico")
