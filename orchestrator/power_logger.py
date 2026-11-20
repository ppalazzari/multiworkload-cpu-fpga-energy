#!/usr/bin/python3
"""
power_logger.py
---------------
Campiona ogni secondo:
  - potenza totale del nodo via IPMI (AC wall-plug)
  - potenza delle schede U55C via xrt-smi (SOLO se eseguito sul nodo che
    ospita le schede: da remoto le colonne restano N/A)

Output TSV su stdout:
  Epoch  Node_W  Timestamp_UTC  IPMI_Timestamp  [FPGA_i_W ...]

Uso:
  python3 power_logger.py [--host BMC] [--user UTENTE] [--no-fpga] [bdf ...]

  --host     BMC da interrogare (default: $IPMI_HOST, altrimenti fpga1)
  --no-fpga  non interroga xrt-smi: da usare quando il logger gira su un
             nodo diverso da quello misurato
  --inband   interroga il BMC del nodo stesso via /dev/ipmi0, senza rete e
             senza password. Serve l'accesso a /dev/ipmi0: direttamente
             (gruppo ipmi, come su fpgas1) oppure via sudo, che viene
             attivato da solo se il dispositivo non e' leggibile.
  --sudo     forza l'uso di sudo -n anche se /dev/ipmi0 sembra leggibile.
             Sul nodo misurato conviene legare il logger a una CPU libera:
               taskset -c 47 python3 power_logger.py --inband --no-fpga > log

  La password si passa in $IPMI_PWD. Esempio, logger su fpga1 che misura
  fpga2:
    source ~/.ipmi_env
    python3 power_logger.py --host cresco8-fpga2-mg.vlancresco --no-fpga \\
        > campagna.log 2>/dev/null &
"""

import os
import sys
import time
import subprocess
import re
from datetime import datetime

# ── Configurazione IPMI nodo ────────────────────────────────────────
IPMI_ADDRESS = os.environ.get("IPMI_HOST", "cresco8-fpga1-mg.vlancresco")
INBAND = False
SUDO = False
IPMI_USER    = "admin"
IPMI_PWD    = os.environ.get("IPMI_PWD", "")

# ── BDF delle schede U55C su cresco8-fpga1 ──────────────────────────
# Aggiorna se diversi (vedi: xrt-smi examine)
DEFAULT_BDFS = ["0000:cc:00.1"]   # aggiungi seconda scheda se presente

# ── Legge potenza nodo via IPMI ─────────────────────────────────────
def read_node_power():
    """Restituisce (inst_W, ipmi_timestamp_str) oppure (None, None)."""
    if INBAND:
        # BMC del nodo stesso via /dev/ipmi0: niente rete, niente password.
        # Se /dev/ipmi0 non e' leggibile dall'utente serve sudo (-n: non
        # chiede la password, fallisce subito se non e' autorizzato).
        cmd = (["sudo", "-n"] if SUDO else []) + ["ipmitool", "dcmi", "power", "reading"]
        env = None
    else:
        # password passata via ambiente (-E): non compare nella lista processi
        cmd = ["ipmitool", "-I", "lanplus", "-H", IPMI_ADDRESS,
               "-U", IPMI_USER, "-E", "dcmi", "power", "reading"]
        env = dict(os.environ, IPMI_PASSWORD=IPMI_PWD or "")
    try:
        out = subprocess.check_output(
            cmd, env=env, stderr=subprocess.DEVNULL, timeout=3
        ).decode()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None, None

    inst_pw = ts_pw = None
    for line in out.splitlines():
        if "Instantaneous power reading" in line:
            m = re.search(r'(\d+)\s+Watts', line)
            if m: inst_pw = int(m.group(1))
        if "IPMI timestamp" in line:
            parts = line.split()
            ts_pw = "-".join(parts[3:7]) if len(parts) >= 7 else None

    return inst_pw, ts_pw

# ── Legge potenza scheda FPGA via xrt-smi ───────────────────────────
def read_fpga_power(bdf):
    """Restituisce la potenza totale in W (float) oppure None."""
    try:
        out = subprocess.check_output(
            f"xrt-smi examine -r electrical --device {bdf}",
            shell=True, stderr=subprocess.DEVNULL, timeout=3
        ).decode()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None

    for line in out.splitlines():
        # La riga "  Power  : XX.XXXXXX Watts"
        if re.match(r'\s+Power\s+:', line) and 'Warning' not in line \
                and 'Max' not in line and 'Rails' not in line:
            m = re.search(r'([\d.]+)\s+Watts', line)
            if m:
                return float(m.group(1))
    return None

# ── Main ─────────────────────────────────────────────────────────────
def main():
    global IPMI_ADDRESS, IPMI_USER
    import argparse
    ap = argparse.ArgumentParser(description="logger di potenza IPMI + xrt-smi")
    ap.add_argument("--host", default=IPMI_ADDRESS, help="BMC da interrogare")
    ap.add_argument("--user", default=IPMI_USER)
    ap.add_argument("--sudo", action="store_true",
                    help="con --inband, invoca ipmitool tramite sudo -n. Attivato da "
                         "solo se /dev/ipmi0 non e' leggibile dall'utente")
    ap.add_argument("--inband", action="store_true",
                    help="interroga il BMC del nodo locale via /dev/ipmi0 "
                         "(nessuna rete, nessuna password; serve il gruppo ipmi)")
    ap.add_argument("--no-fpga", action="store_true",
                    help="non leggere la potenza delle schede (logger remoto)")
    ap.add_argument("bdfs", nargs="*", help="BDF delle schede da leggere")
    a = ap.parse_args()
    global INBAND, SUDO
    INBAND = a.inband
    SUDO = a.sudo
    if INBAND and not SUDO and not os.access("/dev/ipmi0", os.R_OK):
        SUDO = True
        print("[INFO] /dev/ipmi0 non leggibile: uso sudo -n", file=sys.stderr)
    IPMI_ADDRESS, IPMI_USER = a.host, a.user
    if INBAND:
        IPMI_ADDRESS = "in-band (/dev/ipmi0)"
    elif not IPMI_PWD:
        print("[WARN] IPMI_PWD vuota: le letture IPMI falliranno", file=sys.stderr)
    bdfs = [] if a.no_fpga else (a.bdfs or DEFAULT_BDFS)
    print(f"[INFO] BMC {IPMI_ADDRESS}, schede: {bdfs or 'nessuna'}", file=sys.stderr)

    # Header
    fpga_headers = "\t".join(f"FPGA_{i}_W ({bdf})"
                              for i, bdf in enumerate(bdfs))
    print(f"Epoch\tNode_W\tTimestamp_UTC\tIPMI_Timestamp\t{fpga_headers}", flush=True)
    print("Press CTRL-C to stop.", file=sys.stderr)

    while True:
        t0 = time.time()
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        # Lettura IPMI (asincrona rispetto alle FPGA)
        node_w, ipmi_ts = read_node_power()
        node_str  = str(node_w)  if node_w  is not None else "N/A"
        ipmi_str  = ipmi_ts      if ipmi_ts is not None else "N/A"

        # Lettura potenza ogni scheda FPGA
        fpga_vals = []
        for bdf in bdfs:
            pw = read_fpga_power(bdf)
            fpga_vals.append(f"{pw:.3f}" if pw is not None else "N/A")

        fpga_str = "\t".join(fpga_vals)
#        print(f"{ts}\t{ipmi_str}\t{node_str}\t{fpga_str}", flush=True)
        print(f"{t0:.3f}\t{node_str}\t{ts}\t{ipmi_str}\t{fpga_str}", flush=True)

        # Attendi fino al prossimo secondo (compensando il tempo di esecuzione)
        elapsed = time.time() - t0
        sleep_t = max(0.0, 1.0 - elapsed)
        if sleep_t < 0.05:
            # La lettura ha impiegato quasi 1s — avvisa su stderr
            print(f"[WARN] lettura lenta ({elapsed:.2f}s)", file=sys.stderr)
        time.sleep(sleep_t)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrotto.", file=sys.stderr)
