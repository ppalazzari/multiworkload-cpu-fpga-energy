#!/bin/bash
# collect.sh — fills orchestrator/ and data/raw/ of this repository from the
# working copy of the framework on an N48 node.
#
# Run it from the root of this repository, on a node that sees ~/energy_comparisons:
#   ./tools/collect.sh --dry-run     list what would be copied, copy nothing
#   ./tools/collect.sh               copy, compress the power logs, anonymize paths
#
# What it does:
#   - orchestrator/, analysis/scripts/, tools/: the files of ~/energy_comparisons/bin
#     listed in tools/files.txt, and the local modules they import;
#   - data/raw/<campaign>/<folder>/: every raw folder listed in tools/campaigns.tsv;
#     power logs (*.log) are gzip-compressed;
#   - in all copied text files, the home path is replaced by "~" and the user name
#     by "user", so that no personal path ends up in the repository.
# Folders already present in data/raw are skipped, so the script can be rerun.

set -u
U=${USER:-$(id -un)}
SRC=${SRC:-$HOME/energy_comparisons}
DRY=0; [[ ${1:-} == --dry-run ]] && DRY=1
ROOT=$(cd "$(dirname "$0")/.." && pwd)
MAN=$ROOT/tools/campaigns.tsv
say () { echo "[collect] $*"; }
[[ -d $SRC/bin && -d $SRC/work/raw ]] || { say "ERROR: $SRC/bin or $SRC/work/raw not found (set SRC=...)"; exit 1; }
[[ -f $ROOT/README.md && -f $MAN ]] || { say "ERROR: run from the repository (README.md and tools/campaigns.tsv)"; exit 1; }

anonymize () {   # anonymize <file>: home path -> ~, user name -> user (text files only)
    file -b --mime-type "$1" | grep -qE '^text/|json|xml|javascript' || return 0
    sed -i -e "s#$HOME#~#g" -e "s#/afs/[^ /]*/[^ /]*/user/$U#~#g" -e "s#\b$U\b#user#g" "$1"
}

# ---------------------------------------------------------------- code
# Only the files listed in tools/files.txt, plus the local modules they import.
LIST=$ROOT/tools/files.txt
[[ -f $LIST ]] || { say "ERROR: tools/files.txt not found"; exit 1; }
declare -A DEST
while IFS=$'\t' read -r dst f; do
    [[ -z ${dst:-} || $dst == \#* ]] && continue
    DEST[$f]=$dst
done < "$LIST"
# local imports of the listed Python files
changed=1
while (( changed )); do
    changed=0
    for f in "${!DEST[@]}"; do
        [[ $f == *.py && -f $SRC/bin/$f ]] || continue
        for m in $(grep -hoE '^(import|from) [A-Za-z_][A-Za-z0-9_]*' "$SRC/bin/$f" | awk '{print $2}' | sort -u); do
            if [[ -f $SRC/bin/$m.py && -z ${DEST[$m.py]:-} ]]; then
                DEST[$m.py]=orchestrator; changed=1; say "  + $m.py (imported by $f)"
            fi
        done
    done
done
say "code from $SRC/bin"
n=0
for f in $(printf '%s\n' "${!DEST[@]}" | sort); do
    if [[ ! -f $SRC/bin/$f ]]; then say "  WARNING: $f not found"; continue; fi
    if (( DRY )); then echo "  ${DEST[$f]}/$f"; else
        mkdir -p "$ROOT/${DEST[$f]}"; cp -p "$SRC/bin/$f" "$ROOT/${DEST[$f]}/$f"; anonymize "$ROOT/${DEST[$f]}/$f"; fi
    n=$((n + 1))
done
say "  $n files"

# ---------------------------------------------------------------- raw data
tot=0; miss=0
while IFS=$'\t' read -r camp paper globs; do
    [[ -z ${camp:-} || $camp == \#* ]] && continue
    found=0
    if [[ $camp == equal_work ]] && pgrep -u "$U" -f "fase_scala12" >/dev/null; then
        say "WARNING: the equal-work campaign is still running: skipped, rerun collect.sh when it ends"; continue; fi
    for g in ${globs//,/ }; do
        for d in $SRC/work/raw/$g; do
            [[ -d $d ]] || continue
            found=1; dst=$ROOT/data/raw/$camp/$(basename "$d")
            if [[ -d $dst ]]; then say "  skip (present) $camp/$(basename "$d")"; continue; fi
            sz=$(du -sh "$d" | cut -f1)
            if (( DRY )); then echo "  data/raw/$camp/$(basename "$d")  ($sz)"; continue; fi
            mkdir -p "$dst"
            cp -rp "$d/." "$dst/"
            find "$dst" -type f -name '*.log' -exec gzip -9 {} \;
            while IFS= read -r -d '' t; do anonymize "$t"; done < <(find "$dst" -type f -not -name '*.gz' -print0)
            say "  $camp/$(basename "$d")  ($sz)"; tot=$((tot + 1))
        done
    done
    (( found )) || { say "WARNING: no folder found for campaign $camp ($globs)"; miss=$((miss + 1)); }
done < "$MAN"

(( DRY )) && { say "dry run: nothing copied"; exit 0; }
say "copied $tot raw folders; campaigns without data: $miss"
say "remaining personal strings, if any (check before pushing):"
grep -rIl -e "$U" -e "$HOME" "$ROOT/orchestrator" "$ROOT/data/raw" 2>/dev/null | head || true
du -sh "$ROOT/data/raw" "$ROOT/orchestrator"
say "largest files (GitHub refuses files > 100 MB):"
find "$ROOT/data" -type f -size +50M -exec ls -lh {} \; | awk '{print "  " $5, $9}'
