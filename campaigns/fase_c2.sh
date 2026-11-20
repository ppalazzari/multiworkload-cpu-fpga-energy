#!/bin/bash
# fase_c2.sh — campagna C2: quattro workload con due FPGA (m = 2).
# Stesso script su cresco8-fpga2 (performance) e cresco8-fpga1 (schedutil).
#
# Parte 0: verifica che le due sequenze usino davvero le due schede
#          (NB 4 unita' divise 2+2; total execs deve crescere su entrambe).
# Parte 1 (~4.2 h): senza pinning, (QP, NB, DE, IM) = (30, 30, x, 0),
#          x = 14 (x3), 6 (x2), 10, 18. Previsioni con P_idle 728.6 W:
#            impronta, partizione dinamica: ottimo x = 14, ~1798 kJ; x = 6 ~2037 kJ
#            senza impronta:                ottimo x = 4-6, ~1684 kJ
# Parte 2 (~3.1 h): partizione statica, CPU 0-9, FPGA 10-47,
#          (30, 30, 30, y), y = 4 (x2), 0, 8. Previsione: ottimo y = 4, ~2091 kJ.
#
# Uso:
#   ./fase_c2.sh --check
#   pagsh -c 'aklog && setsid nohup ~/fase_c2.sh > /tmp/c2_$(date +%m%d_%H%M).log 2>&1 < /dev/null &'

set -u
BASE=${BASE:-$HOME/energy_comparisons}
PAUSA=${PAUSA:-180}
IDLE=${IDLE:-300}
STAMP=$(date +%m%d_%H%M)
NODE=$(hostname -s)
OUT=$BASE/work/raw/c2_${NODE}_$STAMP
PLOG=/tmp/c2_power_$STAMP.log
PERR=/tmp/c2_power_err_$STAMP.log
RM=bin/run_multi_pin.py
CFG=bin/workloads_pin.json
BDFS="0000:33:00.1 0000:cc:00.1"

say () { echo "[$(date +%H:%M:%S)] $*"; }

check () {
    local ok=1
    say "nodo: $NODE   governor: $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor)"
    grep -q -- "--fpga-devices" "$BASE/$RM" || { say "ERRORE: $RM senza --fpga-devices"; ok=0; }
    python3 - "$BASE/$CFG" <<'EOF' || ok=0
import json, os, sys
c = json.load(open(sys.argv[1]))
bad = [w for w in ("nbody", "deflate", "algo3", "qpdyn") if not c[w]["fpga"].get("device_env")]
miss = [c[w]["fpga"]["bin"] for w in ("nbody", "deflate", "algo3") if not os.path.isfile(c[w]["fpga"]["bin"])]
if bad or miss:
    print("ERRORE: device_env mancante per", bad, "o host mancanti", miss); sys.exit(1)
EOF
    for b in $BDFS; do
        [[ -f /sys/bus/pci/devices/$b/kdsstat ]] || { say "ERRORE: scheda $b non visibile"; ok=0; }
    done
    if pgrep -u "$USER" -f "run_multi|power_logger.py|\.xclbin" > /dev/null; then
        say "ERRORE: processi gia' attivi:"; pgrep -u "$USER" -af "run_multi|power_logger.py|\.xclbin"; ok=0
    fi
    tokens 2>/dev/null | grep -i "tokens for" || say "ATTENZIONE: nessun token"
    return $(( ok == 1 ? 0 : 1 ))
}
if [[ ${1:-} == --check ]]; then check; exit $?; fi
check || { say "controlli falliti, campagna non avviata"; exit 1; }

execs () {   # total execs delle due schede, separati da tab
    for b in $BDFS; do
        grep -m1 "total execs" /sys/bus/pci/devices/$b/kdsstat | awk '{print $NF}'
    done | paste -sd'\t'
}

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
{   echo "# c2 $STAMP  nodo $NODE"
    echo "# governor $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor)"
    echo "# git $(git -C "$BASE" log --oneline -1)"
    echo "# log potenza $PLOG"
} > "$OUT/info.txt"
echo -e "finestra\tt0\tt1" > "$OUT/idle_windows.tsv"
echo -e "tag\texecs_33\texecs_cc" > "$OUT/kds.tsv"

idle () {
    local t0; t0=$(date +%s.%N)
    say "idle $1: $IDLE s"; sleep "$IDLE"
    echo -e "$1\t$t0\t$(date +%s.%N)" >> "$OUT/idle_windows.tsv"
}
pulizia () {
    pkill -u "$USER" -f "\.xclbin" 2>/dev/null
    pkill -u "$USER" -f multi_instance_worker 2>/dev/null
    pkill -u "$USER" -f "algo3_batch_omp|nbody_cpu|deflate_cpu|qp_dyn_quad" 2>/dev/null
    sleep 10
}
run () {   # run <tag> <units> <alloc> [cpu-cpus fpga-cpus]
    local tag=$1 units=$2 alloc=$3 cpu=${4:-} fpga=${5:-}
    local args=(--config "$CFG" --units "$units" --alloc "$alloc" --fpga-devices 0,1)
    [[ -n $cpu ]] && args+=(--cpu-cpus "$cpu" --fpga-cpus "$fpga")
    say "=== $tag  alloc $alloc  cpu ${cpu:-libera}  fpga ${fpga:-libera}"
    ( cd "$BASE" && python3 $RM "${args[@]}" --run --tag "$tag" --outdir "$OUT" ) \
        > "$OUT/$tag.out" 2>&1
    local rc=$?
    echo -e "$tag\t$(execs)" >> "$OUT/kds.tsv"
    grep -E "MAKESPAN|scheda [01]:|Traceback|ERR" "$OUT/$tag.out" | head -5
    if (( rc != 0 )); then say "ERRORE: $tag terminata con codice $rc"; pulizia; fi
    sleep "$PAUSA"
}

idle iniziale

say "### parte 0: verifica delle due schede (NB e QP)"
verifica () {   # verifica <tag> <W:4> <variabile> <tempo massimo per scheda, s>
    local tag=$1 u=$2 var=$3 tmax=$4 V="$OUT/$1.out"
    run "$tag" "$u" "$u"
    if grep -q "$var=0 -> device\[0\]" "$V" && grep -q "$var=1 -> device\[1\]" "$V" \
       && grep -q "MAKESPAN" "$V" && python3 - "$OUT/${tag}_timeline.json" "$tmax" <<'EOF2'
import json, sys
d = json.load(open(sys.argv[1]))["sequenze"]; tmax = float(sys.argv[2])
ok = all(k in d and d[k] and 0 < d[k][0]["calcolo_s"] < tmax for k in ("FPGA0", "FPGA1"))
print("  calcolo per scheda:", {k: round(d[k][0]["calcolo_s"], 1) for k in ("FPGA0", "FPGA1") if d.get(k)})
sys.exit(0 if ok else 1)
EOF2
    then
        say "verifica $tag ok: una sequenza per scheda, binding $var=0/1, calcolo < $tmax s"
    else
        say "ERRORE: verifica $tag non passata: campagna interrotta"
        kill "$LPID"; exit 1
    fi
}
verifica verifica_nb "NB:4" FPGA_DEVICE 120     # atteso ~89 s per scheda
verifica verifica_qp "QP:4" QP_DEVICE   120     # atteso ~90 s; ~180 s se le schede sono condivise

U4="IM:30,DE:30,QP:30,NB:30"
say "### parte 1: senza pinning, (30, 30, x, 0)"
for t in 14_1 6_1 10_1 14_2 18_1 6_2 14_3; do
    run "d$t" "$U4" "IM:0,DE:${t%_*},QP:30,NB:30"
done

say "### parte 2: partizione statica CPU 0-9 / FPGA 10-47, (30, 30, 30, y)"
for t in 4_1 0_1 8_1 4_2; do
    run "s$t" "$U4" "IM:${t%_*},DE:30,QP:30,NB:30" 0-9 10-47
done

idle finale
say "runs.tsv: $(wc -l < "$OUT/runs.tsv") righe (attese 13)"
cp "$PLOG" "$OUT/" && say "log di potenza copiato in $OUT"
kill "$LPID" 2>/dev/null && say "logger fermato"
say "=== FINE ==="
