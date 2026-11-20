#!/bin/bash
# fase_scala12.sh — scala delle priorita' completa, core condivisi: le 12 coppie
# "A30 + B21", l'ottimo (30,25,0,0) e le configurazioni pure, su entrambi i nodi N48.
# Ogni giro esegue, su ciascun nodo, le 12 coppie una volta (ordine opposto sui due
# nodi e ruotato al secondo giro), l'ottimo due volte e una configurazione pura
# (fpga1: tutto-CPU al giro 1 e tutto-FPGA al giro 2; fpga2 il contrario).
# Dopo il giro 1 ogni coppia ha una run per nodo; dopo il giro 2, due per nodo.
#
# Previsioni (modello con interferenza, P_idle 714.8 W, t_cfg 5.9 s), T in s, E in kJ:
#   QP30+NB21 2763 2679   NB30+QP21 2733 2657   DE30+QP21 3105 3022   IM30+QP21 3886 3641
#   QP30+DE21 3073 2969   NB30+DE21 3746 3449   DE30+NB21 3586 3364   IM30+NB21 4199 3863
#   QP30+IM21 3579 3374   NB30+IM21 4147 3778   DE30+IM21 3847 3662   IM30+DE21 4042 3820
#   ottimo (30,25,0,0) 2518 2458   tutto-FPGA 6357 4710   tutto-CPU 5013 4874
# Durata stimata: circa 15.5-16 h per giro e per nodo (ROUNDS=2 di default: circa 32 h;
# i dati del giro 1 sono completi dopo circa 16 h).
#
# Uso, su ciascuno dei due nodi (il set e' scelto dal nome: fpga1 -> A, fpga2 -> B):
#   ./fase_scala12.sh --check
#   pagsh -c 'aklog && setsid nohup ~/fase_scala12.sh > /tmp/s12_$(date +%m%d_%H%M).log 2>&1 < /dev/null &'
# Variabili: ROUNDS (giri, default 2), PAUSA, IDLE, SET=A|B, FAN_MAX (W, default 250).
# Ventole: all'avvio la potenza delle ventole (sensore BMC "Sys Fan Pwr") deve essere
# <= FAN_MAX (velocita' fissa 11000 RPM: circa 190 W); durante la campagna un registratore
# scrive ogni 60 s in ventole.tsv: potenza delle ventole, giri min e max, temperatura
# dell'aria in ingresso; la potenza delle ventole e' riportata anche all'avvio di ogni run.

set -u
BASE=${BASE:-$HOME/energy_comparisons}
PAUSA=${PAUSA:-120}
IDLE=${IDLE:-300}
ROUNDS=${ROUNDS:-2}
STAMP=$(date +%m%d_%H%M)
NODE=$(hostname -s)
case ${SET:-$NODE} in
    A|*fpga1*) SET=A ;;
    B|*fpga2*) SET=B ;;
    *) echo "set non riconosciuto: usare SET=A o SET=B"; exit 1 ;;
esac
OUT=$BASE/work/raw/s12${SET}_${NODE}_$STAMP
PLOG=/tmp/s12_power_$STAMP.log
PERR=/tmp/s12_power_err_$STAMP.log
RM=bin/run_multi_pin.py
CFG=bin/workloads_qp8.json

# Governor: profilo tuned "hpc-compute" (performance) all'inizio, "cresco8" alla fine,
# anche in caso di errore o interruzione (trap); SETTLE: attesa dopo il cambio.
TUNED=${TUNED:-/usr/sbin/tuned-adm}
PROF_MISURA=${PROF_MISURA:-hpc-compute}
PROF_FINE=${PROF_FINE:-cresco8}
SETTLE=${SETTLE:-600}
FAN_MAX=${FAN_MAX:-250}
ventole_w () { sudo -n ipmitool sdr 2>/dev/null | awk -F'|' '/Sys Fan Pwr/ {gsub(/[^0-9]/,"",$2); print $2; exit}'; }
ventole_riga () {   # epoch, W ventole, RPM min, RPM max, aria in ingresso (C)
    local sdr; sdr=$(sudo -n ipmitool sdr 2>/dev/null)
    echo "$sdr" | awk -F'|' -v t="$(date +%s)" '
        /Sys Fan Pwr/            {gsub(/[^0-9]/,"",$2); w=$2}
        /Fan .*Tach/             {gsub(/[^0-9]/,"",$2); r=$2+0; if (mn==""||r<mn) mn=r; if (r>mx) mx=r}
        /Ambient Temp|Inlet Temp/ {gsub(/[^0-9]/,"",$2); if (a=="") a=$2}
        END {printf "%s\t%s\t%s\t%s\t%s\n", t, w, mn, mx, a}'
}
say () { echo "[$(date +%H:%M:%S)] $*"; }
check () {
    local ok=1 gov
    gov=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor)
    say "nodo: $NODE   set: $SET   governor: $gov   XRT: $(xrt-smi --version 2>/dev/null | grep -m1 -i version | tr -s ' ')"
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
    local fw; fw=$(ventole_w)
    if [[ -z $fw ]]; then say "ATTENZIONE: sensore Sys Fan Pwr non leggibile"
    elif (( fw > FAN_MAX )); then say "ERRORE: ventole a $fw W (> $FAN_MAX W): velocita' non fissa?"; ok=0
    else say "ventole: $fw W (limite $FAN_MAX W)"; fi
    return $(( ok == 1 ? 0 : 1 ))
}

U="QP:30,NB:30,DE:30,IM:30"
OPT="QP:30,NB:25,DE:0,IM:0"
ALLF="QP:30,NB:30,DE:30,IM:30"
ALLC="QP:0,NB:0,DE:0,IM:0"
# le 12 coppie, ordinate per rho medio decrescente
PAIRS=(nb30qp21:QP:21,NB:30,DE:0,IM:0  qp30nb21:QP:30,NB:21,DE:0,IM:0
       nb30de21:QP:0,NB:30,DE:21,IM:0  qp30de21:QP:30,NB:0,DE:21,IM:0
       de30nb21:QP:0,NB:21,DE:30,IM:0  de30qp21:QP:21,NB:0,DE:30,IM:0
       nb30im21:QP:0,NB:30,DE:0,IM:21  qp30im21:QP:30,NB:0,DE:0,IM:21
       im30nb21:QP:0,NB:21,DE:0,IM:30  im30qp21:QP:21,NB:0,DE:0,IM:30
       de30im21:QP:0,NB:0,DE:30,IM:21  im30de21:QP:0,NB:0,DE:21,IM:30)
# sequenza: <tag> <alloc> oppure "IDLE <nome>"
sequenza () {
    local r i k n=${#PAIRS[@]} p ord=()
    for (( r = 1; r <= ROUNDS; r++ )); do
        ord=()
        for (( i = 0; i < n; i++ )); do
            k=$(( (i + (r - 1) * 6) % n ))
            [[ $SET == B ]] && k=$(( n - 1 - k ))
            ord+=("${PAIRS[$k]}")
        done
        echo "opt_r${r}a $OPT"
        for (( i = 0; i < n; i++ )); do
            p=${ord[$i]}
            echo "${p%%:*}_r$r ${p#*:}"
            if (( i == 5 )); then
                echo "IDLE meta_r$r"
                if [[ ($SET == A && $r -eq 1) || ($SET == B && $r -eq 2) ]]; then
                    echo "allcpu_r$r $ALLC"
                else
                    echo "allfpga_r$r $ALLF"
                fi
                echo "opt_r${r}b $OPT"
            fi
        done
        echo "IDLE fine_r$r"
    done
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
    [[ -n ${VPID:-} ]] && kill "$VPID" 2>/dev/null
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
say "logger ok: $N righe, PID $LPID"
echo -e "epoch\tventole_W\trpm_min\trpm_max\taria_C" > "$OUT/ventole.tsv"
( while true; do ventole_riga >> "$OUT/ventole.tsv"; sleep 60; done ) < /dev/null &
VPID=$!
say "registratore ventole: PID $VPID -> $OUT/ventole.tsv"
{   echo "# s12$SET $STAMP  nodo $NODE  scala delle priorita' completa (12 coppie), core condivisi, $ROUNDS giri"
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
run () {   # run <tag> <alloc>: core condivisi, nessun pinning, una scheda
    say "=== $1  alloc $2  (ventole $(ventole_w) W)"
    ( cd "$BASE" && python3 $RM --config "$CFG" --units "$U" --alloc "$2" --fpga-devices 0 \
                     --run --tag "$1" --outdir "$OUT" ) > "$OUT/$1.out" 2>&1 < /dev/null
    (( $? != 0 )) && say "ERRORE: $1"
    grep -E "MAKESPAN|Traceback" "$OUT/$1.out" | head -2
    sleep "$PAUSA"
}

idle iniziale
while read -r tag alloc; do
    if [[ $tag == IDLE ]]; then idle "$alloc"; else run "$tag" "$alloc"; fi
done < <(sequenza)

R=$(wc -l < "$OUT/runs.tsv" 2>/dev/null || echo 0)
say "runs.tsv: $R run (attese $(( 15 * ROUNDS )))"
cp "$PLOG" "$OUT/" && say "log di potenza copiato in $OUT"
kill "$LPID" 2>/dev/null && say "logger fermato"
kill "$VPID" 2>/dev/null && say "registratore ventole fermato"
awk -F'\t' 'NR > 1 && $2 != "" {n++; if (mn == "" || $2 < mn) mn = $2; if ($2 > mx) mx = $2} END {printf "ventole durante la campagna: %d letture, %s-%s W\n", n, mn, mx}' "$OUT/ventole.tsv"
say "analisi: python3 $BASE/bin/analyze_power.py $OUT/$(basename "$PLOG") $OUT/runs.tsv --csv $OUT/risultati.csv"
say "=== FINE ==="
