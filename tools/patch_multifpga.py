#!/usr/bin/env python3
"""patch_multifpga.py — piu' schede FPGA in run_multi_pin.py e descrittore.

Uso (dalla cartella energy_comparisons, dopo build_dev_hosts.py):
    python3 bin/patch_multifpga.py

1. bin/run_multi_pin.py (copia di sicurezza .bak_multifpga): opzione
   --fpga-devices 0,1. Una sequenza per scheda (FPGA0, FPGA1, ...); le
   unita' di ogni workload sono divise in parti uguali e i resti assegnati a
   turno fra le schede; a ogni processo host viene passato l'indice della
   scheda nella variabile fpga.device_env del workload (default FPGA_DEVICE).
   Con una sola scheda indicata, la lega a quella; senza l'opzione, nulla cambia.
2. bin/workloads_pin.json: host _dev per NB, DE, IM; device_env
   (QP_DEVICE per QP, FPGA_DEVICE per gli altri); _globals.fpga_devices.
"""
import json, os, shutil, sys

B = "bin"; H = os.path.expanduser("~")
p = f"{B}/run_multi_pin.py"
s = open(p).read()
if "--fpga-devices" in s:
    print("run_multi_pin.py ha gia' --fpga-devices: salto la modifica")
else:
    shutil.copy(p, p + ".bak_multifpga")
    def rep(old, new):
        global s
        if s.count(old) != 1:
            sys.exit(f"ERRORE: trovato {s.count(old)} volte:\n{old}")
        s = s.replace(old, new)
    rep('''    p.add_argument("--fpga-cpus", default=None,''',
'''    p.add_argument("--fpga-devices", default="",
                   help="indici delle schede, es. 0,1: una sequenza FPGA per scheda")
    p.add_argument("--fpga-cpus", default=None,''')
    rep('''    fpga_jobs = [(w, build_worker(cfg, w, "fpga", n[w], a.threads, cpus=a.fpga_cpus))
                 for w in order if n.get(w, 0) > 0]''',
'''    devs = [int(x) for x in a.fpga_devices.split(",") if x.strip()] if a.fpga_devices else []
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
    fpga_jobs = [j for _, js in fpga_seqs for j in js]''')
    rep('''    seqs = [DeviceSequencer("FPGA", fpga_jobs), DeviceSequencer("CPU", cpu_jobs)]''',
        '''    seqs = [DeviceSequencer(nm, js) for nm, js in fpga_seqs] + [DeviceSequencer("CPU", cpu_jobs)]''')
    open(p, "w").write(s)
    print(f"scritto {p} (copia in {p}.bak_multifpga)")

j = f"{B}/workloads_pin.json"
c = json.load(open(j))
dev = f"{H}/energy_comparisons/work/hosts_dev"
for w, exe in (("nbody", "nbody_host_dev"), ("deflate", "deflate_host_dev"),
               ("algo3", "ImgProc_plus_Deflate_dev")):
    if not os.path.isfile(f"{dev}/{exe}"):
        sys.exit(f"ERRORE: manca {dev}/{exe}: eseguire prima build_dev_hosts.py")
    c[w]["fpga"]["bin"] = f"{dev}/{exe}"
    c[w]["fpga"]["device_env"] = "FPGA_DEVICE"
c["qpdyn"]["fpga"]["device_env"] = "QP_DEVICE"
c["_globals"]["fpga_devices"] = [
    {"index": 0, "bdf": "0000:33:00.1"}, {"index": 1, "bdf": "0000:cc:00.1"}]
json.dump(c, open(j, "w"), indent=2, ensure_ascii=False)
print(f"aggiornato {j}")
