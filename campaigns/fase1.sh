#!/bin/bash
# fase1.sh — Campagna C1, fase 1, su cresco8-fpga1 (1 x U55C, 0000:cc:00.1).
#
# Verifica la previsione del modello con interferenza (matrice di rallentamento
# della campagna quattro_0918): con la configurazione CPU della campagna B
# (NB e IM a 48 thread) l'energia minima non e' a QP30+NB21 ma verso NB25.
#
#   NB su FPGA   T previsto   E prevista   (modello con interferenza, P_idle 712 W)
#        21        2762 s      2669.6 kJ   ottimo dello zaino senza interferenza
#        23        2627 s      2549.2 kJ
#        25        2491 s      2428.7 kJ   ottimo previsto
#        27        2569 s      2460.1 kJ   FPGA-bound
#
# Struttura: finestra di idle iniziale (300 s), 5 x NB21 e 5 x NB25 alternati
# con ordine invertito a ogni giro, NB23 e NB27 una volta, idle finale (300 s).
# Durata stimata: circa 9.5 ore.
#
# Uso:
#   ./fase1.sh --check      solo controlli preliminari, non lancia nulla
#   setsid nohup ./fase1.sh > ~/fase1_$(date +%m%d_%H%M).log 2>&1 < /dev/null & disown
#
# Variabili (opzionali): BASE (copia locale del framework, default ~/energy_comparisons),
# PAUSA (s fra le run, default 180), IDLE (s di idle iniziale e finale, default 300),
# FORCE=1 per partire anche se il governor non e' 'performance'.

set -u
BASE=${BASE:-$HOME/energy_comparisons}
PAUSA=${PAUSA:-180}
IDLE=${IDLE:-300}
FORCE=${FORCE:-0}
STAMP=$(date +%m%d_%H%M)
OUT=$BASE/work/raw/fase1_$STAMP
PLOG=/tmp/fase1_power_$STAMP.log          # il logger non scrive mai su AFS
PERR=/tmp/fase1_power_err_$STAMP.log
U="IM:30,DE:30,QP:30,NB:30"

say () { echo "[$(date +%H:%M:%S)] $*"; }

# ---------------------------------------------------------------- controlli
check () {
    local ok=1
    say "nodo: $(hostname)"
    [[ $(hostname) == cresco8-fpga1* ]] || say "NOTA: la campagna B e' stata fatta su cresco8-fpga1; qui si verifica anche la trasferibilita' della matrice"

    local gov; gov=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null)
    say "governor: $gov"
    if [[ $gov != performance ]]; then
        say "ERRORE: la campagna B usava 'performance' (idle 718 W contro 597 W con schedutil)."
        say "        sudo cpupower frequency-set -g performance   oppure FORCE=1 per ignorare"
        [[ $FORCE == 1 ]] || ok=0
    fi

    say "schede FPGA:"; xrt-smi examine 2>/dev/null | grep -A5 "Device(s) Present"
    xrt-smi examine 2>/dev/null | grep -q "cc:00.1" || { say "ERRORE: 0000:cc:00.1 non presente"; ok=0; }

    if pgrep -u "$USER" -f power_logger.py > /dev/null; then
        say "ERRORE: c'e' gia' un power_logger attivo:"; pgrep -u "$USER" -af power_logger.py; ok=0
    fi
    if pgrep -u "$USER" -f run_multi.py > /dev/null; then
        say "ERRORE: c'e' gia' un run_multi.py attivo"; ok=0
    fi

    say "token AFS:"; tokens 2>/dev/null | grep -i "tokens for" || say "ATTENZIONE: nessun token AFS visibile"
    [[ $BASE == /afs/* || $BASE == $HOME* ]] && \
        say "NOTA: BASE e' su AFS; la campagna muore se il token scade o la sessione si chiude."

    say "modifiche a workloads.json e run_multi.py dopo la campagna B (18/9):"
    git -C "$BASE" log --oneline --since=2026-09-18 -- bin/workloads.json bin/run_multi.py | head -20
    say "  -> se NB o IM sono passati a 47 thread, la fase 1 NON riproduce la campagna B."

    say "previsione del modello senza interferenza per le quattro ripartizioni:"
    for nb in 21 23 25 27; do
        ( cd "$BASE" && echo "--- NB:$nb"; python3 bin/run_multi.py --units "$U" --alloc "IM:0,DE:0,QP:30,NB:$nb" 2>&1 | tail -6 ) || true
    done
    return $(( ok == 1 ? 0 : 1 ))
}

if [[ ${1:-} == --check ]]; then check; exit $?; fi
check || { say "controlli falliti, campagna non avviata"; exit 1; }

# ---------------------------------------------------------------- logger
mkdir -p "$OUT"
say "avvio logger -> $PLOG"
setsid nohup taskset -c 46 python3 "$BASE/bin/power_logger.py" --inband --no-fpga \
    > "$PLOG" 2> "$PERR" < /dev/null &
sleep 60
N=$(wc -l < "$PLOG")
if (( N < 40 )) || grep -qiE "error|traceback|denied" "$PERR"; then
    say "ERRORE: logger non attivo ($N righe in 60 s)"; cat "$PERR"; exit 1
fi
LPID=$(pgrep -u "$USER" -f power_logger.py | head -1)
say "logger ok: $N righe, PID $LPID"

{   echo "# fase1 $STAMP  nodo $(hostname)"
    echo "# governor $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor)"
    echo "# git $(git -C "$BASE" log --oneline -1)"
    echo "# log potenza $PLOG"
} > "$OUT/info.txt"
echo -e "finestra\tt0\tt1" > "$OUT/idle_windows.tsv"

idle () {   # idle <nome>
    local t0; t0=$(date +%s.%N)
    say "idle $1: $IDLE s"; sleep "$IDLE"
    echo -e "$1\t$t0\t$(date +%s.%N)" >> "$OUT/idle_windows.tsv"
}
run () {    # run <tag> <unita' NB su FPGA>
    say "=== $1  NB:$2 ==="
    ( cd "$BASE" && python3 bin/run_multi.py --units "$U" --alloc "IM:0,DE:0,QP:30,NB:$2" \
                     --run --tag "$1" --outdir "$OUT" ) | grep -E "MAKESPAN|ERR|Traceback" || true
    sleep "$PAUSA"
}

# ---------------------------------------------------------------- campagna
idle iniziale
for i in 1 2 3 4 5; do
    if (( i % 2 )); then run "nb21_$i" 21; run "nb25_$i" 25
    else                 run "nb25_$i" 25; run "nb21_$i" 21; fi
    (( i == 2 )) && run nb23 23
    (( i == 4 )) && run nb27 27
done
idle finale

# ---------------------------------------------------------------- chiusura
R=$(( $(wc -l < "$OUT/runs.tsv") ))
say "runs.tsv: $R righe (attese 12)"
cp "$PLOG" "$OUT/" && say "log di potenza copiato in $OUT"
if (( R >= 12 )); then
    kill "$LPID" 2>/dev/null && say "logger fermato"
else
    say "ATTENZIONE: campagna incompleta, logger lasciato attivo (PID $LPID)"
fi
say "analisi: python3 $BASE/bin/analyze_power.py $OUT/$(basename "$PLOG") $OUT/runs.tsv --csv $OUT/risultati.csv"
say "=== FINE ==="
