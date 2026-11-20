#!/usr/bin/env python3
"""
run_multi.py — orchestratore per piu' workload smaltiti contemporaneamente.

Estende run_split.py al caso vettoriale. FPGA e CPU eseguono ciascuna una
SEQUENZA di workload; i due dispositivi lavorano concorrentemente.

    FPGA:  [cfg] W_a ... [cfg] W_b ...
    CPU :  W_c ......... W_d .........
           ^                          ^
           @@READY globale            @@DONE globale

Una sola barriera all'inizio e una alla fine: le barriere dei singoli
binari servono a sincronizzare le transizioni interne, non a segmentare la
finestra di misura.

Il tempo fra il @@DONE di un workload e il @@READY del successivo sullo
stesso dispositivo e' la **transizione**: per la FPGA include la
riconfigurazione (t_cfg), per entrambi il caricamento dei dati. Viene
misurata e riportata separatamente.

Esempi:

  # calcola la ripartizione ottima senza eseguire
  ./run_multi.py --units IM:30,DE:30,QP:30 --optimize

  # esegue la ripartizione ottima
  ./run_multi.py --units IM:30,DE:30,QP:30 --optimize --run --tag opt

  # esegue una ripartizione data
  ./run_multi.py --units IM:30,DE:30,QP:30 --alloc IM:0,DE:4,QP:30 --run --tag n0_4_30

  # punto di controllo che viola la priorita' (solo previsione)
  ./run_multi.py --units IM:30,DE:30,QP:30 --alloc IM:4,DE:0,QP:30
"""

import argparse
import itertools
import json
import os
import subprocess
import sys
import threading
import time

READY = "@@READY"
DONE = "@@DONE"

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CFG = os.path.join(HERE, "workloads.json")

# alias brevi <-> nomi nel descrittore
ALIAS = {"IM": "algo3", "DE": "deflate", "QP": "qpdyn", "NB": "nbody", "ET": "ethash", "HP": "hpl", "YO": "yolo"}
RALIAS = {v: k for k, v in ALIAS.items()}


# ===========================================================================
#  Modello
# ===========================================================================
class Model:
    """Parametri energetici e soluzione del problema di ripartizione."""

    def __init__(self, cfg, units, P_idle, t_cfg, E_cfg):
        self.u = dict(units)                  # {workload: N_w}
        self.P_idle, self.t_cfg, self.E_cfg = P_idle, t_cfg, E_cfg
        self.p = {}
        for w, N in units.items():
            d = cfg[w]
            tA, tB = d["fpga"]["t_unit_s"], d["cpu"]["t_unit_s"]
            if tA is None or tB is None:
                sys.exit(f"workload '{w}': t_unit_s mancante, calibrare prima")
            PA = d["fpga"].get("P_incr_W")
            PB = d["cpu"].get("P_incr_W")
            if PA is None or PB is None:
                sys.exit(f"workload '{w}': P_incr_W mancante nel descrittore")
            self.p[w] = dict(tA=tA, tB=tB, EA=PA * tA, EB=PB * tB,
                             D=PB * tB - PA * tA)
        self.k, self.order = 1, None

    def set_devices(self, k, order):
        """--per-device: k acceleratori uguali che si dividono le unita' come fa
        l'esecuzione (divmod per workload, resto a turno). t_unit_s del lato
        'fpga' resta il tempo per unita' dell'insieme (t di un dispositivo / k);
        T_A diventa il carico del dispositivo piu' carico, a unita' intere."""
        self.k, self.order = max(1, k), order

    def _TA(self, n):
        if self.k <= 1:
            c = sum(1 for w in n if n[w] > 0)
            return sum(n[w] * self.p[w]["tA"] for w in n) + c * self.t_cfg
        load, rr = [0.0] * self.k, 0
        for w in self.order:
            nw = int(n.get(w, 0))
            if nw <= 0:
                continue
            q, rem = divmod(nw, self.k)
            share = [q] * self.k
            for _ in range(rem):
                share[rr % self.k] += 1
                rr += 1
            for d in range(self.k):
                if share[d] > 0:
                    load[d] += share[d] * self.p[w]["tA"] * self.k + self.t_cfg
        return max(load)

    # -- valutazione di una ripartizione ------------------------------------
    def eval(self, n):
        c = sum(1 for w in n if n[w] > 0)
        TA = self._TA(n)
        TB = sum((self.u[w] - n[w]) * self.p[w]["tB"] for w in n)
        T = max(TA, TB)
        E = (sum(self.p[w]["EA"] * n[w] + self.p[w]["EB"] * (self.u[w] - n[w])
                 for w in n)
             + c * self.E_cfg + self.P_idle * T)
        return dict(T=T, E=E, TA=TA, TB=TB, c=c)

    # -- densita' di priorita' ----------------------------------------------
    def rho(self, w):
        q = self.p[w]
        return (q["D"] + self.P_idle * q["tB"]) / (q["tA"] + q["tB"])

    def sigma(self, w):
        q = self.p[w]
        return q["tB"] / (q["tA"] + q["tB"])

    def priority(self, key="rho"):
        f = self.rho if key == "rho" else self.sigma
        return sorted(self.p, key=f, reverse=True)

    # -- soluzione ----------------------------------------------------------
    def greedy(self, c_assumed):
        """Zaino frazionario, riempimento per rho decrescente."""
        budget = (sum(self.u[w] * self.p[w]["tB"] for w in self.u)
                  - c_assumed * self.t_cfg)
        n, rem = {w: 0.0 for w in self.u}, budget
        for w in self.priority("rho"):
            cost = self.p[w]["tA"] + self.p[w]["tB"]
            take = max(0.0, min(self.u[w], rem / cost))
            n[w] = take
            rem -= take * cost
        return n

    def solve(self, objective="E"):
        """Greedy per ogni c plausibile, poi ricerca locale sugli interi."""
        cands = set()
        for c in range(1, len(self.u) + 1):
            frac = self.greedy(c)
            # tutti gli arrotondamenti del workload frazionario
            base = {w: int(frac[w]) for w in frac}
            for delta in itertools.product(*[range(0, 2) for _ in self.u]):
                cand = {w: min(self.u[w], base[w] + d)
                        for w, d in zip(sorted(self.u), delta)}
                cands.add(tuple(cand[w] for w in sorted(self.u)))
        # intorno locale, per sicurezza
        extra = set()
        for t in cands:
            for delta in itertools.product([-2, -1, 0, 1, 2], repeat=len(t)):
                v = tuple(max(0, min(self.u[w], t[i] + delta[i]))
                          for i, w in enumerate(sorted(self.u)))
                extra.add(v)
        cands |= extra
        # estremi
        cands.add(tuple(0 for _ in self.u))
        cands.add(tuple(self.u[w] for w in sorted(self.u)))

        ks = sorted(self.u)
        best = None
        for t in cands:
            n = dict(zip(ks, t))
            r = self.eval(n)
            key = (r["E"], r["T"]) if objective == "E" else (r["T"], r["E"])
            if best is None or key < best[0]:
                best = (key, n, r)
        return best[1], best[2]

    def exhaustive(self, objective="E", limit=2_000_000):
        size = 1
        for w in self.u:
            size *= self.u[w] + 1
        if size > limit:
            return None
        ks = sorted(self.u)
        best = None
        for t in itertools.product(*[range(self.u[w] + 1) for w in ks]):
            n = dict(zip(ks, t))
            r = self.eval(n)
            key = (r["E"], r["T"]) if objective == "E" else (r["T"], r["E"])
            if best is None or key < best[0]:
                best = (key, n, r)
        return best[1], best[2]


# ===========================================================================
#  Esecuzione
# ===========================================================================
class Worker:
    """Un singolo processo con handshake @@READY / @@DONE."""

    def __init__(self, label, argv, env=None):
        self.label, self.argv, self.env = label, [str(a) for a in argv], env
        self.proc = None
        self.ready = threading.Event()
        self.done = threading.Event()
        self.log = []
        self.t_ready = self.t_start = self.t_done = None

    def start(self):
        self.proc = subprocess.Popen(
            self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1, env=self.env)
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        for line in self.proc.stdout:
            line = line.rstrip("\n")
            self.log.append(line)
            if READY in line:
                self.t_ready = time.time()
                self.ready.set()
            elif DONE in line:
                self.t_done = time.time()
                self.done.set()
            else:
                print(f"[{self.label}] {line}", file=sys.stderr)

    def release(self):
        self.t_start = time.time()
        self.proc.stdin.write("\n")
        self.proc.stdin.flush()

    def wait(self, ev, what):
        while not ev.wait(timeout=1.0):
            if self.proc.poll() is not None:
                print(f"\nERRORE: {self.label} terminato con codice "
                      f"{self.proc.returncode} senza {what}", file=sys.stderr)
                for ln in self.log[-15:]:
                    print(f"  | {ln}", file=sys.stderr)
                return False
        return True

    def finish(self):
        try:
            self.proc.stdin.write("\n")
            self.proc.stdin.flush()
            self.proc.stdin.close()
        except (BrokenPipeError, ValueError, OSError):
            pass
        try:
            return self.proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            return self.proc.wait(timeout=10)

    @property
    def elapsed(self):
        return (self.t_done - self.t_start) if (self.t_start and self.t_done) else None


class DeviceSequencer(threading.Thread):
    """Esegue una sequenza di workload su un dispositivo.

    Il primo worker viene preparato prima della barriera globale; i
    successivi si avviano dentro la finestra, e il loro setup (per la FPGA:
    la riconfigurazione) e' misurato come transizione."""

    def __init__(self, device, jobs):
        super().__init__(daemon=True)
        self.device, self.jobs = device, jobs   # jobs: [(nome, Worker), ...]
        self.ready = threading.Event()          # primo worker pronto
        self.go = threading.Event()             # via dalla barriera globale
        self.done = threading.Event()
        self.ok = True
        self.timeline = []                      # per workload: dict
        self.t_end = None

    def run(self):
        if not self.jobs:
            self.ready.set(); self.go.wait(); self.done.set(); return
        name0, w0 = self.jobs[0]
        w0.start()
        if not w0.wait(w0.ready, READY):
            self.ok = False; self.ready.set(); self.done.set(); return
        self.ready.set()
        self.go.wait()

        prev_end = time.time()
        for i, (name, w) in enumerate(self.jobs):
            if i > 0:
                w.start()
                if not w.wait(w.ready, READY):
                    self.ok = False; break
            t_transizione = w.t_ready - prev_end if i > 0 else 0.0
            w.release()
            if not w.wait(w.done, DONE):
                self.ok = False; break
            self.timeline.append(dict(
                workload=name, transizione_s=t_transizione,
                calcolo_s=w.elapsed, t_start=w.t_start, t_end=w.t_done))
            prev_end = w.t_done
            w.finish()
        self.t_end = time.time()
        self.done.set()


# ===========================================================================
def parse_pairs(s, what):
    out = {}
    for tok in s.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if ":" not in tok:
            sys.exit(f"{what} malformato: {tok!r} (serve NOME:VALORE)")
        k, v = tok.split(":", 1)
        k = k.strip()
        out[ALIAS.get(k.upper(), k)] = int(v)
    return out


def count_cpus(spec):
    """Numero di core in una lista tipo '0-28,30,32-33'."""
    n = 0
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-")
            n += int(hi) - int(lo) + 1
        else:
            n += 1
    return n


def build_worker(cfg, w, device, n_units, threads, cpus=None):
    d = cfg[w][device]
    unit_items = cfg[w]["unit_items"]
    ctx = {"n_units": n_units, "n_items": n_units * unit_items,
           "threads": threads, "xclbin": d.get("xclbin", ""),
           "ncpu": count_cpus(cpus) if cpus else threads, "cpus": cpus or ""}
    ctx.update(d.get("consts", {}))
    for key, expr in d.get("derived", {}).items():
        ctx[key] = eval(expr, {"__builtins__": {"max": max, "min": min,
                                                "round": round, "int": int}}, ctx)
    argv = [d["bin"]] + [str(a).format(**ctx) for a in d["args"]]
    if cpus:
        argv = ["taskset", "-c", cpus] + argv
    env = dict(os.environ)
    if device == "cpu":
        env["OMP_NUM_THREADS"] = str(threads)
        if cpus:
            env["OMP_PLACES"] = "cores"
            env["OMP_PROC_BIND"] = "close"
    # variabili d'ambiente dichiarate nel descrittore, con gli stessi
    # segnaposto degli argomenti
    for k, v in d.get("env", {}).items():
        if not k.startswith("_"):
            env[k] = str(v).format(**ctx)
    return Worker(f"{device.upper()}:{RALIAS.get(w, w)}", argv, env)


def fmt_alloc(n, u):
    return "  ".join(f"{RALIAS.get(w,w)}={n[w]}/{u[w]}" for w in sorted(n))


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default=DEFAULT_CFG)
    p.add_argument("--units", required=True,
                   help="dimensione dei workload, es. IM:30,DE:30,QP:30")
    p.add_argument("--alloc", help="ripartizione, es. IM:0,DE:4,QP:30")
    p.add_argument("--optimize", action="store_true",
                   help="calcola la ripartizione ottima")
    p.add_argument("--objective", choices=["E", "T"], default="E",
                   help="grandezza da minimizzare con --optimize (default E)")
    p.add_argument("--exhaustive", action="store_true",
                   help="ricerca esaustiva invece che greedy+locale")
    p.add_argument("--run", action="store_true",
                   help="esegue davvero; senza, stampa solo la previsione")
    p.add_argument("--order", help="ordine dei workload sulla FPGA, es. QP,DE,IM")
    p.add_argument("--threads", type=int, default=48)
    p.add_argument("--cpu-cpus", default=None,
                   help="core dei worker CPU, es. 0-28 (taskset, OMP_PLACES=cores)")
    p.add_argument("--fpga-devices", default="",
                   help="indici delle schede, es. 0,1: una sequenza FPGA per scheda")
    p.add_argument("--fpga-cpus", default=None,
                   help="core dei processi host FPGA, es. 29-47 (taskset)")
    p.add_argument("--per-device", action="store_true",
                   help="modello a dispositivi discreti con --fpga-devices multipli "
                        "(tempo del dispositivo piu' carico, unita' intere)")
    p.add_argument("--settle", type=float, default=10.0)
    p.add_argument("--outdir", default="./measures")
    p.add_argument("--tag", default="multi")
    a = p.parse_args()

    thr_cpu = a.threads
    if a.cpu_cpus and "--threads" not in sys.argv:
        thr_cpu = count_cpus(a.cpu_cpus)
    if a.cpu_cpus or a.fpga_cpus:
        import shutil
        if not shutil.which("taskset"):
            sys.exit("il pinning richiede taskset")
        print(f"pinning: CPU={a.cpu_cpus or 'libero'} ({thr_cpu} thread)  "
              f"FPGA host={a.fpga_cpus or 'libero'}")
    cfg = json.load(open(a.config))
    glob = cfg.get("_globals", {})
    P_idle = glob.get("P_idle_W", 712.0)
    t_cfg = glob.get("t_cfg_s", 5.4)
    E_cfg = glob.get("E_cfg_J", 0.0)

    units = parse_pairs(a.units, "--units")
    for w in units:
        if w not in cfg:
            sys.exit(f"workload sconosciuto: {w}. Disponibili: "
                     f"{', '.join(k for k in cfg if not k.startswith('_'))}")

    m = Model(cfg, units, P_idle, t_cfg, E_cfg)
    if a.per_device:
        ndev = len([x for x in a.fpga_devices.split(",") if x.strip()]) if a.fpga_devices else 1
        ord0 = ([ALIAS.get(x.strip().upper(), x.strip()) for x in a.order.split(",")]
                if a.order else m.priority("rho"))
        m.set_devices(ndev, [w for w in ord0 if w in units])
        print(f"modello a dispositivi discreti: {ndev} acceleratori")

    print("=" * 66)
    print(f"  P_idle = {P_idle} W    t_cfg = {t_cfg} s    E_cfg = {E_cfg} J")
    print(f"  {'w':4s} {'N':>4s} {'t_A':>7s} {'t_B':>7s} {'E_A':>7s} {'E_B':>8s}"
          f" {'rho':>8s} {'sigma':>7s}")
    for w in m.priority("rho"):
        q = m.p[w]
        print(f"  {RALIAS.get(w,w):4s} {units[w]:4d} {q['tA']:7.2f} {q['tB']:7.2f}"
              f" {q['EA']:7.0f} {q['EB']:8.0f} {m.rho(w):8.1f} {m.sigma(w):7.4f}")
    print(f"  priorita' energia: {' > '.join(RALIAS.get(w,w) for w in m.priority('rho'))}")
    print(f"  priorita' tempo  : {' > '.join(RALIAS.get(w,w) for w in m.priority('sigma'))}")
    print("=" * 66)

    # --- ripartizione -----------------------------------------------------
    if a.optimize:
        res = (m.exhaustive(a.objective) if a.exhaustive else None) or m.solve(a.objective)
        n, r = res
        frac = m.greedy(r["c"])
        print("\nSoluzione frazionaria (greedy):  "
              + "  ".join(f"{RALIAS.get(w,w)}={frac[w]:.3f}" for w in sorted(frac)))
        print(f"Ottimo intero ({a.objective}):  {fmt_alloc(n, units)}")
    elif a.alloc:
        n = {w: 0 for w in units}
        n.update({w: v for w, v in parse_pairs(a.alloc, "--alloc").items()})
        for w in n:
            if not 0 <= n[w] <= units[w]:
                sys.exit(f"ripartizione non valida per {w}: {n[w]} non in [0,{units[w]}]")
        r = m.eval(n)
    else:
        p.error("serve --alloc oppure --optimize")

    # --- previsione -------------------------------------------------------
    n0 = {w: 0 for w in units}
    nN = dict(units)
    rc, rf = m.eval(n0), m.eval(nN)
    print(f"\n{'configurazione':22s} {'T (s)':>10s} {'E (kJ)':>10s}")
    print(f"{'tutto CPU':22s} {rc['T']:10.1f} {rc['E']/1000:10.1f}")
    print(f"{'ripartizione':22s} {r['T']:10.1f} {r['E']/1000:10.1f}"
          f"   <- T_A={r['TA']:.1f} T_B={r['TB']:.1f} c={r['c']}")
    print(f"{'tutto FPGA':22s} {rf['T']:10.1f} {rf['E']/1000:10.1f}")
    print(f"\nrisparmio previsto: {100*(1-r['E']/rc['E']):.1f}% vs CPU, "
          f"{100*(1-r['E']/rf['E']):.1f}% vs FPGA")

    if not a.run:
        print("\n(solo previsione; aggiungere --run per eseguire)")
        return 0

    # --- costruzione delle sequenze ---------------------------------------
    order = ([ALIAS.get(x.strip().upper(), x.strip()) for x in a.order.split(",")]
             if a.order else m.priority("rho"))
    devs = [int(x) for x in a.fpga_devices.split(",") if x.strip()] if a.fpga_devices else []
    def bind(w, wk, d):
        wk.env[cfg[w]["fpga"].get("device_env", "FPGA_DEVICE")] = str(d)
    if len(devs) > 1:
        shares = {d: {} for d in devs}; rr = 0
        for w in order:
            q, rem = divmod(n.get(w, 0), len(devs))
            for d in devs:
                shares[d][w] = q
            for _ in range(rem):
                shares[devs[rr % len(devs)]][w] += 1; rr += 1
        fpga_seqs = []
        for d in devs:
            jobs = []
            for w in order:
                if shares[d].get(w, 0) > 0:
                    wk = build_worker(cfg, w, "fpga", shares[d][w], a.threads, cpus=a.fpga_cpus)
                    bind(w, wk, d); jobs.append((w, wk))
            fpga_seqs.append((f"FPGA{d}", jobs))
            print(f"scheda {d}: " + ", ".join(f"{RALIAS.get(w, w)}={shares[d][w]}"
                                               for w in order if shares[d].get(w, 0) > 0))
    else:
        jobs = [(w, build_worker(cfg, w, "fpga", n[w], a.threads, cpus=a.fpga_cpus))
                for w in order if n.get(w, 0) > 0]
        if devs:
            for w, wk in jobs:
                bind(w, wk, devs[0])
        fpga_seqs = [("FPGA", jobs)]
    fpga_jobs = [j for _, js in fpga_seqs for j in js]
    cpu_jobs = [(w, build_worker(cfg, w, "cpu", units[w] - n[w], thr_cpu, cpus=a.cpu_cpus))
                for w in order if units[w] - n.get(w, 0) > 0]

    print(f"\nsequenza FPGA: {' -> '.join(RALIAS.get(w,w)+f'({n[w]})' for w,_ in fpga_jobs) or '(vuota)'}")
    print(f"sequenza CPU : {' -> '.join(RALIAS.get(w,w)+f'({units[w]-n[w]})' for w,_ in cpu_jobs) or '(vuota)'}")

    os.makedirs(a.outdir, exist_ok=True)
    seqs = [DeviceSequencer(nm, js) for nm, js in fpga_seqs] + [DeviceSequencer("CPU", cpu_jobs)]
    for s in seqs:
        s.start()

    print("\nAttendo il setup dei primi worker...")
    for s in seqs:
        s.ready.wait()
        if not s.ok:
            print("ERRORE durante il setup", file=sys.stderr)
            return 1
    print(f"Quiete di {a.settle:.0f} s...")
    time.sleep(a.settle)

    t0 = time.time()
    print(f"\n>>> START  {time.strftime('%H:%M:%S')}")
    for s in seqs:
        s.go.set()
    for s in seqs:
        s.done.wait()
    t1 = time.time()
    print(f"<<< END    {time.strftime('%H:%M:%S')}")
    time.sleep(a.settle)

    if not all(s.ok for s in seqs):
        print("ERRORE durante l'esecuzione", file=sys.stderr)
        return 1

    # --- risultati --------------------------------------------------------
    makespan = t1 - t0
    print("\n" + "=" * 66)
    for s in seqs:
        tot = sum(x["calcolo_s"] for x in s.timeline)
        trans = sum(x["transizione_s"] for x in s.timeline)
        print(f"  {s.device}")
        for x in s.timeline:
            print(f"     {RALIAS.get(x['workload'],x['workload']):4s}"
                  f"  calcolo {x['calcolo_s']:8.1f} s"
                  + (f"   transizione {x['transizione_s']:6.1f} s"
                     if x["transizione_s"] else ""))
        print(f"     {'tot':4s}  calcolo {tot:8.1f} s   transizioni {trans:6.1f} s"
              f"   ({100*trans/makespan:.2f}% del makespan)")
    print(f"\n  MAKESPAN {makespan:.1f} s   (previsto {r['T']:.1f} s, "
          f"scarto {100*(makespan-r['T'])/r['T']:+.1f}%)")

    with open(os.path.join(a.outdir, "runs.tsv"), "a") as f:
        alloc = "+".join(f"{RALIAS.get(w,w)}:{n[w]}" for w in sorted(n))
        f.write(f"{a.tag}\t{alloc}\t{t0:.3f}\t{t1:.3f}\tmulti\n")
    with open(os.path.join(a.outdir, f"{a.tag}_timeline.json"), "w") as f:
        json.dump(dict(tag=a.tag, units=units, alloc=n, previsione=r,
                       t_start=t0, t_end=t1, makespan_s=makespan,
                       sequenze={s.device: s.timeline for s in seqs}),
                  f, indent=2)
    print(f"\n  Finestra: {t0:.3f} -> {t1:.3f} (epoch)")
    print(f"  Marcatori in {a.outdir}/runs.tsv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
