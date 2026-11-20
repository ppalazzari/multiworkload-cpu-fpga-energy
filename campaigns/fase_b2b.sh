#!/bin/bash
# fase_b2b.sh — campagna B, regime a partizione statica (~9.5 h).
# Riferimenti a 29 core (r29_*) all'inizio e alla fine, sul nodo della campagna.
# CPU sui core 0-28, runtime FPGA sui core 29-47 (impronta di NB = 19 core),
# QP sulla CPU con 5 istanze (bin/workloads_b2pin.json).
# Modello con t_C ed E_C misurati a 29 core (riferimenti r29 della notte 1):
#   s_opt (28,30,0,0)  ottimo a partizione statica       prev. 2637 s, 2520 kJ  x3
#   s_unp (30,25,0,0)  ottimo senza pinning, qui         prev. 2917 s, 2758 kJ  x3
#   s_de  (26,30,2,0)  vicino con DE                      prev. 2711 s, 2580 kJ  x2
#   coppie con QP sulla CPU e pinning (campagna D, parte 1b, nuova configurazione):
#   pQP_NB, pQP_DE, pQP_IM: QP 5 unita' sulla CPU, 15/12/12 unita' sulla FPGA, x2
#
# Uso:
#   ./fase_b2b.sh --check
#   pagsh -c 'aklog && setsid nohup ~/fase_b2b.sh > /tmp/b2b_$(date +%m%d_%H%M).log 2>&1 < /dev/null &'

set -u
BASE=${BASE:-$HOME/energy_comparisons}
PAUSA=${PAUSA:-120}
IDLE=${IDLE:-300}
STAMP=$(date +%m%d_%H%M)
NODE=$(hostname -s)
OUT=$BASE/work/raw/b2b_${NODE}_$STAMP
PLOG=/tmp/b2b_power_$STAMP.log
PERR=/tmp/b2b_power_err_$STAMP.log
RM=bin/run_multi_pin.py
CFG=bin/workloads_qp8.json


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

CFG29=bin/workloads_b2pin.json
( cd "$BASE" && python3 - <<'EOF'
import json, os
if not os.path.exists("bin/workloads_b2pin.json"):
    c = json.load(open("bin/workloads_qp8.json"))
    a = c["qpdyn"]["cpu"]["args"]
    a[a.index("--core-bases") + 1] = "0,4,8,12,24"
    a[a.index("--main-cores") + 1] = "16,17,18,19,28"
    c["qpdyn"]["cpu"]["consts"]["instances"] = 5
    c["qpdyn"]["cpu"]["nota"] = "maschera CPU 0-28: 4 istanze sul socket 0 + 1 sul socket 1, thread principali 16-19 e 28"
    json.dump(c, open("bin/workloads_b2pin.json", "w"), indent=2, ensure_ascii=False)
    print("creato bin/workloads_b2pin.json")
EOF
)
mkdir -p "$OUT"
setsid nohup taskset -c 47 python3 "$BASE/bin/power_logger.py" --inband --no-fpga \
    > "$PLOG" 2> "$PERR" < /dev/null &
sleep 60
N=$(wc -l < "$PLOG")
if (( N < 40 )) || grep -qiE "error|traceback|denied" "$PERR"; then
    say "ERRORE: logger non attivo ($N righe in 60 s)"; cat "$PERR"; exit 1; fi
LPID=$(pgrep -u "$USER" -f power_logger.py | head -1)
say "logger ok: $N righe, PID $LPID"
{   echo "# b2b $STAMP  nodo $NODE  campagna B, partizione statica CPU 0-28 / FPGA 29-47"
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
run () {   # run <tag> <units> <alloc> [config] [cpu-cpus] [fpga-cpus]
    local cfg=${4:-$CFG} extra=()
    [[ -n ${5:-} ]] && extra=(--cpu-cpus "$5" --fpga-cpus "$6")
    say "=== $1  units $2  alloc $3  config $(basename $cfg) ${5:+cpu $5 fpga $6}"
    ( cd "$BASE" && python3 $RM --config "$cfg" --units "$2" --alloc "$3" --fpga-devices 0 \
                     "${extra[@]}" --run --tag "$1" --outdir "$OUT" ) > "$OUT/$1.out" 2>&1
    (( $? != 0 )) && say "ERRORE: $1"
    grep -E "MAKESPAN|Traceback" "$OUT/$1.out" | head -2
    sleep "$PAUSA"
}

idle iniziale
U="QP:30,NB:30,DE:30,IM:30"
S() { run "$1" "$2" "$3" "$CFG29" 0-28 29-47; }
riferimenti29 () {   # riferimenti a 29 core sul nodo della campagna, FPGA ferma
    for w in QP NB DE IM; do S "r29_${w}_$1" "$w:5" "$w:0"; done
}
riferimenti29 1
S s_opt_1 "$U" "QP:28,NB:30,DE:0,IM:0"
S s_unp_1 "$U" "QP:30,NB:25,DE:0,IM:0"
S s_de_1  "$U" "QP:26,NB:30,DE:2,IM:0"
S s_opt_2 "$U" "QP:28,NB:30,DE:0,IM:0"
S s_unp_2 "$U" "QP:30,NB:25,DE:0,IM:0"
idle intermedia
S s_de_2  "$U" "QP:26,NB:30,DE:2,IM:0"
S s_opt_3 "$U" "QP:28,NB:30,DE:0,IM:0"
S s_unp_3 "$U" "QP:30,NB:25,DE:0,IM:0"
for r in 1 2; do
    S "pQP_NB_$r" "QP:5,NB:15" "QP:0,NB:15"
    S "pQP_DE_$r" "QP:5,DE:12" "QP:0,DE:12"
    S "pQP_IM_$r" "QP:5,IM:12" "QP:0,IM:12"
done
riferimenti29 2
idle finale
cp "$PLOG" "$OUT/" && say "log di potenza copiato in $OUT"
kill "$LPID" 2>/dev/null && say "logger fermato"
say "=== FINE ==="
