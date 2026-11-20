#!/usr/bin/env python3
"""patch_pin_worker.py — versioni con pinning di multi_instance_worker e descrittore.

Uso (dalla cartella energy_comparisons):
    python3 bin/patch_pin_worker.py

Crea, senza toccare gli originali (la campagna fase1 li usa):
  bin/multi_instance_worker_pin.py
      se --core-bases non e' dato, i core di ciascuna istanza vengono presi
      dentro la maschera ricevuta (os.sched_getaffinity), non da 0 in su;
      con maschera completa (0-47) il comportamento e' identico all'originale
  bin/workloads_pin.json
      QP e DE usano multi_instance_worker_pin.py; numero di istanze legato ai
      core concessi: QP min(9, ncpu // 5), DE min(40, ncpu)
"""
import json, sys, os

B = "bin"
src, dst = f"{B}/multi_instance_worker.py", f"{B}/multi_instance_worker_pin.py"
s = open(src).read()
old = """    else:
        bases = [i * a.threads_per_inst for i in range(n)]"""
new = """    else:
        # core concessi dalla maschera ricevuta (taskset di run_multi_pin.py)
        allowed = sorted(os.sched_getaffinity(0))
        tpi = a.threads_per_inst
        if n * tpi > len(allowed):
            sys.exit(f"servono {n * tpi} core ma la maschera ne concede "
                     f"{len(allowed)}: {allowed}")
        bases = [allowed[i * tpi] for i in range(n)]
        for i, b in enumerate(bases):
            if allowed[i * tpi + tpi - 1] != b + tpi - 1:
                sys.exit("maschera non contigua per i thread di un'istanza: "
                         "usare --core-bases")
        print(f"  maschera ricevuta : {allowed[0]}-{allowed[-1]} "
              f"({len(allowed)} core)", file=sys.stderr)"""
if s.count(old) != 1:
    sys.exit(f"ERRORE: blocco da sostituire trovato {s.count(old)} volte")
open(dst, "w").write(s.replace(old, new))
os.chmod(dst, os.stat(src).st_mode)   # eseguibile come l'originale
print(f"scritto {dst}")

c = json.load(open(f"{B}/workloads.json"))
wpin = os.path.abspath(dst)
for w, expr in (("qpdyn", "min(9, ncpu // 5)"), ("deflate", "min(40, ncpu)")):
    d = c[w]["cpu"]
    d["bin"] = wpin
    d.get("consts", {}).pop("instances", None)
    d.setdefault("derived", {})["instances"] = expr
c.setdefault("_globals", {})["_nota_pin"] = (
    "variante per run_multi_pin.py: istanze di QP e DE legate a {ncpu}, "
    "core assegnati dentro la maschera")
json.dump(c, open(f"{B}/workloads_pin.json", "w"), indent=2, ensure_ascii=False)
print(f"scritto {B}/workloads_pin.json")
