#!/usr/bin/env python3
"""misura_ecfg.py — carica a turno i bitstream di QP, DE e IM su una scheda,
con un lavoro minimo (1 blocco), per misurare tempo ed energia della
transizione (riprogrammazione + preparazione dell'host).

Uso:  python3 bin/misura_ecfg.py --config bin/workloads_qp8.json --device 1 \
          --reps 30 --gap 25 --out <cartella>
Scrive <out>/caricamenti.tsv: workload, ripetizione, t0 (lancio), tready
(l'host annuncia @@READY: bitstream caricato e dati pronti), t1 (fine del
blocco di lavoro), codice di uscita. Protocollo come nell'orchestratore:
l'host attende il via sul proprio stdin dopo @@READY.
Il bitstream cambia a ogni caricamento, quindi XRT non puo' saltare la
programmazione.
"""
import argparse, json, os, subprocess, time

p = argparse.ArgumentParser()
p.add_argument("--config", required=True)
p.add_argument("--device", type=int, default=1)
p.add_argument("--reps", type=int, default=30)
p.add_argument("--gap", type=float, default=25.0)
p.add_argument("--out", required=True)
a = p.parse_args()
cfg = json.load(open(a.config))
os.makedirs(a.out, exist_ok=True)

def comando(w):
    f = cfg[w]["fpga"]
    sub = dict(f.get("consts", {}))
    sub["n_items"] = "1"
    sub["xclbin"] = f.get("xclbin") or sub.get("xclbin")
    if not sub["xclbin"] or not os.path.isfile(sub["xclbin"]):
        raise SystemExit(f"ERRORE: xclbin di {w} non trovato nel descrittore: {sub['xclbin']}")
    argv = [f["bin"]] + [str(x).format(**sub) for x in f["args"]]
    env = dict(os.environ, **{k: str(v) for k, v in (f.get("env") or {}).items()})
    env[f.get("device_env", "FPGA_DEVICE")] = str(a.device)
    return argv, env

wl = ["qpdyn", "deflate", "algo3"]
cmds = {w: comando(w) for w in wl}
for w in wl:
    print(w, " ".join(cmds[w][0]))
with open(os.path.join(a.out, "caricamenti.tsv"), "w") as tsv:
    tsv.write("workload\trip\tt0\ttready\tt1\tcodice\n")
    for r in range(1, a.reps + 1):
        for w in wl:
            argv, env = cmds[w]
            log = open(os.path.join(a.out, f"{w}_{r}.out"), "w")
            t0 = time.time(); tready = float("nan")
            pr = subprocess.Popen(argv, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, bufsize=1)
            for line in pr.stdout:
                log.write(line)
                if line.startswith("@@READY"):
                    tready = time.time()
                    pr.stdin.write("GO\n"); pr.stdin.flush(); pr.stdin.close()
            rc = pr.wait(); t1 = time.time(); log.close()
            tsv.write(f"{w}\t{r}\t{t0:.3f}\t{tready:.3f}\t{t1:.3f}\t{rc}\n"); tsv.flush()
            print(f"[{time.strftime('%H:%M:%S')}] {w} rip {r}: transizione {tready-t0:.1f} s, "
                  f"lavoro {t1-tready:.1f} s, codice {rc}", flush=True)
            time.sleep(a.gap)
