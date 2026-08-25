#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Textul integral al unui act si operatiunile de modificare pe care le produce.

Pentru fiecare act descarcam pagina de detaliu, o transformam in blocuri
structurate (articole, puncte, paragrafe) si marcam ce anume face fiecare bloc:
abroga, modifica, introduce text nou.

Marcajele provin exclusiv din ce declara actul insusi si din tabelul "Actiuni
induse" al portalului. Nu incercam sa reconstituim forma dinaintea modificarii:
portalul publica doar versiunea consolidata, fara istoric, asa ca textul "vechi"
ar trebui ghicit - iar un diff inventat e mai daunator decat lipsa lui.

Rezultatul se scrie in data/acts/<id>.json si este incarcat de dashboard la cerere.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scrape import (  # noqa: E402
    BASE, UA, BROWSER_HEADERS, _OPENER, _decode, _warm_up, clean, fetch, fold,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACTS_DIR = os.path.join(ROOT, "data", "acts")

DETAIL_URL = BASE + "/Public/DetaliiDocument/%s"
INDUSE_URL = BASE + "/Public/actiuniInduse"

# Clasele de continut folosite de portal, in ordinea in care apar in pagina.
BLOCK_RE = re.compile(
    r'<(?P<tag>span|div|p)[^>]*class="(?P<cls>S_(?:HDR|DEN|ART_TTL|ART_BDY|PCT_TTL|PCT|'
    r'PCT_BDY|ALN_TTL|ALN|ALN_BDY|LIT|LIT_BDY|PAR|SMN_TTL|SMN|NOT|ANX_TTL|ANX)[A-Z_]*)"'
    r'[^>]*>(?P<body>.*?)</(?P=tag)>', re.S)

# Blocuri pur decorative sau de navigatie.
SKIP_CLS = {"S_PCT_SHORT", "S_ART"}

# Verbe de modificare, in forma normalizata (fara diacritice).
RE_ABROGA = re.compile(r"\bse abrog|\bau fost abrogat|\bse elimin")
RE_MODIFICA = re.compile(r"\bse modific|\bse inlocui|\bva avea urmatorul cuprins")
RE_INTRODUCE = re.compile(r"\bse introduc|\bse completeaz|\bse adaug")
RE_CUPRINS = re.compile(r"urm[aă]torul cuprins\s*:?\s*", re.I)

# "Punctul 3", "Articolul 5", "Alineatul (2)", "Litera a)"
RE_ELEMENT = re.compile(
    r"\b(punctul|punctele|articolul|alineatul|alineatele|litera|literele|anexa)\s+"
    r"([0-9]+(?:\^[0-9]+)?|\([0-9a-z]+\)|[a-z]\)|[IVXLC]+)", re.I)


def strip_tags(x: str) -> str:
    return clean(x)


def fetch_blocks(doc_id: str):
    """Descarca pagina de detaliu si o reduce la o lista de blocuri de text."""
    page = fetch(DETAIL_URL % doc_id, referer=BASE + "/Public/RezultateCautare")
    # Textul actului incepe la titlul marcat S_DEN; tot ce e inainte (meniu,
    # cuprins, butonul "Forma printabila") repeta continutul sau e navigatie.
    m = re.search(r'<[a-z]+[^>]*class="[^"]*\bS_DEN\b[^"]*"', page)
    body = page[m.start():] if m else page
    for stop in ('<footer', 'class="doc_footer"', 'id="mesajBetaModal"'):
        i = body.find(stop)
        if i > 0:
            body = body[:i]

    blocks, seen = [], set()
    for mm in BLOCK_RE.finditer(body):
        cls = mm.group("cls")
        if cls in SKIP_CLS:
            continue
        txt = strip_tags(mm.group("body"))
        if not txt or txt in ("+", "-", "..."):
            continue
        key = (cls, txt)
        if key in seen:            # portalul repeta unele blocuri
            continue
        seen.add(key)
        blocks.append({"cls": cls, "text": txt})
    return blocks


def fetch_operations(doc_id: str):
    """Tabelul 'Actiuni induse': ce act si ce element modifica actul curent."""
    try:
        _warm_up()          # aceeasi sesiune ca restul cererilor
        data = urllib.parse.urlencode({"contor": doc_id}).encode()
        req = urllib.request.Request(INDUSE_URL, data=data)
        for k, v in BROWSER_HEADERS:
            if k not in ("Accept", "Sec-Fetch-Dest", "Sec-Fetch-Mode", "Sec-Fetch-User"):
                req.add_header(k, v)
        req.add_header("Accept", "application/json, text/javascript, */*; q=0.01")
        req.add_header("X-Requested-With", "XMLHttpRequest")
        req.add_header("Sec-Fetch-Dest", "empty")
        req.add_header("Sec-Fetch-Mode", "cors")
        req.add_header("Referer", DETAIL_URL % doc_id)
        with _OPENER.open(req, timeout=45) as r:
            payload = json.loads(_decode(r))
    except Exception as e:                      # noqa: BLE001 - orice esec = fara operatiuni
        print("    ! actiuniInduse %s: %s" % (doc_id, e), file=sys.stderr)
        return []

    markup = payload.get("acte") or ""
    if "Nu exist" in markup:
        return []

    ops = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", markup, re.S):
        cells = [strip_tags(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        cells = [c for c in cells if c]
        if len(cells) < 3:
            continue
        if fold(cells[0]).startswith("sectiune"):     # randul de antet
            continue
        tid = re.search(r"DetaliiDocument[A-Za-z]*/(\d+)", row)
        ops.append({
            "sectiune": cells[0],
            "operatiune": cells[1],
            "tinta": " ".join(cells[2:]),
            "tinta_id": tid.group(1) if tid else None,
        })
    return ops


def classify_block(text: str):
    """Ce operatiune descrie blocul: abrogare, modificare, introducere sau nimic."""
    f = fold(text)
    if RE_ABROGA.search(f):
        return "abrogat"
    if RE_MODIFICA.search(f):
        return "modificat"
    if RE_INTRODUCE.search(f):
        return "introdus"
    return None


def new_wording(text: str):
    """Textul nou dintr-un bloc de tipul '... va avea urmatorul cuprins: ...'."""
    m = RE_CUPRINS.search(text)
    if not m:
        return None
    tail = text[m.end():].strip().strip('"“”«»').strip()
    return tail or None


def element_label(text: str):
    m = RE_ELEMENT.search(text)
    return m.group(2) if m else None


def build(doc_id: str, meta: dict):
    blocks = fetch_blocks(doc_id)
    ops = fetch_operations(doc_id)

    # Un act care nu induce nicio actiune asupra altuia este act nou, nu unul
    # de modificare - dashboard-ul il coloreaza diferit.
    act_nou = not any("MODIFICA" in o["operatiune"] or "ABROGA" in o["operatiune"]
                      or "COMPLETEAZA" in o["operatiune"] for o in ops)

    out_blocks = []
    for b in blocks:
        item = {"cls": b["cls"], "text": b["text"]}
        op = classify_block(b["text"])
        if op:
            item["op"] = op
            nw = new_wording(b["text"])
            if nw:
                # Portalul nu publica forma anterioara, deci putem evidentia
                # doar textul nou, nu si ce a fost inlocuit.
                item["nou"] = nw
                item["prefix"] = b["text"][:len(b["text"]) - len(nw)].rstrip()
        out_blocks.append(item)

    return {
        "id": doc_id,
        "titlu": meta.get("titlu", ""),
        "tip": meta.get("tip", ""),
        "numar": meta.get("numar", ""),
        "emitenti": meta.get("emitenti", []),
        "data_publicare": meta.get("data_publicare"),
        "data_vigoare": meta.get("data_vigoare"),
        "monitor_nr": meta.get("monitor_nr", ""),
        "act_nou": act_nou,
        "operatiuni": ops,
        "blocuri": out_blocks,
    }


def path_for(doc_id: str) -> str:
    return os.path.join(ACTS_DIR, "%s.json" % doc_id)


def save(doc: dict):
    os.makedirs(ACTS_DIR, exist_ok=True)
    p = path_for(doc["id"])
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, p)


if __name__ == "__main__":
    for did in sys.argv[1:]:
        d = build(did, {})
        save(d)
        print("%s: %d blocuri, %d operatiuni, %d marcaje" % (
            did, len(d["blocuri"]), len(d["operatiuni"]),
            sum(1 for b in d["blocuri"] if b.get("op"))))
