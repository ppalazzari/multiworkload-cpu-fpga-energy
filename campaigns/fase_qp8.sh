#!/bin/bash
# fase_qp8.sh — QP sulla CPU con la configurazione corretta (8 istanze 4+4,
# thread principali vincolati ai core 16-19 e 40-43: bin/workloads_qp8.json).
#
#   carqp_r   QP isolato sulla CPU, 10 unita' (x3): t_C^QP ed E_C^QP per la Tabella III
#   ref_QP_a/b, QP_<v>_r   riga QP della matrice delle coppie (x3), come fase_coppie.sh
# Durata ~5 h.
#
# Uso:
#   ./fase_qp8.sh --check
#   pagsh -c 'aklog && setsid nohup ~/fase_qp8.sh > /tmp/qp8_$(date +%m%d_%H%M).log 2>&1 < /dev/null &'

set -u
BASE=${BASE:-$HOME/energy_comparisons}
PAUSA=${PAUSA:-120}
IDLE=${IDLE:-300}
REPS=${REPS:-"1 2 3"}
STAMP=$(date +%m%d_%H%M)
NODE=$(hostname -s)
OUT=$BASE/work/raw/qp8_${NODE}_$STAMP
PLOG=/tmp/qp8_power_$STAMP.log
PERR=/tmp/qp8_power_err_$STAMP.log
RM=bin/run_multi_pin.py
CFG=bin/workloads_qp8.json

# unita' CPU (n_u) e FPGA (n_v) per coppia "u v n_u n_v" (calcolate con i rallentamenti
# della campagna B, 3 dove ignoti, margine 1.5; QP|NB con una sola unita' di QP)
COPPIE="QP QP 5 10
QP NB 5 61
QP DE 5 8
QP IM 5 10"
REF="QP 5"

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
    grep -q -- "--main-cores" "$BASE/$CFG" 2>/dev/null || { say "ERRORE: $CFG mancante o senza --main-cores"; ok=0; }
    if pgrep -u "$USER" -f "run_multi|power_logger.py|\.xclbin" > /dev/null; then
        say "ERRORE: processi gia' attivi"; ok=0; fi
    tokens 2>/dev/null | grep -i "tokens for" || say "ATTENZIONE: nessun token"
    return $(( ok == 1 ? 0 : 1 ))
}
if [[ ${1:-} == --check ]]; then check; exit $?; fi
check || { say "controlli falliti"; exit 1; }

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
setsid nohup taskset -c 47 python3 "$BASE/bin/power_logger.py" --inband --no-fpga \
    > "$PLOG" 2> "$PERR" < /dev/null &
sleep 60
N=$(wc -l < "$PLOG")
if (( N < 40 )) || grep -qiE "error|traceback|denied" "$PERR"; then
    say "ERRORE: logger non attivo ($N righe in 60 s)"; cat "$PERR"; exit 1; fi
LPID=$(pgrep -u "$USER" -f power_logger.py | head -1)
say "logger ok: $N righe, PID $LPID   ripetizioni: $REPS"
{   echo "# qp8 $STAMP  nodo $NODE  QP CPU 8 istanze 4+4, thread principali vincolati"
    echo "# governor $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor) (iniziale $GOV_INIZIO, ripristino con il profilo $PROF_FINE)"
    echo "# tuned $(PYTHONUNBUFFERED=1 $TUNED active 2>/dev/null | grep -m1 -i profile)"
    echo "# xrt $(xrt-smi --version 2>/dev/null | grep -m1 -i version | tr -s ' ')"
    echo "# kernel $(uname -r)"
    echo "# avvio $(uptime -s)"
    echo "# log potenza $PLOG"
} > "$OUT/info.txt"
echo -e "finestra\tt0\tt1" > "$OUT/idle_windows.tsv"
idle () { local t0; t0=$(date +%s.%N); say "idle $1: $IDLE s"; sleep "$IDLE"
          echo -e "$1\t$t0\t$(date +%s.%N)" >> "$OUT/idle_windows.tsv"; }
run () {   # run <tag> <units> <alloc>
    say "=== $1  units $2  alloc $3"
    ( cd "$BASE" && python3 $RM --config "$CFG" --units "$2" --alloc "$3" --fpga-devices 0 \
                     --run --tag "$1" --outdir "$OUT" ) > "$OUT/$1.out" 2>&1
    (( $? != 0 )) && say "ERRORE: $1"
    grep -E "MAKESPAN|Traceback" "$OUT/$1.out" | head -2
    sleep "$PAUSA"
}
riferimenti () {   # workload sulla CPU, FPGA ferma
    while read -r u n; do run "ref_${u}_$1" "$u:$n" "$u:0"; done <<< "$REF"
}

idle iniziale
for r in 1 2 3; do run "carqp_$r" "QP:10" "QP:0"; done
riferimenti a
for r in $REPS; do
    while read -r u v nu nv; do
        if [[ $u == "$v" ]]; then run "${u}_${v}_$r" "$u:$((nu + nv))" "$u:$nv"
        else run "${u}_${v}_$r" "$u:$nu,$v:$nv" "$u:0,$v:$nv"; fi
    done <<< "$COPPIE"
done
riferimenti b
idle finale
cp "$PLOG" "$OUT/" && say "log di potenza copiato in $OUT"
kill "$LPID" 2>/dev/null && say "logger fermato"
say "=== FINE ==="
