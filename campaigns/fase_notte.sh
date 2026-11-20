#!/bin/bash
# fase_notte.sh — campagna notturna su cresco8-fpga2 (governor performance).
#
# Parte 1 (~2 h): caratterizzazione con pinning
#   a. tempi CPU a FPGA ferma: QP, IM, DE, NB su 29 core; NB su 46 e 44 core
#   b. coppie in co-esecuzione con partizione dei core:
#      NB su FPGA (core 29-47) con QP, DE, IM su CPU (core 0-28)
#      QP, IM su FPGA (core 46-47) e DE su FPGA (core 44-47) con NB su CPU
# Parte 2 (~6.5 h): quattro workload con partizione statica (CPU 0-28,
#   FPGA 29-47), QP30 + NBx con x = 25, 27, 29, 30, alternati.
#   Previsione del modello statico (tempi a 29 core misurati il 1/10 con
#   schedutil, P_idle 730 W, da ricalcolare con la parte 1):
#       x = 25: ~2830 kJ   27: ~2670 kJ   29: ~2550 kJ (ottimo)   30: ~2570 kJ
#   Confronto con la campagna C (stesso nodo, senza pinning): NB25 2455 kJ.
#
# Uso:
#   ./fase_notte.sh --check
#   pagsh -c 'aklog && setsid nohup ~/fase_notte.sh > /tmp/notte_$(date +%m%d_%H%M).log 2>&1 < /dev/null &'

set -u
BASE=${BASE:-$HOME/energy_comparisons}
PAUSA=${PAUSA:-180}
IDLE=${IDLE:-300}
STAMP=$(date +%m%d_%H%M)
OUT=$BASE/work/raw/notte_$STAMP
PLOG=/tmp/notte_power_$STAMP.log
PERR=/tmp/notte_power_err_$STAMP.log
RM=bin/run_multi_pin.py
CFG=bin/workloads_pin.json
U4="IM:30,DE:30,QP:30,NB:30"

say () { echo "[$(date +%H:%M:%S)] $*"; }

check () {
    local ok=1
    say "nodo: $(hostname)"
    [[ $(hostname) == cresco8-fpga2* ]] || say "NOTA: progettata per cresco8-fpga2"
    local gov; gov=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null)
    say "governor: $gov"
    [[ $gov == performance ]] || { say "ERRORE: serve il governor performance"; ok=0; }
    for f in $RM $CFG bin/multi_instance_worker_pin.py bin/power_logger.py; do
        [[ -f $BASE/$f ]] || { say "ERRORE: manca $f"; ok=0; }
    done
    [[ -x $BASE/bin/multi_instance_worker_pin.py ]] || { say "ERRORE: multi_instance_worker_pin.py non eseguibile"; ok=0; }
    if pgrep -u "$USER" -f "run_multi|power_logger.py|\.xclbin" > /dev/null; then
        say "ERRORE: processi gia' attivi:"; pgrep -u "$USER" -af "run_multi|power_logger.py|\.xclbin"; ok=0
    fi
    say "token AFS:"; tokens 2>/dev/null | grep -i "tokens for" || say "ATTENZIONE: nessun token"
    return $(( ok == 1 ? 0 : 1 ))
}

if [[ ${1:-} == --check ]]; then check; exit $?; fi
check || { say "controlli falliti, campagna non avviata"; exit 1; }

# ---------------------------------------------------------------- logger (core 47, gruppo FPGA)
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
{   echo "# notte $STAMP  nodo $(hostname)"
    echo "# governor $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor)"
    echo "# git $(git -C "$BASE" log --oneline -1)"
    echo "# log potenza $PLOG"
} > "$OUT/info.txt"
echo -e "finestra\tt0\tt1" > "$OUT/idle_windows.tsv"

idle () {
    local t0; t0=$(date +%s.%N)
    say "idle $1: $IDLE s"; sleep "$IDLE"
    echo -e "$1\t$t0\t$(date +%s.%N)" >> "$OUT/idle_windows.tsv"
}

pulizia () {   # solo dopo una run fallita: processi orfani
    pkill -u "$USER" -f "\.xclbin"            2>/dev/null
    pkill -u "$USER" -f multi_instance_worker 2>/dev/null
    pkill -u "$USER" -f "algo3_batch_omp|nbody_cpu|deflate_cpu|qp_dyn_quad" 2>/dev/null
    sleep 10
}

run () {   # run <tag> <units> <alloc> <cpu-cpus> [fpga-cpus]
    local tag=$1 units=$2 alloc=$3 cpu=$4 fpga=${5:-}
    local args=(--config "$CFG" --units "$units" --alloc "$alloc" --cpu-cpus "$cpu")
    [[ -n $fpga ]] && args+=(--fpga-cpus "$fpga")
    say "=== $tag  units $units  alloc $alloc  cpu $cpu  fpga ${fpga:--}"
    ( cd "$BASE" && python3 $RM "${args[@]}" --run --tag "$tag" --outdir "$OUT" ) \
        > "$OUT/$tag.out" 2>&1
    local rc=$?
    grep -E "MAKESPAN|maschera|istanze|Traceback|ERR" "$OUT/$tag.out" | head -5
    if (( rc != 0 )); then say "ERRORE: $tag terminata con codice $rc"; pulizia; fi
    sleep "$PAUSA"
}

# ---------------------------------------------------------------- campagna
idle iniziale

say "### parte 1a: tempi CPU a FPGA ferma"
run ref29_QP "QP:4"  "QP:0"  0-28
run ref29_IM "IM:4"  "IM:0"  0-28
run ref29_DE "DE:4"  "DE:0"  0-28
run ref29_NB "NB:4"  "NB:0"  0-28
run ref46_NB "NB:4"  "NB:0"  0-45
run ref44_NB "NB:4"  "NB:0"  0-43

say "### parte 1b: coppie con partizione"
run nbF_qpC "NB:12,QP:5"  "NB:12,QP:0" 0-28 29-47
run nbF_deC "NB:12,DE:10" "NB:12,DE:0" 0-28 29-47
run nbF_imC "NB:6,IM:10"  "NB:6,IM:0"  0-28 29-47
run qpF_nbC "QP:6,NB:5"   "QP:6,NB:0"  0-45 46-47
run imF_nbC "IM:5,NB:5"   "IM:5,NB:0"  0-45 46-47
run deF_nbC "DE:5,NB:5"   "DE:5,NB:0"  0-43 44-47

say "### parte 2: quattro workload, partizione statica 0-28 / 29-47"
for x in 29_1 27_1 30_1 29_2 25_1 27_2 30_2 29_3; do
    run "s$x" "$U4" "IM:0,DE:0,QP:30,NB:${x%_*}" 0-28 29-47
done

idle finale

R=$(wc -l < "$OUT/runs.tsv")
say "runs.tsv: $R righe (attese 20)"
cp "$PLOG" "$OUT/" && say "log di potenza copiato in $OUT"
kill "$LPID" 2>/dev/null && say "logger fermato"
say "=== FINE ==="
