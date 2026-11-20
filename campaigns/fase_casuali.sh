#!/bin/bash
# fase_casuali.sh — validazione del modello su allocazioni casuali (N_w = 10).
# REGIME=shared  (core condivisi, nessun pinning)          ~13 h, consigliato su cresco8-fpga2
# REGIME=static  (CPU 0-28, runtime FPGA 29-47, QP 5 ist.) ~15 h, consigliato su cresco8-fpga1
# Allocazioni: bin/casuali_${REGIME}.tsv (30 punti da un Latin hypercube, piu' l'ottimo
# del regime), con le previsioni del modello. Ordine: opt_1, c01..c15, opt_2, idle
# intermedia, c16..c30, opt_3.
# Analisi: python3 bin/analisi_casuali.py <cartella> bin/casuali_${REGIME}.tsv
#
# Uso:
#   REGIME=shared ./fase_casuali.sh --check
#   pagsh -c 'aklog && REGIME=shared setsid nohup ~/fase_casuali.sh > /tmp/cas_$(date +%m%d_%H%M).log 2>&1 < /dev/null &'

set -u
REGIME=${REGIME:?imposta REGIME=shared oppure REGIME=static}
BASE=${BASE:-$HOME/energy_comparisons}
PAUSA=${PAUSA:-90}
IDLE=${IDLE:-300}
STAMP=$(date +%m%d_%H%M)
NODE=$(hostname -s)
OUT=$BASE/work/raw/cas_${REGIME}_${NODE}_$STAMP
PLOG=/tmp/cas_power_$STAMP.log
PERR=/tmp/cas_power_err_$STAMP.log
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
    [[ -f $BASE/bin/casuali_${REGIME}.tsv ]] || { say "ERRORE: manca $BASE/bin/casuali_${REGIME}.tsv"; ok=0; }
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
{   echo "# cas $STAMP  nodo $NODE  allocazioni casuali, regime $REGIME, N_w=10"
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

LISTA=$BASE/bin/casuali_${REGIME}.tsv
[[ -f $LISTA ]] || { say "ERRORE: manca $LISTA"; exit 1; }
cp "$LISTA" "$OUT/"
idle iniziale
U="QP:10,NB:10,DE:10,IM:10"
esegui () {   # esegui <tag> <alloc>
    if [[ $REGIME == static ]]; then run "$1" "$U" "$2" "$CFG29" 0-28 29-47
    else run "$1" "$U" "$2"; fi
}
OPT=$(awk -F'\t' '$1=="opt"{print $2}' "$LISTA")
mapfile -t PUNTI < <(awk -F'\t' '$1 ~ /^c[0-9]/{print $1"\t"$2}' "$LISTA")
esegui opt_1 "$OPT"
for k in $(seq 0 14);  do IFS=$'\t' read -r t a <<< "${PUNTI[$k]}"; esegui "$t" "$a"; done
esegui opt_2 "$OPT"
idle intermedia
for k in $(seq 15 29); do IFS=$'\t' read -r t a <<< "${PUNTI[$k]}"; esegui "$t" "$a"; done
esegui opt_3 "$OPT"
idle finale
cp "$PLOG" "$OUT/" && say "log di potenza copiato in $OUT"
kill "$LPID" 2>/dev/null && say "logger fermato"
say "=== FINE ==="
