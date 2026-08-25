#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Construieste artefactul: o singura pagina HTML, cu datele incluse in ea.

Artefactele ruleaza sub un CSP strict, care nu permite cereri catre alte gazde
si nici catre fisiere alaturate. Tot ce afiseaza pagina trebuie deci sa fie
inclus in ea, asa ca aici lipim indexul actelor si textele integrale direct in
HTML, sub forma de JSON.
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "acts.json")
ACTS_DIR = os.path.join(ROOT, "data", "acts")
OUT = os.path.join(ROOT, "dist", "radar-legislativ.html")

# Limite de siguranta: baza creste continuu, artefactul are un plafon de 16 MB.
MAX_ACTS = int(os.environ.get("MAX_ARTIFACT_ACTS", "1200"))
MAX_DETAILS = int(os.environ.get("MAX_ARTIFACT_DETAILS", "400"))

TEMPLATE_PATH = os.path.join(ROOT, "scripts", "artifact_template.html")


def main():
    with open(DB_PATH, encoding="utf-8") as f:
        db = json.load(f)

    acts = db["acts"][:MAX_ACTS]
    keep = {a["id"] for a in acts}

    details, budget = {}, MAX_DETAILS
    if os.path.isdir(ACTS_DIR):
        # Pastram textele pentru cele mai relevante acte din fereastra afisata.
        for a in sorted(acts, key=lambda x: (-x["scor"], x.get("data_publicare") or "")):
            if budget <= 0:
                break
            p = os.path.join(ACTS_DIR, "%s.json" % a["id"])
            if a["id"] in keep and os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    details[a["id"]] = json.load(f)
                budget -= 1

    # Marcam corect ce are text *in artefact* (nu doar pe disc).
    for a in acts:
        a["are_text"] = a["id"] in details

    payload = {
        "generated_at": db.get("generated_at"),
        "total_baza": db.get("total"),
        "acts": acts,
        "details": details,
    }

    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        html = f.read()

    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # </script> in date ar inchide blocul mai devreme.
    blob = blob.replace("</", "<\\/")
    html = html.replace("__DATE__", blob)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)

    mb = os.path.getsize(OUT) / 1e6
    print("%s — %d acte, %d cu text integral, %.2f MB"
          % (os.path.relpath(OUT, ROOT), len(acts), len(details), mb))
    if mb > 14:
        print("! aproape de plafonul de 16 MB; scade MAX_ARTIFACT_ACTS/DETAILS",
              file=sys.stderr)


if __name__ == "__main__":
    main()
