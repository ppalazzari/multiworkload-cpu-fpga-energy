#!/usr/bin/env python3
"""
multi_instance_worker.py — lancia N istanze di un binario e le presenta
all'orchestratore come un singolo worker conforme al contratto.

Serve quando il programma CPU non satura da solo il nodo: zlib e'
monothread (una istanza per core), QP-DYN usa 4 thread per istanza.

Verso l'esterno si comporta come un worker qualsiasi:

    [avvia le istanze, attende il loro @@READY]
    stampa "@@READY"  -> attende '\\n'
    [rilascia tutte le istanze simultaneamente]
    [attende tutti i loro @@DONE]
    stampa "@@DONE"   -> attende '\\n'

Uso:
    multi_instance_worker.py --bin BIN --instances N --units U [opzioni] -- ARGS...

    Negli ARGS, i segnaposto vengono sostituiti per ciascuna istanza:
      {units}   unita' assegnate a questa istanza
      {idx}     indice dell'istanza (0-based)
      {core}    primo core assegnato: idx * threads_per_inst, oppure
                l'elemento idx di --core-bases se specificato

Esempi:

  # Deflate: 48 istanze zlib monothread, una per core
  multi_instance_worker.py --bin ./deflate_cpu --instances 48 --units 480 \\
      -- /path/wiki_1GB.xml {units} 128 {core}

  # QP-DYN: 8 istanze, ciascuna con il proprio thread principale vincolato a
  # un core dedicato (il thread principale attende in modo attivo: senza
  # vincolo finisce dove capita e rallenta l'istanza)
  multi_instance_worker.py --bin ./qp_dyn_quad_omp --instances 8 --units 80 \\
      --threads-per-inst 4 --core-bases 0,4,8,12,24,28,32,36 \\
      --main-cores 16,17,18,19,40,41,42,43 \\
      --env QP_CPU_BASE={core} --env OMP_NUM_THREADS=4 -- /path/workdir {units}

  # QP-DYN su due socket, lasciando liberi i core 20-23 e 40-47
  multi_instance_worker.py --bin ./qp_dyn_quad_omp --instances 8 --units 80 \\
      --threads-per-inst 4 --core-bases 0,4,8,12,24,28,32,36 \\
      --env QP_CPU_BASE={core} --env OMP_NUM_THREADS=4 -- /path/workdir {units}

  # QP-DYN: 9 istanze da 4 thread, affinita' via QP_CPU_BASE
  multi_instance_worker.py --bin ./qp_dyn_quad_omp --instances 9 --units 90 \\
      --threads-per-inst 4 --env QP_CPU_BASE={core} --env OMP_NUM_THREADS=4 \\
      -- /path/workdir {units}
"""

import argparse
import os
import shutil
import subprocess
import sys
import threading
import time

READY = "@@READY"
DONE = "@@DONE"


class Instance:
    def __init__(self, idx, argv, env):
        self.idx = idx
        self.argv = [str(a) for a in argv]
        self.env = env
        self.proc = None
        self.ready = threading.Event()
        self.done = threading.Event()
        self.log = []

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
                self.ready.set()
            elif DONE in line:
                self.done.set()
            else:
                # l'output delle istanze va su stderr: lo stdout del worker
                # e' riservato ai marcatori per l'orchestratore
                print(f"[inst{self.idx}] {line}", file=sys.stderr)

    def release(self):
        self.proc.stdin.write("\n")
        self.proc.stdin.flush()

    def wait_event(self, ev, what):
        while not ev.wait(timeout=1.0):
            if self.proc.poll() is not None:
                print(f"ERRORE: istanza {self.idx} terminata "
                      f"(codice {self.proc.returncode}) senza {what}",
                      file=sys.stderr)
                for ln in self.log[-10:]:
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
            return self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            return self.proc.wait(timeout=10)


def barrier(marker):
    """Barriera verso l'orchestratore."""
    print(marker, flush=True)
    for _ in sys.stdin:
        break


def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bin", required=True, help="binario da lanciare")
    p.add_argument("--instances", type=int, required=True)
    p.add_argument("--units", type=int, required=True,
                   help="unita' totali, ripartite fra le istanze")
    p.add_argument("--threads-per-inst", type=int, default=1,
                   help="usato per calcolare {core} (default 1)")
    p.add_argument("--core-bases", default="",
                   help="primo core di ciascuna istanza, separati da virgola "
                        "(es. 0,4,8,12,24,28,32,36); sostituisce idx*threads_per_inst")
    p.add_argument("--main-cores", default="",
                   help="core dedicato al processo di ciascuna istanza, separati da "
                        "virgola; l'istanza viene lanciata con taskset -c <core>. "
                        "I thread che il programma vincola da se' (QP_CPU_BASE) "
                        "vengono poi spostati sui propri core; il thread principale "
                        "resta su quello indicato qui")
    p.add_argument("--env", action="append", default=[],
                   metavar="NOME=VALORE",
                   help="variabile d'ambiente per le istanze; accetta i "
                        "segnaposto {idx} {core} {units}")
    p.add_argument("args", nargs=argparse.REMAINDER,
                   help="argomenti del binario, dopo --")
    a = p.parse_args()

    extra = a.args[1:] if a.args and a.args[0] == "--" else a.args

    # ripartizione delle unita': il resto va alle prime istanze
    base, rest = divmod(a.units, a.instances)
    shares = [base + (1 if i < rest else 0) for i in range(a.instances)]
    shares = [s for s in shares if s > 0]
    n = len(shares)

    if a.core_bases:
        try:
            bases = [int(x) for x in a.core_bases.split(",") if x.strip() != ""]
        except ValueError:
            sys.exit(f"--core-bases malformato: {a.core_bases!r}")
        if len(bases) < n:
            sys.exit(f"--core-bases ha {len(bases)} voci ma servono {n} istanze")
    else:
        bases = [i * a.threads_per_inst for i in range(n)]

    mains = []
    if a.main_cores:
        try:
            mains = [int(x) for x in a.main_cores.split(",") if x.strip() != ""]
        except ValueError:
            sys.exit(f"--main-cores malformato: {a.main_cores!r}")
        if len(mains) < n:
            sys.exit(f"--main-cores ha {len(mains)} voci ma servono {n} istanze")
        overlap = set(mains[:n]) & {b + t for b in bases[:n] for t in range(a.threads_per_inst)}
        if overlap:
            sys.exit(f"--main-cores si sovrappone ai core di calcolo: {sorted(overlap)}")
        if not shutil.which("taskset"):
            sys.exit("--main-cores richiede taskset")

    print(f"worker: {n} istanze x {a.threads_per_inst} thread "
          f"= {n * a.threads_per_inst} core", file=sys.stderr)
    print(f"  unita' per istanza: {shares}", file=sys.stderr)
    print(f"  core di partenza  : {bases[:n]}", file=sys.stderr)
    if mains:
        print(f"  thread principali : {mains[:n]}", file=sys.stderr)

    instances = []
    for i, share in enumerate(shares):
        ctx = {"idx": i, "core": bases[i], "units": share}
        env = dict(os.environ)
        for e in a.env:
            if "=" not in e:
                sys.exit(f"--env malformato: {e!r} (serve NOME=VALORE)")
            k, v = e.split("=", 1)
            env[k] = v.format(**ctx)
        argv = [a.bin] + [str(x).format(**ctx) for x in extra]
        if mains:
            argv = ["taskset", "-c", str(mains[i])] + argv
        instances.append(Instance(i, argv, env))

    if instances:
        print(f"  esempio: {' '.join(instances[0].argv)}", file=sys.stderr)

    for inst in instances:
        inst.start()

    for inst in instances:
        if not inst.wait_event(inst.ready, READY):
            for x in instances:
                if x.proc.poll() is None:
                    x.proc.kill()
            return 1
    print("tutte le istanze pronte", file=sys.stderr)

    # --- barriera esterna -------------------------------------------------
    barrier(READY)

    t0 = time.time()
    for inst in instances:
        inst.release()

    for inst in instances:
        if not inst.wait_event(inst.done, DONE):
            return 1
    t1 = time.time()

    barrier(DONE)
    # ----------------------------------------------------------------------

    for inst in instances:
        inst.finish()

    print(f"worker: {t1-t0:.2f} s per {a.units} unita'", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
