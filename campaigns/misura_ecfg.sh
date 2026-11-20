#!/bin/bash
# misura_ecfg.sh — energia e tempo di riconfigurazione (E_cfg, t_cfg) su
# cresco8-fpga1, scheda 1 (cc:00.1, sana). ~1.3 h.
# 30 cicli QP -> DE -> IM con 1 blocco di lavoro, 25 s di pausa fra un
# caricamento e l'altro (base locale per l'energia); profilo hpc-compute.
#
# Uso:
#   ./misura_ecfg.sh --check
#   pagsh -c 'aklog && setsid nohup ~/misura_ecfg.sh > /tmp/ecfg_$(date +%m%d_%H%M).log 2>&1 < /dev/null &'
set -u
BASE=${BASE:-$HOME/energy_comparisons}
CFG=${CFG:-bin/workloads_qp8.json}
DEV=${DEV:-1}
REPS=${REPS:-30}
IDLE=${IDLE:-300}
SETTLE=${SETTLE:-600}
TUNED=/usr/sbin/tuned-adm
STAMP=$(date +%m%d_%H%M)
NODE=$(hostname -s)
OUT=$BASE/work/raw/ecfg_${NODE}_$STAMP
PLOG=/tmp/ecfg_power_$STAMP.log
say () { echo "[$(date +%H:%M:%S)] $*"; }
check () {
    local ok=1
    say "nodo $NODE  governor $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor)"
    [[ $NODE == cresco8-fpga1 ]] || say "ATTENZIONE: previsto su cresco8-fpga1"
    sudo -n -l $TUNED >/dev/null 2>&1 || { say "ERRORE: nessun permesso per $TUNED"; ok=0; }
    [[ -f $BASE/$CFG ]] || { say "ERRORE: manca $CFG"; ok=0; }
    if pgrep -u "$USER" -f "run_multi|power_logger.py|\.xclbin|misura_ecfg.py" > /dev/null; then
        say "ERRORE: processi gia' attivi sul nodo"; ok=0; fi
    return $(( ok == 1 ? 0 : 1 ))
}
if [[ ${1:-} == --check ]]; then check; exit $?; fi
check || exit 1
ripristino () { [[ -n ${LPID:-} ]] && kill "$LPID" 2>/dev/null; sudo -n $TUNED profile cresco8 >/dev/null 2>&1; say "profilo cresco8"; }
trap ripristino EXIT
trap 'exit 1' INT TERM HUP
sudo -n $TUNED profile hpc-compute >/dev/null 2>&1
say "profilo hpc-compute; attesa $SETTLE s"; sleep "$SETTLE"
mkdir -p "$OUT"
{ echo "# ecfg $STAMP nodo $NODE scheda $DEV"; echo "# governor $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor)"
  echo "# xrt $(xrt-smi --version 2>/dev/null | grep -m1 -i version | tr -s ' ')"; echo "# avvio $(uptime -s)"; } > "$OUT/info.txt"
setsid nohup taskset -c 47 python3 "$BASE/bin/power_logger.py" --inband --no-fpga > "$PLOG" 2>/tmp/ecfg_power_err_$STAMP.log < /dev/null &
sleep 60; LPID=$(pgrep -u "$USER" -f power_logger.py | head -1)
(( $(wc -l < "$PLOG") >= 40 )) || { say "ERRORE: logger non attivo"; exit 1; }
say "logger ok"; echo -e "finestra\tt0\tt1" > "$OUT/idle_windows.tsv"
t0=$(date +%s.%N); sleep "$IDLE"; echo -e "iniziale\t$t0\t$(date +%s.%N)" >> "$OUT/idle_windows.tsv"
( cd "$BASE" && python3 bin/misura_ecfg.py --config "$CFG" --device "$DEV" --reps "$REPS" --gap 25 --out "$OUT" )
t0=$(date +%s.%N); sleep "$IDLE"; echo -e "finale\t$t0\t$(date +%s.%N)" >> "$OUT/idle_windows.tsv"
cp "$PLOG" "$OUT/" && say "log copiato in $OUT"
say "=== FINE ==="
