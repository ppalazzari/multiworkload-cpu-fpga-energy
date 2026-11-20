#!/usr/bin/env python3
"""build_dev_hosts.py — copie degli host FPGA che rispettano FPGA_DEVICE.

Uso (con l'ambiente Vitis/XRT caricato, da qualunque cartella):
    python3 ~/energy_comparisons/bin/build_dev_hosts.py

Per NBody, DE e IM:
  1. ricava da `make -n -B` il comando di compilazione dell'host originale;
  2. copia il sorgente in <cartella originale>/<nome>_dev.cpp (file nuovo,
     l'originale non viene toccato) e vi inserisce, prima del ciclo sui
     dispositivi, la lettura di FPGA_DEVICE: se e' definita si prova solo
     quel dispositivo, senza ripiego; altrimenti il comportamento e' identico;
  3. compila in ~/energy_comparisons/work/hosts_dev/<nome>_dev.
QP non serve: qp_dyn_power legge gia' QP_DEVICE.
"""
import os, re, shlex, subprocess, sys, shutil

H = os.path.expanduser("~")
OUT = f"{H}/energy_comparisons/work/hosts_dev"
HOSTS = [  # nome, cartella del make, bersaglio, nome del sorgente
    ("nbody_host", f"{H}/workspace/NBody_ver7_OutPeq15_InnerPeq8_U280/migr_u55c", "host", "nbody_main.cpp"),
    ("deflate_host", f"{H}/workspace/Deflate_Vitis_2023_1/migr_u55c", "host", "host_test_power_absorption.cpp"),
    ("ImgProc_plus_Deflate", f"{H}/workspace/DemoHipeac_Weq8Byte_singleKernel/ImgProc_plus_Deflate/Hardware",
     "ImgProc_plus_Deflate", "host.cpp"),
]
LOOP = "for (unsigned int i = 0; i < devices.size(); i++) {"
PATCH = """unsigned int dev_first = 0, dev_last = devices.size() - 1;
    if (const char* fpga_sel = getenv("FPGA_DEVICE")) {   // scheda imposta dall'orchestratore, nessun ripiego
        dev_first = dev_last = (unsigned int) atoi(fpga_sel);
        if (dev_first >= devices.size()) {
            std::cout << "FPGA_DEVICE=" << fpga_sel << " fuori intervallo (" << devices.size() << " dispositivi)\\n";
            exit(EXIT_FAILURE);
        }
        std::cout << "INFO: FPGA_DEVICE=" << fpga_sel << " -> device[" << dev_first << "], nessun ripiego\\n";
    }
    for (unsigned int i = dev_first; i <= dev_last && i < devices.size(); i++) {"""

for v in ("XILINX_XRT", "XILINX_VIVADO"):
    if not os.environ.get(v):
        sys.exit(f"ERRORE: {v} non definita: caricare l'ambiente (es. source ~/env2023.sh)")
os.makedirs(OUT, exist_ok=True)

def recipe(mkdir, target):
    out = subprocess.run(["make", "-C", mkdir, "-n", "-B", target],
                         capture_output=True, text=True).stdout
    out = out.replace("\\\n", " ")
    return [l.strip() for l in out.splitlines()
            if re.match(r"^\S*(g\+\+|c\+\+)\s", l.strip())]

ok = True
for name, mkdir, target, srcname in HOSTS:
    print(f"################ {name}")
    cmds = recipe(mkdir, target)
    if not cmds:
        print("  ERRORE: nessun comando di compilazione da make -n"); ok = False; continue
    # sorgente originale: l'argomento che termina con srcname
    src = None
    for c in cmds:
        for tok in shlex.split(c):
            if tok.endswith(srcname):
                src = os.path.normpath(os.path.join(mkdir, tok)); break
        if src: break
    if not src or not os.path.isfile(src):
        print(f"  ERRORE: sorgente {srcname} non trovato nei comandi"); ok = False; continue
    text = open(src).read()
    if text.count(LOOP) != 1:
        print(f"  ERRORE: ciclo sui dispositivi trovato {text.count(LOOP)} volte in {src}"); ok = False; continue
    dev_src = src[:-4] + "_dev.cpp"
    open(dev_src, "w").write("#include <cstdlib>\n#include <iostream>\n" + text.replace(LOOP, PATCH))
    print(f"  sorgente: {src}\n  copia   : {dev_src}")
    exe = f"{OUT}/{name}_dev"
    obj = f"{OUT}/{name}_dev.o"
    for c in cmds:
        toks = shlex.split(c)
        new = [toks[0], "-I" + os.path.dirname(src)]
        k = 1
        while k < len(toks):
            t = toks[k]
            if t.endswith(srcname):
                new.append(dev_src)
            elif t == "-o" and k + 1 < len(toks):
                dst = toks[k + 1]
                new += ["-o", obj if dst.endswith(".o") else exe]; k += 1
            elif t.endswith(".o") and not t.startswith("-"):
                new.append(obj)                       # oggetto nel comando di link
            else:
                new.append(t)
            k += 1
        print("  $ " + " ".join(new)[:160] + " ...")
        r = subprocess.run(new, cwd=mkdir, capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stderr[-2000:]); ok = False; break
    if os.path.isfile(exe):
        print(f"  OK -> {exe}")
    else:
        print("  ERRORE: eseguibile non prodotto"); ok = False
sys.exit(0 if ok else 1)
