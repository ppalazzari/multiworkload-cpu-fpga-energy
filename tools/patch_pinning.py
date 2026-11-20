#!/usr/bin/env python3
"""patch_pinning.py — crea bin/run_multi_pin.py: run_multi.py con il pinning.

Uso (dalla cartella energy_comparisons):
    python3 patch_pinning.py bin/run_multi.py bin/run_multi_pin.py

Non modifica run_multi.py (la campagna fase1 su fpga2 lo sta usando).
Opzioni aggiunte a run_multi_pin.py:
    --cpu-cpus  0-28    i worker CPU girano con taskset -c 0-28,
                        OMP_PLACES=cores, OMP_PROC_BIND=close; se --threads
                        non e' dato, i thread OpenMP sono pari ai core concessi
    --fpga-cpus 29-47   i processi host FPGA girano con taskset -c 29-47
Nel descrittore (workloads.json) diventano disponibili i segnaposto
{ncpu} (numero di core concessi al dispositivo) e {cpus} (la lista).
Senza le due opzioni il comportamento e' identico a run_multi.py.
I thread del driver XRT (uno per unita' di calcolo) sono thread del kernel:
non si possono fissare da utente, finiscono sui core liberi del gruppo FPGA.
"""
import sys

src, dst = sys.argv[1], sys.argv[2]
s = open(src).read()

def rep(old, new, count=1):
    global s
    n = s.count(old)
    if n != count:
        sys.exit(f"ERRORE: atteso {count} occorrenze, trovate {n}:\n{old}")
    s = s.replace(old, new)

# 1. funzione di conteggio dei core, prima di build_worker
rep('def build_worker(cfg, w, device, n_units, threads):',
'''def count_cpus(spec):
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


def build_worker(cfg, w, device, n_units, threads, cpus=None):''')

# 2. segnaposto ncpu e cpus nel contesto
rep('''           "threads": threads, "xclbin": d.get("xclbin", "")}''',
'''           "threads": threads, "xclbin": d.get("xclbin", ""),
           "ncpu": count_cpus(cpus) if cpus else threads, "cpus": cpus or ""}''')

# 3. taskset e variabili OpenMP
rep('''    argv = [d["bin"]] + [str(a).format(**ctx) for a in d["args"]]
    env = dict(os.environ)
    if device == "cpu":
        env["OMP_NUM_THREADS"] = str(threads)''',
'''    argv = [d["bin"]] + [str(a).format(**ctx) for a in d["args"]]
    if cpus:
        argv = ["taskset", "-c", cpus] + argv
    env = dict(os.environ)
    if device == "cpu":
        env["OMP_NUM_THREADS"] = str(threads)
        if cpus:
            env["OMP_PLACES"] = "cores"
            env["OMP_PROC_BIND"] = "close"''')

# 4. opzioni da riga di comando
rep('''    p.add_argument("--threads", type=int, default=48)''',
'''    p.add_argument("--threads", type=int, default=48)
    p.add_argument("--cpu-cpus", default=None,
                   help="core dei worker CPU, es. 0-28 (taskset, OMP_PLACES=cores)")
    p.add_argument("--fpga-cpus", default=None,
                   help="core dei processi host FPGA, es. 29-47 (taskset)")''')

# 5. uso nelle chiamate
rep('build_worker(cfg, w, "fpga", n[w], a.threads)',
    'build_worker(cfg, w, "fpga", n[w], a.threads, cpus=a.fpga_cpus)')
rep('build_worker(cfg, w, "cpu", units[w] - n[w], a.threads)',
    'build_worker(cfg, w, "cpu", units[w] - n[w], thr_cpu, cpus=a.cpu_cpus)')

# 6. thread CPU: pari ai core concessi se --threads non e' esplicito; stampa
rep('''    cfg = json.load(open(a.config))''',
'''    thr_cpu = a.threads
    if a.cpu_cpus and "--threads" not in sys.argv:
        thr_cpu = count_cpus(a.cpu_cpus)
    if a.cpu_cpus or a.fpga_cpus:
        import shutil
        if not shutil.which("taskset"):
            sys.exit("il pinning richiede taskset")
        print(f"pinning: CPU={a.cpu_cpus or 'libero'} ({thr_cpu} thread)  "
              f"FPGA host={a.fpga_cpus or 'libero'}")
    cfg = json.load(open(a.config))''')

open(dst, "w").write(s)
print(f"scritto {dst}")
