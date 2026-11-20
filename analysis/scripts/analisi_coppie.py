#!/usr/bin/env python3
"""analisi_coppie.py — matrice di interferenza dalla campagna fase_coppie.sh.

Uso:  python3 analisi_coppie.py <cartella della campagna> [--csv matrice.csv]

Per ogni run <u>_<v>_<r> legge dalla timeline il segmento CPU del workload u e
quello FPGA del workload v. Il rallentamento e' t_C(u|v) / t_C(u isolato),
con t_C isolato = media delle run ref_<u>_a e ref_<u>_b (FPGA ferma).
Controlli: la FPGA deve restare occupata per tutta la fase CPU (copertura
= 100 %); se finisce prima, la run e' segnalata e il valore non e' valido.
"""
import json, glob, os, sys, statistics as st

NOMI = {"qpdyn": "QP", "nbody": "NB", "deflate": "DE", "algo3": "IM"}
ORD = ["QP", "NB", "DE", "IM"]

def carica(cartella):
    run = {}
    for f in glob.glob(os.path.join(cartella, "*_timeline.json")):
        d = json.load(open(f))
        run[d["tag"]] = d
    return run

def segmento(d, classe, w):
    for dev, segs in d["sequenze"].items():
        if dev.startswith(classe):
            for s in segs:
                if NOMI.get(s["workload"], s["workload"]) == w:
                    return s
    return None

def unita_cpu(d, w):
    nome = [k for k, v in NOMI.items() if v == w][0]
    return d["units"][nome] - d["alloc"].get(nome, 0)

def main():
    cart = sys.argv[1]
    csv = sys.argv[sys.argv.index("--csv") + 1] if "--csv" in sys.argv else None
    run = carica(cart)
    # riferimenti isolati
    rif = {}
    for w in ORD:
        v = []
        for tag in (f"ref_{w}_a", f"ref_{w}_b"):
            if tag in run:
                s = segmento(run[tag], "CPU", w)
                v.append(s["calcolo_s"] / unita_cpu(run[tag], w))
        rif[w] = v
        if v:
            print(f"riferimento {w}: " + ", ".join(f"{x:.2f}" for x in v) + " s/u"
                  + (f"   (deriva {100*(v[-1]/v[0]-1):+.1f} %)" if len(v) == 2 else ""))
    print()
    mat = {}
    for tag, d in sorted(run.items()):
        p = tag.split("_")
        if len(p) != 3 or p[0] not in ORD or p[1] not in ORD:
            continue
        u, v = p[0], p[1]
        sc = segmento(d, "CPU", u); sf = segmento(d, "FPGA", v)
        if not sc or not sf or not rif.get(u):
            print(f"{tag}: segmenti o riferimento mancanti"); continue
        tcu = sc["calcolo_s"] / unita_cpu(d, u)
        r = tcu / st.mean(rif[u])
        cop = min(1.0, (sf["t_end"] - sc["t_start"]) / max(1e-9, sc["t_end"] - sc["t_start"]))
        ok = cop >= 0.999
        mat.setdefault((u, v), []).append((r, ok))
        print(f"{tag:10} t_C {tcu:7.2f} s/u   rallentamento {r:6.3f}   copertura FPGA {100*cop:5.1f} %"
              + ("" if ok else "   <-- NON VALIDA: la FPGA ha finito prima"))
    print("\nMatrice (riga: CPU, colonna: FPGA), media ± dev. std. sulle run valide:")
    print("CPU\\FPGA " + "".join(f"{v:>16}" for v in ORD))
    righe = []
    for u in ORD:
        cel = []
        for v in ORD:
            val = [r for r, ok in mat.get((u, v), []) if ok]
            if not val: cel.append("—")
            elif len(val) == 1: cel.append(f"{val[0]:.3f} (1)")
            else: cel.append(f"{st.mean(val):.3f}±{st.stdev(val):.3f} ({len(val)})")
        righe.append((u, cel))
        print(f"{u:8} " + "".join(f"{c:>16}" for c in cel))
    if csv:
        with open(csv, "w") as f:
            f.write("CPU;" + ";".join(ORD) + "\n")
            for u, cel in righe:
                f.write(u + ";" + ";".join(cel) + "\n")
        print(f"\nscritto {csv}")

if __name__ == "__main__":
    main()
