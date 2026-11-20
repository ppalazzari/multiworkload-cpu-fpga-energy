#!/usr/bin/env python3
"""analisi_interferenza.py — matrice di rallentamento CPU/FPGA dalle timeline.

Uso:
  python3 analisi_interferenza.py <cartella_campagna> [--ref ref_cpu] [--pidle 712]
                                  [--sweep QP:30 NB:16-30]

Legge <cartella>/*_timeline.json prodotti da run_multi.py e:
  1. ricava i tempi per unita' isolati della CPU dalla run di riferimento
     (tutto-CPU, default 'ref_cpu') e quelli della FPGA da 'ref_fpga' se c'e';
  2. stima, ai minimi quadrati, il rallentamento s(v|u) del workload CPU v
     mentre la FPGA esegue il workload u (ogni segmento CPU e' un'equazione:
     sum_fasi overlap / s(v|u) = n_v * t_iso(v), con s(v|nessuno) = 1);
  3. rigioca ogni run con i rallentamenti stimati e confronta i makespan;
  4. con --sweep, prevede T ed E per una famiglia di ripartizioni,
     con ordine dei workload per rho decrescente (default di run_multi.py).

Versione usata per la tabella V dell'articolo: cartella quattro_0918,
risultato atteso QP|NB ~28 (una run), NB|QP 1.41, DE|NB 1.67, IM|NB 1.56.
"""
import json, glob, os, sys, argparse
import numpy as np

# parametri del modello (tabella III dell'articolo, P_idle 712 W)
EF = {'qpdyn': 325, 'nbody': 3608, 'deflate': 834, 'algo3': 607}
EC = {'qpdyn': 14072, 'nbody': 15533, 'deflate': 8269, 'algo3': 7645}
ORDER = ['qpdyn', 'nbody', 'deflate', 'algo3']          # rho decrescente
ALIAS = {'QP': 'qpdyn', 'NB': 'nbody', 'DE': 'deflate', 'IM': 'algo3'}

def carica(cart):
    runs = {}
    for f in sorted(glob.glob(os.path.join(cart, '*_timeline.json'))):
        d = json.load(open(f)); t0 = d['t_start']
        def segs(dev):
            out = []
            for s in d['sequenze'][dev]:
                w = s['workload']
                n = d['alloc'][w] if dev == 'FPGA' else d['units'][w] - d['alloc'][w]
                out.append((w, n, s['t_start'] - t0, s['t_end'] - t0, s['calcolo_s']))
            return out
        runs[d['tag']] = dict(T=d['makespan_s'], F=segs('FPGA'), C=segs('CPU'))
    return runs

def stima(runs, ref):
    iso = {w: c / n for (w, n, a, b, c) in runs[ref]['C']}
    rows, rhs, lab = [], [], []
    for r, d in runs.items():
        if r == ref: continue
        ph = [(a, b, w) for (w, n, a, b, c) in d['F']]
        for (v, n, a, b, c) in d['C']:
            ov, cov = {}, 0.0
            for (pa, pb, u) in ph:
                o = max(0.0, min(b, pb) - max(a, pa))
                if o > 0: ov[(v, u)] = ov.get((v, u), 0) + o; cov += o
            rows.append(ov); rhs.append(n * iso[v] - ((b - a) - cov)); lab.append((r, v))
    keys = sorted({k for ro in rows for k, o in ro.items() if o > 1})
    A = np.array([[ro.get(k, 0.0) for k in keys] for ro in rows]); y = np.array(rhs)
    r_, *_ = np.linalg.lstsq(A, y, rcond=None)
    slow = {k: (1 / x if x > 1e-3 else float('inf')) for k, x in zip(keys, r_)}
    return iso, slow

def rigioca(d, iso, slow, usa=True):
    ph = [(a, b, w) for (w, n, a, b, c) in d['F']]
    t = 0.0
    for i, (v, n, a, b, c) in enumerate(d['C']):
        if i > 0: t += a - d['C'][i - 1][3]          # transizione misurata
        work = n * iso[v]
        while work > 1e-9:
            u, end = None, 1e18
            for (pa, pb, w) in ph:
                if pa <= t < pb: u, end = w, pb; break
                if pa > t: end = min(end, pa)
            s = slow.get((v, u), 1.0) if (u and usa) else 1.0
            dt = min(end - t, work * s); t += dt; work -= dt / s
    return max(t, max([b for (a, b, w) in ph], default=0.0))

def prevedi(alloc, iso, fiso, slow, P, N=30, cfg_nb=11.0, cfg=5.8, init_nb=60.0):
    F, t, first = [], 0.0, True
    for w in ORDER:
        if alloc.get(w, 0) > 0:
            if not first: t += cfg_nb if w == 'nbody' else cfg
            F.append((w, alloc[w], t, t + alloc[w] * fiso[w], 0)); t += alloc[w] * fiso[w]; first = False
    C = [(w, N - alloc.get(w, 0), 0, 0, 0) for w in ORDER if N - alloc.get(w, 0) > 0]
    ph = [(a, b, w) for (w, n, a, b, c) in F]; t = 0.0
    for i, (v, n, *_r) in enumerate(C):
        if i > 0: t += init_nb if v == 'nbody' else 2.0
        work = n * iso[v]
        while work > 1e-9:
            u, end = None, 1e18
            for (pa, pb, w) in ph:
                if pa <= t < pb: u, end = w, pb; break
                if pa > t: end = min(end, pa)
            s = slow.get((v, u), 1.0) if u else 1.0
            dt = min(end - t, work * s); t += dt; work -= dt / s
    T = max(t, max([b for (a, b, w) in ph], default=0.0))
    Eapp = sum(alloc.get(w, 0) * EF[w] + (N - alloc.get(w, 0)) * EC[w] for w in ORDER)
    return T, (Eapp + P * T) / 1e3

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('cartella'); ap.add_argument('--ref', default='ref_cpu')
    ap.add_argument('--pidle', type=float, default=712.0)
    ap.add_argument('--sweep', nargs=2, metavar=('FISSO', 'VARIABILE'),
                    help='es. QP:30 NB:16-30')
    a = ap.parse_args()
    runs = carica(a.cartella)
    iso, slow = stima(runs, a.ref)
    fiso = ({w: c / n for (w, n, x, y, c) in runs['ref_fpga']['F']} if 'ref_fpga' in runs
            else {'qpdyn': 45.19, 'nbody': 44.54, 'deflate': 59.14, 'algo3': 60.08})
    print('tempi isolati CPU (s/unita):', {k: round(v, 2) for k, v in iso.items()})
    print('\nrallentamenti s(CPU|FPGA):')
    for (v, u), s in sorted(slow.items()):
        print(f'  {v:8} | {u:8}  {s:6.2f}')
    print('\nrun        T misurato   senza rall.        con rall.')
    for r, d in runs.items():
        t0, t1 = rigioca(d, iso, slow, False), rigioca(d, iso, slow, True)
        print(f'{r:10} {d["T"]:9.1f}  {t0:8.1f} ({(d["T"]/t0-1)*100:+5.1f}%)  {t1:8.1f} ({(d["T"]/t1-1)*100:+5.1f}%)')
    if a.sweep:
        fw, fn = a.sweep[0].split(':'); vw, rng = a.sweep[1].split(':')
        lo, hi = map(int, rng.split('-'))
        print(f'\nprevisione con rallentamenti, {a.sweep[0]} e {vw} da {lo} a {hi}:')
        for x in range(lo, hi + 1):
            T, E = prevedi({ALIAS[fw]: int(fn), ALIAS[vw]: x}, iso, fiso, slow, a.pidle)
            print(f'  {vw}{x:2}  T = {T:7.1f} s   E = {E:7.1f} kJ')
