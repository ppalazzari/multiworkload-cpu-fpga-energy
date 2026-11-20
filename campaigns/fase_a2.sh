#!/bin/bash
# fase_a2.sh — ripetizione della campagna A (tre workload, test di priorita').
#
# Motivo: nella campagna A originale (prio3_0918) il log di potenza e' andato
# perso per 6 run su 11 (logger su AFS morto con la sessione). Si ripete con la
# procedura delle campagne C-F: pagsh, log in /tmp, finestre di idle dedicate.
#
# Nodo: N48 (cresco8-fpga2 o cresco8-fpga1), governor performance, una U55C (scheda 0).
# Allocazioni (IM, DE, QP), N = 30, alternate, 4 ripetizioni ciascuna:
#   (0, 4, 30)  segue l'ordinamento per rho   previsto T 1624.4 s, E 1614.0 kJ (P_idle 712 W)
#   (4, 0, 30)  viola l'ordinamento           previsto T 1689.1 s, E 1661.7 kJ
#   (previsioni con i parametri della Tabella III, t_cfg 5.4 s)
# Durata: ~4.5 h (8 run da ~28 min + pause + 2 finestre di idle da 5 min).
#
# Uso:
#   ./fase_a2.sh --check
#   pagsh -c 'aklog && setsid nohup ~/fase_a2.sh > /tmp/a2_$(date +%m%d_%H%M).log 2>&1 < /dev/null &'

set -u
BASE=${BASE:-$HOME/energy_comparisons}
PAUSA=${PAUSA:-180}
IDLE=${IDLE:-300}
RIP=${RIP:-4}
STAMP=$(date +%m%d_%H%M)
NODE=$(hostname -s)
OUT=$BASE/work/raw/a2_${NODE}_$STAMP
PLOG=/tmp/a2_power_$STAMP.log
PERR=/tmp/a2_power_err_$STAMP.log
RM=bin/run_multi_pin.py
CFG=bin/workloads_pin.json
UNITS="IM:30,DE:30,QP:30"

# Governor: profilo tuned "hpc-compute" (governor performance) all'inizio e
# profilo "cresco8" (governor schedutil, ventole meno rumorose) alla fine, anche
# in caso di errore o interruzione (trap). SETTLE: attesa dopo il cambio, perche'
# ventole e temperature si stabilizzino prima della finestra di idle.
TUNED=${TUNED:-/usr/sbin/tuned-adm}
PROF_MISURA=${PROF_MISURA:-hpc-compute}
PROF_FINE=${PROF_FINE:-cresco8}
SETTLE=${SETTLE:-600}
say () { echo "[$(date +%H:%M:%S)] $*"; }

check () {
    local ok=1 gov
    gov=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor)
    say "nodo: $NODE   governor: $gov   XRT: $(xrt-smi --version 2>/dev/null | grep -m1 -i version | tr -s ' ')"
    [[ $NODE == cresco8-fpga[12] ]] || { say "ERRORE: va lanciato su un nodo N48"; ok=0; }
    if [[ $gov != performance ]]; then
        if sudo -n -l $TUNED >/dev/null 2>&1; then
            say "governor $gov: lo script attivera' il profilo $PROF_MISURA e alla fine $PROF_FINE"
        else
            say "ERRORE: governor $gov e nessun permesso sudo per cambiarlo"; ok=0
        fi
    fi
    grep -q -- "--fpga-devices" "$BASE/$RM" || { say "ERRORE: $RM senza --fpga-devices"; ok=0; }
    python3 - "$BASE/$CFG" <<'EOF' || ok=0
import json, os, sys
c = json.load(open(sys.argv[1]))
for w in ("deflate", "algo3", "qpdyn"):
    f = c[w]["fpga"]
    if not f.get("device_env") or not os.path.isfile(f["bin"]):
        print("ERRORE:", w, "senza device_env o host mancante:", f.get("bin")); sys.exit(1)
if not c["qpdyn"]["fpga"]["bin"].endswith("_mdev"):
    print("ERRORE: QP deve usare qp_dyn_power_mdev (binding con QP_DEVICE)"); sys.exit(1)
EOF
    [[ -f /sys/bus/pci/devices/0000:33:00.1/kdsstat ]] || { say "ERRORE: scheda 0 non visibile"; ok=0; }
    if pgrep -u "$USER" -f "run_multi|power_logger.py|\.xclbin" > /dev/null; then
        say "ERRORE: processi gia' attivi:"; pgrep -u "$USER" -af "run_multi|power_logger.py|\.xclbin"; ok=0
    fi
    tokens 2>/dev/null | grep -i "tokens for" || say "ATTENZIONE: nessun token"
    return $(( ok == 1 ? 0 : 1 ))
}
if [[ ${1:-} == --check ]]; then check; exit $?; fi
check || { say "controlli falliti, campagna non avviata"; exit 1; }

profilo () {   # profilo <tuned> <governor atteso>: attiva e verifica su tutti i core
    sudo -n $TUNED profile "$1" >/dev/null 2>&1
    sleep 5
    local n; n=$(grep -c -v "^$2$" /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor | awk -F: '{s+=$2} END {print s}')
    (( n == 0 )) && say "profilo $1 attivo: governor $2 su tutti i core" || say "ATTENZIONE: profilo $1, $n core non in $2"
    return $(( n == 0 ? 0 : 1 ))
}
GOV_INIZIO=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor)
ripristino () {
    [[ -n ${LPID:-} ]] && kill "$LPID" 2>/dev/null
    profilo "$PROF_FINE" schedutil || true
}
trap ripristino EXIT
trap 'exit 1' INT TERM HUP
if ! PYTHONUNBUFFERED=1 $TUNED active 2>/dev/null | grep -q "$PROF_MISURA"; then
    profilo "$PROF_MISURA" performance || { say "ERRORE: impossibile attivare $PROF_MISURA"; exit 1; }
    if [[ $GOV_INIZIO != performance ]]; then
        say "attesa di stabilizzazione: $SETTLE s"; sleep "$SETTLE"
    fi
fi

mkdir -p "$OUT"
say "avvio logger -> $PLOG"
setsid nohup taskset -c 47 python3 "$BASE/bin/power_logger.py" --inband --no-fpga \
    > "$PLOG" 2> "$PERR" < /dev/null &
sleep 60
N=$(wc -l < "$PLOG")
if (( N < 40 )) || grep -qiE "error|traceback|denied" "$PERR"; then
    say "ERRORE: logger non attivo ($N righe in 60 s)"; cat "$PERR"; exit 1
fi
LPID=$(pgrep -u "$USER" -f power_logger.py | head -1)
say "logger ok: $N righe, PID $LPID"
{   echo "# a2 $STAMP  nodo $NODE  ripetizione della campagna A"
    echo "# governor $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor) (iniziale $GOV_INIZIO, ripristino con il profilo $PROF_FINE)"
    echo "# tuned $(PYTHONUNBUFFERED=1 $TUNED active 2>/dev/null | grep -m1 -i profile)"
    echo "# xrt $(xrt-smi --version 2>/dev/null | grep -m1 -i version | tr -s ' ')"
    echo "# kernel $(uname -r)"
    echo "# avvio $(uptime -s)"
    echo "# git $(git -C "$BASE" log --oneline -1 2>/dev/null)"
    echo "# log potenza $PLOG"
} > "$OUT/info.txt"
echo -e "finestra\tt0\tt1" > "$OUT/idle_windows.tsv"

idle () {
    local t0; t0=$(date +%s.%N)
    say "idle $1: $IDLE s"; sleep "$IDLE"
    echo -e "$1\t$t0\t$(date +%s.%N)" >> "$OUT/idle_windows.tsv"
}
pulizia () {
    pkill -u "$USER" -f "\.xclbin" 2>/dev/null
    pkill -u "$USER" -f multi_instance_worker 2>/dev/null
    pkill -u "$USER" -f "algo3_batch_omp|deflate_cpu|qp_dyn_quad" 2>/dev/null
    sleep 10
}
run () {   # run <tag> <alloc>
    say "=== $1  alloc $2"
    ( cd "$BASE" && python3 $RM --config "$CFG" --units "$UNITS" --alloc "$2" \
                     --fpga-devices 0 --run --tag "$1" --outdir "$OUT" ) > "$OUT/$1.out" 2>&1
    local rc=$?
    grep -E "DEVICE=|MAKESPAN|Traceback|ERR" "$OUT/$1.out" | head -5
    if (( rc != 0 )); then say "ERRORE: $1 terminata con codice $rc"; pulizia; fi
    sleep "$PAUSA"
}

idle iniziale
for r in $(seq 1 "$RIP"); do
    run "rho_$r"  "IM:0,DE:4,QP:30"
    run "viol_$r" "IM:4,DE:0,QP:30"
done
idle finale

say "runs.tsv: $(wc -l < "$OUT/runs.tsv") righe (attese $((2 * RIP)))"
cp "$PLOG" "$OUT/" && say "log di potenza copiato in $OUT"
kill "$LPID" 2>/dev/null && say "logger fermato"
say "=== FINE ==="
