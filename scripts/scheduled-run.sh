#!/bin/bash
# Rularea programată: colectează, reconstruiește, publică pe GitHub.
#
# Pornit de launchd la 08:00 și 16:00. launchd folosește ora locală a
# sistemului, deci trecerea la ora de vară se rezolvă de la sine.
#
# Republicarea artefactului NU se face aici: unealta Artifact nu există în
# `claude -p` (CLI-ul fără interfață). O rutină în cloud preia fișierul
# construit de aici, din repo, și îl republică la 09:20 și 17:20 ora României.

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
  0) say "Date noi publicate pe GitHub; rutina din cloud le va prelua." ;;
  2) say "Nimic nou — artefactul rămâne cum e." ;;
  *) say "Colectarea a eșuat (cod $STATUS)."; RC=$STATUS ;;
esac

# Ținem jurnalul la o dimensiune rezonabilă.
if [[ -f "$LOG" ]] && [[ $(wc -l < "$LOG") -gt 4000 ]]; then
  tail -2000 "$LOG" > "$LOG.trim" && mv "$LOG.trim" "$LOG"
fi

exit $RC
