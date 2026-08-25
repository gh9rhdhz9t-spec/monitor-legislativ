#!/bin/bash
# Rulează colectarea și reconstruiește artefactul.
#
# Trebuie rulat de pe o mașină din România: portalul legislatie.just.ro închide
# conexiunile venite din centre de date, așa că runnerele GitHub nu îl pot citi.
#
# Scriptul aduce actele noi, reface dist/radar-legislativ.html și comite
# rezultatul. Publicarea artefactului o face rutina, după ce acest script iese
# cu codul 0 (nimic nou = codul 2, deci nu are rost o republicare).

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1

LOG="$REPO/data/update.log"
stamp() { TZ=Europe/Bucharest date '+%Y-%m-%d %H:%M:%S'; }
say()   { echo "[$(stamp)] $*" | tee -a "$LOG"; }

say "── pornesc actualizarea ──"

export PAGES="${PAGES:-6}"
export MAX_DETAILS="${MAX_DETAILS:-40}"

if ! python3 scripts/scrape.py 2>&1 | tee -a "$LOG"; then
  say "EȘEC: colectarea nu s-a încheiat cu bine; nu public nimic."
  exit 1
fi

if [[ -z "$(git status --porcelain data/)" ]]; then
  say "Nicio modificare în date — nu e nimic de republicat."
  exit 2
fi

if ! python3 scripts/build_artifact.py 2>&1 | tee -a "$LOG"; then
  say "EȘEC: nu am putut reconstrui artefactul."
  exit 1
fi

TOTAL=$(python3 -c "import json;print(json.load(open('data/acts.json'))['total'])" 2>/dev/null || echo "?")
NOI=$(python3 -c "import json;print(json.load(open('data/acts.json'))['new_this_run'])" 2>/dev/null || echo "?")

git add data/ dist/
git commit -q -m "Actualizare $(stamp) — $NOI acte noi, $TOTAL în total" || {
  say "Nimic de comis."; exit 2; }

git push -q origin main 2>&1 | tee -a "$LOG" \
  || say "Push eșuat — comitul rămâne local, se trimite la rularea următoare."

say "Gata: $NOI acte noi, $TOTAL în total. Artefactul poate fi republicat."
exit 0
