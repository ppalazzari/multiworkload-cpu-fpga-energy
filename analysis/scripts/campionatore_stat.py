#!/usr/bin/env python3
"""campionatore_stat.py — registra ogni secondo il tempo di CPU occupato
dell'intero nodo, da /proc/stat (riga "cpu": user+nice+system+irq+softirq+steal).
Uscita: epoca <TAB> core-secondi occupati cumulati (in secondi di core).
Uso: python3 campionatore_stat.py > file.tsv   (si ferma con un segnale)
"""
import os, time, sys
HZ = os.sysconf("SC_CLK_TCK")
while True:
    with open("/proc/stat") as f:
        v = [int(x) for x in f.readline().split()[1:]]
    busy = v[0] + v[1] + v[2] + v[5] + v[6] + (v[7] if len(v) > 7 else 0)
    print(f"{time.time():.3f}\t{busy / HZ:.2f}", flush=True)
    time.sleep(1.0)
