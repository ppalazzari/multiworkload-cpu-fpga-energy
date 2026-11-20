#!/bin/bash
# fase_coppie.sh — matrice di interferenza completa, senza pinning (N48, una U55C).
#
# Per ogni coppia (u sulla CPU, v sulla FPGA), 16 coppie compresa la diagonale:
# la CPU elabora n_u unita' di u mentre la FPGA elabora abbastanza unita' di v
# da restare occupata per tutta la fase CPU (1.5 volte la durata attesa), cosi'
# il rallentamento si legge direttamente: t_C(u|v) / t_C(u isolato), senza fit.
# Riferimenti: ogni workload sulla CPU con la FPGA ferma, all'inizio e alla fine.
#
# Ripetizioni: REPS (default "1 2 3"). Durata totale ~14 h: dividere in due notti,
#   notte 1: REPS="1 2" ./fase_coppie.sh   (~9.5 h)
#   notte 2: REPS="3"   ./fase_coppie.sh   (~5 h)
#
# Uso:
#   ./fase_coppie.sh --check
#   pagsh -c 'aklog && REPS="1 2" setsid nohup ~/fase_coppie.sh > /tmp/coppie_$(date +%m%d_%H%M).log 2>&1 < /dev/null &'

set -u
BASE=${BASE:-$HOME/energy_comparisons}
PAUSA=${PAUSA:-120}
IDLE=${IDLE:-300}
REPS=${REPS:-"1 2 3"}
STAMP=$(date +%m%d_%H%M)
NODE=$(hostname -s)
OUT=$BASE/work/raw/coppie_${NODE}_$STAMP
PLOG=/tmp/coppie_power_$STAMP.log
PERR=/tmp/coppie_power_err_$STAMP.log
RM=bin/run_multi_pin.py
CFG=bin/workloads_pin.json

# unita' CPU (n_u) e FPGA (n_v) per coppia "u v n_u n_v" (calcolate con i rallentamenti
# della campagna B, 3 dove ignoti, margine 1.5; QP|NB con una sola unita' di QP)
COPPIE="QP QP 5 10
QP NB 1 61
QP DE 5 8
QP IM 5 23
NB QP 5 13
NB NB 5 11
NB DE 5 9
NB IM 5 10
DE QP 8 10
DE NB 8 17
DE DE 8 8
DE IM 8 8
IM QP 16 30
IM NB 16 16
IM DE 16 9
IM IM 16 9"
REF="QP 5
NB 5
DE 8
IM 16"

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
{   echo "# coppie $STAMP  nodo $NODE  ripetizioni $REPS"
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
