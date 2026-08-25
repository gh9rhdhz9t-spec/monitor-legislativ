#!/bin/bash
# Rularea programată: colectează, reconstruiește, republică.
#
# Pornit de launchd la 08:00 și 16:00. launchd folosește ora locală a
# sistemului, deci trecerea la ora de vară se rezolvă de la sine — spre
# deosebire de cron-ul GitHub, care merge doar pe UTC.

set -uo pipefail

# launchd pornește cu un PATH minim, fără directoarele în care stau claude și git.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1
LOG="$REPO/data/update.log"

say(){ echo "[$(TZ=Europe/Bucharest date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

bash scripts/run-update.sh
STATUS=$?

RC=0
case $STATUS in
  0) bash scripts/republish.sh || RC=$? ;;
  2) say "Nimic nou — artefactul rămâne cum e." ;;
  *) say "Colectarea a eșuat (cod $STATUS) — nu republic."; RC=$STATUS ;;
esac

# Ținem jurnalul la o dimensiune rezonabilă.
if [[ -f "$LOG" ]] && [[ $(wc -l < "$LOG") -gt 4000 ]]; then
  tail -2000 "$LOG" > "$LOG.trim" && mv "$LOG.trim" "$LOG"
fi

exit $RC
