#!/usr/bin/env python3
"""
Calcola l'energia di ogni run integrando il log IPMI sulle finestre temporali.

Riconosce due formati di runs.tsv:

  run_split.py  (singolo workload)
      tag  n_fpga  n_cpu  t_start  t_end  [workload]

  run_multi.py  (piu' workload)
      tag  ripartizione  t_start  t_end  multi

La distinzione e' automatica: se la seconda colonna contiene ':' e' il
formato multi.

Uso:
  ./analyze_power.py ipmi_log.txt runs.tsv
  ./analyze_power.py ipmi_log.txt runs.tsv --idle 712 --csv risultati.csv
"""

import argparse
import sys


def load_power(path):
    """Ritorna [(epoch, watt), ...] ordinato."""
    pts, skipped = [], 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("Epoch"):
                continue
            parts = line.replace(",", " ").split()
            try:
                pts.append((float(parts[0]), float(parts[1])))
            except (IndexError, ValueError):
                skipped += 1
    pts.sort()
    if skipped:
        print(f"  {skipped} righe ignorate (letture N/A o malformate)",
              file=sys.stderr)
    return pts


def load_runs(path):
    """Ritorna [{tag, label, t0, t1}, ...], riconoscendo il formato."""
    runs = []
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            c = line.split("\t")
            if len(c) < 4:
                continue
            if ":" in c[1]:                      # formato run_multi
                runs.append(dict(tag=c[0], label=c[1],
                                 t0=float(c[2]), t1=float(c[3])))
            else:                                 # formato run_split
                runs.append(dict(tag=c[0], label=f"{c[1]}/{c[2]}",
                                 t0=float(c[3]), t1=float(c[4])))
    return runs


def integrate(pts, t0, t1):
    """Energia in joule fra t0 e t1 (trapezi), piu' statistiche."""
    win = [(t, w) for t, w in pts if t0 <= t <= t1]
    if len(win) < 2:
        return None
    E = sum((a[1] + b[1]) / 2.0 * (b[0] - a[0]) for a, b in zip(win, win[1:]))
    vals = [w for _, w in win]
    return dict(E=E, n=len(vals), P=sum(vals) / len(vals),
                cov=(win[-1][0] - win[0][0]) / (t1 - t0) if t1 > t0 else 0.0)


def estimate_idle(pts, runs, margin=5.0):
    """Potenza media fuori dalle finestre di esecuzione."""
    busy = [(r["t0"] - margin, r["t1"] + margin) for r in runs]
    idle = [w for t, w in pts if not any(a <= t <= b for a, b in busy)]
    return sum(idle) / len(idle) if idle else None


def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("ipmi_log")
    p.add_argument("runs_tsv")
    p.add_argument("--idle", type=float,
                   help="P_idle in W; se omesso, stimata dai periodi di quiete")
    p.add_argument("--csv", help="scrive i risultati anche in CSV")
    a = p.parse_args()

    pts = load_power(a.ipmi_log)
    if not pts:
        sys.exit("log IPMI vuoto o non interpretabile")
    print(f"Log IPMI: {len(pts)} campioni, da {pts[0][0]:.0f} a {pts[-1][0]:.0f} "
          f"({(pts[-1][0]-pts[0][0])/60:.1f} min)\n")

    runs = load_runs(a.runs_tsv)
    if not runs:
        sys.exit("runs.tsv vuoto o non interpretabile")

    P_idle = a.idle if a.idle else estimate_idle(pts, runs)
    if P_idle:
        src = "fornita" if a.idle else "stimata dai periodi di quiete"
        print(f"P_idle = {P_idle:.1f} W ({src})\n")

    wl = max(len(r["label"]) for r in runs)
    hdr = (f"{'tag':<20}{'ripartizione':<{wl+2}}{'T(s)':>9}"
           f"{'P_med(W)':>10}{'E_tot(kJ)':>11}{'E_inc(kJ)':>11}")
    print(hdr)
    print("-" * len(hdr))

    rows = []
    for r in runs:
        st = integrate(pts, r["t0"], r["t1"])
        if st is None:
            print(f"{r['tag']:<20}  -- nessun campione nella finestra --")
            continue
        T = r["t1"] - r["t0"]
        E_inc = st["E"] - P_idle * T if P_idle else float("nan")
        print(f"{r['tag']:<20}{r['label']:<{wl+2}}{T:>9.1f}"
              f"{st['P']:>10.1f}{st['E']/1000:>11.1f}{E_inc/1000:>11.1f}")
        if st["cov"] < 0.9:
            print(f"{'':20}  ATTENZIONE: copertura campioni {st['cov']*100:.0f}%"
                  f" — verifica la sincronia degli orologi")
        rows.append((r, st, T, E_inc))

    # la finestra 'idle' serve solo a P_idle: non entra nei confronti
    idle_rows = [x for x in rows if x[0]["tag"] == "idle"]
    for r, st, T, _ in idle_rows:
        print(f"\nfinestra idle: P media {st['P']:.1f} W su {T:.0f} s")
    rows = [x for x in rows if x[0]["tag"] != "idle"]
    if rows:
        best = min(rows, key=lambda x: x[1]["E"])
        fast = min(rows, key=lambda x: x[2])
        print(f"\nMinimo di energia: {best[0]['tag']} "
              f"({best[0]['label']}) con {best[1]['E']/1000:.1f} kJ")
        print(f"Minimo di tempo  : {fast[0]['tag']} "
              f"({fast[0]['label']}) con {fast[2]:.1f} s")
        print("  -> coincidono, come previsto dal modello" if best[0] is fast[0]
              else "  -> NON coincidono: vedi §5 della formalizzazione")

        # risparmio rispetto alla configurazione tutto-CPU, se presente
        E = {r["tag"]: st["E"] for r, st, _, _ in rows}
        def all_cpu(label):
            if ":" in label:                    # formato run_multi: WL:n+WL:n
                return all(x.split(":")[1] == "0" for x in label.split("+"))
            a_, _, b_ = label.partition("/")     # formato run_split: nA/nB
            return a_ == "0" and b_ not in ("", "0")
        zeros = [r for r, st, _, _ in rows if all_cpu(r["label"])]
        if zeros and best[0] not in zeros:
            Ez = E[zeros[0]["tag"]]
            print(f"\nrisparmio dell'ottimo vs {zeros[0]['label']}: "
                  f"{100*(1-best[1]['E']/Ez):.1f}%")

    if a.csv:
        with open(a.csv, "w") as f:
            f.write("tag,ripartizione,T_s,P_mean_W,E_tot_J,E_inc_J\n")
            for r, st, T, E_inc in rows:
                f.write(f"{r['tag']},{r['label']},{T:.3f},"
                        f"{st['P']:.2f},{st['E']:.1f},{E_inc:.1f}\n")
        print(f"\nCSV scritto in {a.csv}")


if __name__ == "__main__":
    main()
