#!/bin/bash
# Republică artefactul construit, la aceeași adresă.
#
# Artefactele se pot actualiza doar dintr-o sesiune Claude, așa că lansăm una
# fără interfață. `url` este obligatoriu: fără el s-ar crea un artefact nou,
# la altă adresă, în loc să fie actualizat cel existent.

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FILE="$REPO/dist/radar-legislativ.html"
URL="https://claude.ai/code/artifact/e6c1fd26-5c03-4c23-97c7-4ed78eb439bc"
LOG="$REPO/data/update.log"

say(){ echo "[$(TZ=Europe/Bucharest date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

[[ -f "$FILE" ]] || { say "Lipsește $FILE — nu republic."; exit 1; }

say "Republic artefactul…"
OUT=$(cd "$REPO" && claude -p \
  --allowed-tools Artifact \
  --permission-mode bypassPermissions \
  "Republică artefactul existent, fără să pui întrebări. Folosește un singur apel al uneltei Artifact, cu exact acești parametri:
  file_path: $FILE
  url: $URL
  favicon: ⚖️
  description: Actele din Monitorul Oficial, catalogate tematic și punctate de la 1 la 10 după relevanța pentru dialogul social și economia socială, cu textul integral și modificările evidențiate.
  capabilities: {\"downloads\": true}
Nu citi și nu modifica fișierul, doar publică-l. Răspunde apoi doar cu adresa artefactului." 2>&1)

CODE=$?
echo "$OUT" | tail -5 >> "$LOG"

if [[ $CODE -eq 0 ]] && echo "$OUT" | grep -q "claude.ai/code/artifact"; then
  say "Artefact republicat."
else
  say "EȘEC la republicare (cod $CODE): $(echo "$OUT" | tail -2 | tr '\n' ' ')"
  exit 1
fi
