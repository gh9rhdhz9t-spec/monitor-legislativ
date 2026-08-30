#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Monitor legislativ — colecteaza actele publicate recent pe legislatie.just.ro,
le clasifica tematic si le acorda un scor de relevanta (1-10) pentru dialog social
si economie sociala.

Rezultatul este scris incremental in data/acts.json (baza de date cumulativa,
cheia = id-ul documentului de pe portal).
"""

from __future__ import annotations

import gzip
import html
import http.cookiejar
import io as _io
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lexicon import (  # noqa: E402
    TIER_A, TIER_B, TIER_C, EMITENT_BOOST, TIP_ACT_BOOST, NOISE,
    CATEGORIES, CATEGORY_FALLBACK,
)

BASE = "https://legislatie.just.ro"
SEARCH = BASE + "/Public/RezultateCautare"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
DB_PATH = os.path.join(DATA_DIR, "acts.json")

PAGES = int(os.environ.get("PAGES", "4"))          # 4 x 50 = 200 acte / rulare
PER_PAGE_CODE = "5"                                 # 5 => 50 rezultate/pagina
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "365"))

# Textul integral se descarca doar pentru actele relevante: la ~16 KB per act,
# stocarea intregului Monitor Oficial ar ajunge la sute de MB pe an.
DETAIL_MIN_SCORE = int(os.environ.get("DETAIL_MIN_SCORE", "4"))
DETAIL_RETENTION_DAYS = int(os.environ.get("DETAIL_RETENTION_DAYS", "180"))
MAX_DETAILS = int(os.environ.get("MAX_DETAILS", "40"))

RO_MONTHS = {
    "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4, "mai": 5,
    "iunie": 6, "iulie": 7, "august": 8, "septembrie": 9, "octombrie": 10,
    "noiembrie": 11, "decembrie": 12,
}


# --------------------------------------------------------------------------
# Utilitare text
# --------------------------------------------------------------------------

def fold(s: str) -> str:
    """Elimina diacriticele si trece la litere mici, pentru potriviri robuste.

    Portalul amesteca variantele Unicode (s-comma vs s-cedilla) si uneori scrie
    fara diacritice, asa ca normalizam totul inainte de a cauta cuvinte-cheie.
    """
    if not s:
        return ""
    s = s.replace("ș", "s").replace("ş", "s").replace("Ș", "S").replace("Ş", "S")
    s = s.replace("ț", "t").replace("ţ", "t").replace("Ț", "T").replace("Ţ", "T")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def clean(s: str) -> str:
    """Scoate tag-urile HTML si normalizeaza spatiile albe."""
    s = re.sub(r"<br\s*/?>", " ", s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = s.replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def parse_ro_date(s: str):
    """'25 august 2026' sau '25/08/2026' -> '2026-08-25' (ISO). None daca nu se poate."""
    if not s:
        return None
    s = s.strip()
    m = re.search(r"(\d{1,2})\s+([a-zA-Zăâîșşţț]+)\s+(\d{4})", s)
    if m:
        month = RO_MONTHS.get(fold(m.group(2)))
        if month:
            try:
                return "%04d-%02d-%02d" % (int(m.group(3)), month, int(m.group(1)))
            except ValueError:
                return None
    m = re.search(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", s)
    if m:
        try:
            return "%04d-%02d-%02d" % (int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


# --------------------------------------------------------------------------
# Retea
# --------------------------------------------------------------------------

# Portalul refuza cererile care nu arata a browser real: raspunde cu
# "Remote end closed connection" cand lipsesc cookie-urile de sesiune sau
# antetele obisnuite. Folosim un opener cu cookie jar, pornit printr-o vizita
# pe pagina principala, exact ca un vizitator obisnuit.
_COOKIES = http.cookiejar.CookieJar()
_OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_COOKIES))
_WARMED = False

BROWSER_HEADERS = [
    ("User-Agent", UA),
    ("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
               "image/webp,*/*;q=0.8"),
    ("Accept-Language", "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7"),
    ("Accept-Encoding", "gzip, deflate"),
    ("Connection", "keep-alive"),
    ("Upgrade-Insecure-Requests", "1"),
    ("Sec-Fetch-Dest", "document"),
    ("Sec-Fetch-Mode", "navigate"),
    ("Sec-Fetch-Site", "same-origin"),
    ("Sec-Fetch-User", "?1"),
]


def _decode(resp) -> str:
    raw = resp.read()
    enc = (resp.headers.get("Content-Encoding") or "").lower()
    if "gzip" in enc:
        raw = gzip.GzipFile(fileobj=_io.BytesIO(raw)).read()
    elif "deflate" in enc:
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw.decode("utf-8", errors="replace")


def _warm_up():
    """Ia cookie-urile de sesiune de pe pagina principala."""
    global _WARMED
    if _WARMED:
        return
    try:
        req = urllib.request.Request(BASE + "/")
        for k, v in BROWSER_HEADERS:
            req.add_header(k, v)
        with _OPENER.open(req, timeout=60) as r:
            _decode(r)
        _WARMED = True
        print("  · sesiune initializata (%d cookie-uri)" % len(_COOKIES))
    except Exception as e:                      # noqa: BLE001
        print("  ! nu am putut initializa sesiunea: %s" % e, file=sys.stderr)


def fetch(url: str, tries: int = 5, referer: str = None) -> str:
    _warm_up()
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url)
            for k, v in BROWSER_HEADERS:
                req.add_header(k, v)
            req.add_header("Referer", referer or (BASE + "/"))
            with _OPENER.open(req, timeout=60) as r:
                return _decode(r)
        except (urllib.error.URLError, OSError, EOFError) as e:
            last = e
            wait = min(60, 5 * (2 ** attempt))     # 5, 10, 20, 40, 60
            print("  ! %s (incercarea %d/%d), reincerc in %ds"
                  % (e, attempt + 1, tries, wait), file=sys.stderr)
            time.sleep(wait)
            if attempt == 1:                       # a doua ratare: reia sesiunea
                global _WARMED
                _WARMED = False
                _COOKIES.clear()
                _warm_up()
    raise RuntimeError("Nu am putut descarca %s: %s" % (url, last))


# --------------------------------------------------------------------------
# Parsare
# --------------------------------------------------------------------------

ITEM_RE = re.compile(r'<div class="search_result_item">(.*?)</div>\s*</div>', re.S)
ITEM_FALLBACK_RE = re.compile(r'<div class="search_result_item">(.*?)(?=<div class="search_result_item">|<div class="search_pagination"|</section>|$)', re.S)


def split_items(page_html: str):
    body = page_html
    m = re.search(r'<div class="search_result_page">(.*)', page_html, re.S)
    if m:
        body = m.group(1)
    items = ITEM_FALLBACK_RE.findall(body)
    return items


def parse_item(chunk: str):
    m = re.search(r'href="(/Public/DetaliiDocument/(\d+))"[^>]*>(.*?)</a>', chunk, re.S)
    if not m:
        return None
    doc_id = m.group(2)
    header = clean(m.group(3))
    # "1. HOTARARE 632 14/08/2026"
    header = re.sub(r"^\s*\d+\.\s*", "", header)
    hm = re.match(r"^([A-ZĂÂÎȘŞȚŢ \-]+?)\s+(?:(\S+)\s+)?(\d{1,2}/\d{1,2}/\d{4})\s*$", header)
    if hm:
        tip = hm.group(1).strip()
        numar = (hm.group(2) or "").strip()
        data_act = parse_ro_date(hm.group(3))
    else:
        tip = header.split()[0] if header else ""
        numar = ""
        data_act = None

    den = re.search(r'<span class="S_DEN">(.*?)</span>', chunk, re.S)
    titlu = clean(den.group(1)) if den else header

    par = re.search(r'<span class="S_PAR"[^>]*>(.*?)</span>', chunk, re.S)
    descriere = clean(par.group(1)) if par else ""

    emt = re.search(r'<span class="S_EMT_BDY">(.*?)</span>', chunk, re.S)
    emitenti = []
    if emt:
        emitenti = [clean(x) for x in re.findall(r"<li>(.*?)</li>", emt.group(1), re.S)]
        emitenti = [e for e in emitenti if e]
        if not emitenti:
            t = clean(emt.group(1))
            if t:
                emitenti = [t]

    pub = re.search(r'<span class="S_PUB_BDY">(.*?)</span>', chunk, re.S)
    publicatie = clean(pub.group(1)) if pub else ""
    data_publicare = parse_ro_date(publicatie)
    mo = re.search(r"nr\.\s*(\d+)", publicatie)
    mo_nr = mo.group(1) if mo else ""

    viv = re.search(r"Data intrarii in vigoare\s*:?\s*([^<\n]+)", clean(chunk))
    data_vigoare = parse_ro_date(viv.group(1)) if viv else None
    vigoare_text = clean(viv.group(1)) if viv else ""

    return {
        "id": doc_id,
        "tip": tip,
        "numar": numar,
        "data_act": data_act,
        "titlu": titlu,
        "descriere": descriere,
        "emitenti": emitenti,
        "monitor_nr": mo_nr,
        "data_publicare": data_publicare,
        "data_vigoare": data_vigoare,
        # Pastram textul brut doar cand nu s-a putut interpreta ca data
        # (de ex. "la data publicarii" sau "60 de zile de la publicare").
        "vigoare_text": "" if data_vigoare else vigoare_text,
    }


# --------------------------------------------------------------------------
# Clasificare + scorare
# --------------------------------------------------------------------------

def _stem(word: str) -> str:
    """Trunchiaza terminatia unui cuvant ca sa acopere formele flexionare.

    Romana articuleaza si declina substantivele ('economie' -> 'economia',
    'consiliul' -> 'consiliului', 'munca' -> 'muncii'), asa ca o potrivire
    exacta de subsir pierde majoritatea aparitiilor reale.
    """
    n = len(word)
    if n >= 8:
        return word[:-3]
    if n >= 6:
        return word[:-2]
    if n == 5:
        return word[:-1]
    return word


def build_pattern(key: str):
    parts = []
    for w in key.split():
        if w.isalpha():
            parts.append(re.escape(_stem(w)) + r"[a-z]*")
        else:
            parts.append(re.escape(w) + r"[a-z]*")
    return re.compile(r"\b" + r"[\s\-,]+".join(parts))


_PAT_CACHE = {}


def pattern_for(key: str):
    p = _PAT_CACHE.get(key)
    if p is None:
        p = build_pattern(key)
        _PAT_CACHE[key] = p
    return p


def matches(key: str, text: str) -> bool:
    return pattern_for(key).search(text) is not None


_GROUP_CACHE = {}


def concept_groups(table: dict):
    """Grupeaza cheile care descriu acelasi concept.

    Dupa trunchierea terminatiilor, variante precum 'salariu', 'salarii',
    'salariati' si 'salarizare' se potrivesc pe acelasi cuvant din text; fara
    grupare, un singur termen ar fi numarat de patru ori. Doua chei ajung in
    acelasi grup daca tiparul uneia recunoaste textul celeilalte.
    """
    key = id(table)
    cached = _GROUP_CACHE.get(key)
    if cached is not None:
        return cached

    keys = list(table)
    parent = {k: k for k in keys}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if pattern_for(a).search(b) or pattern_for(b).search(a):
                union(a, b)

    groups = {k: find(k) for k in keys}
    _GROUP_CACHE[key] = groups
    return groups


def count_hits(text: str, table: dict):
    """Suma ponderilor conceptelor gasite in text (un concept se numara o data)."""
    groups = concept_groups(table)
    best = {}
    for kw, w in table.items():
        if matches(kw, text):
            g = groups[kw]
            if g not in best or abs(w) > abs(best[g][1]):
                best[g] = (kw, w)
    total = sum(w for _, w in best.values())
    matched = [kw for kw, _ in best.values()]
    return total, matched


def classify(act: dict) -> str:
    """Categoria tematica. Continutul actului cantareste dublu fata de emitent:
    un minister poate emite acte care nu tin de domeniul sau (de ex. Ministerul
    Muncii care actualizeaza inventarul unei cladiri)."""
    body = fold(" ".join([act["titlu"], act["descriere"], act["tip"]]))
    emit = fold(" ".join(act["emitenti"]))
    best, best_score = CATEGORY_FALLBACK, 0
    for name, kws in CATEGORIES:
        score = (2 * sum(1 for kw in kws if matches(kw, body))
                 + sum(1 for kw in kws if matches(kw, emit)))
        if score > best_score:
            best, best_score = name, score
    return best


# Categoriile in care un termen din nucleul dur chiar descrie subiectul actului.
SOCIAL_CATS = {"Muncă și dialog social", "Economie socială", "Protecție socială și pensii"}


def score_act(act: dict, categorie: str = ""):
    """Returneaza (scor 1-10, detalii) pentru relevanta in dialog social / economie sociala."""
    text = fold(" ".join([act["titlu"], act["descriere"]]))
    emit = fold(" ".join(act["emitenti"]))
    tip = fold(act["tip"])

    a, ka = count_hits(text, TIER_A)
    b, kb = count_hits(text, TIER_B)
    c, kc = count_hits(text, TIER_C)
    n, kn = count_hits(text, NOISE)

    a_n = len(ka)          # cate concepte distincte din nucleul dur, nu doar ponderea

    e = 0
    ke = []
    for kw, w in EMITENT_BOOST.items():
        if matches(kw, emit):
            e = max(e, w)          # doar cel mai relevant emitent, nu suma
            ke.append(kw)

    t = 0
    for kw, w in TIP_ACT_BOOST.items():
        if kw in tip:
            t = max(t, w, key=abs) if t else w

    # Un singur termen din nucleul dur, intr-un act al carui emitent si categorie
    # nu au legatura cu munca, e aproape intotdeauna o trimitere incidentala --
    # de pilda un tarif veterinar indexat cu "salariul minim pe economie". Cerem
    # o confirmare inainte sa cantareasca cat un act chiar despre subiect.
    coroborat = (a_n >= 2 or e >= 3 or b >= 6 or categorie in SOCIAL_CATS)
    if a_n == 1 and not coroborat:
        a = min(a, 3)

    # Plafonam contributia fiecarui nivel ca sa nu domine un singur termen repetat.
    raw = min(a, 14) + min(b, 9) + min(c, 5) + e + t + n

    # Scala 1-10: nucleul dur (Tier A) ridica actul in jumatatea superioara,
    # restul se aseaza dupa scorul brut acumulat.
    if (a >= 6 and coroborat) or (a >= 5 and e >= 4):
        if raw >= 12:
            scor = 10
        elif raw >= 9:
            scor = 9
        else:
            scor = 8
    elif raw >= 12:
        scor = 8
    elif raw >= 10:
        scor = 7
    elif raw >= 8:
        scor = 6
    elif raw >= 6:
        scor = 5
    elif raw >= 4:
        scor = 4
    elif raw >= 2:
        scor = 3
    elif raw >= 1:
        scor = 2
    else:
        scor = 1

    # Un act de zgomot administrativ nu poate urca peste 1, oricat de multe
    # cuvinte generice ar contine.
    if n <= -5 and a == 0:
        scor = min(scor, 1)

    return scor, {
        "raw": raw,
        "tier_a": a, "tier_a_n": a_n, "coroborat": coroborat,
        "tier_b": b, "tier_c": c, "noise": n,
        "emitent": e, "tip": t,
        "keywords": (ka + kb + ke)[:8],
    }


# --------------------------------------------------------------------------
# Rulare
# --------------------------------------------------------------------------

def scrape():
    seen = {}
    for page in range(1, PAGES + 1):
        url = "%s?page=%d&rezultatePerPagina=%s" % (SEARCH, page, PER_PAGE_CODE)
        print("→ pagina %d/%d" % (page, PAGES))
        chunks = split_items(fetch(url))
        if not chunks:
            print("  ! nicio inregistrare pe pagina %d, opresc" % page, file=sys.stderr)
            break
        got = 0
        for ch in chunks:
            act = parse_item(ch)
            if act and act["id"] not in seen:
                seen[act["id"]] = act
                got += 1
        print("  %d acte (total unic: %d)" % (got, len(seen)))
        time.sleep(1.5)          # politete fata de server
    return list(seen.values())


def enrich(act: dict, now_iso: str) -> dict:
    act["categorie"] = classify(act)
    scor, det = score_act(act, act["categorie"])
    act["scor"] = scor
    act["termeni"] = det["keywords"][:5]
    act["first_seen"] = now_iso[:10]
    return act


def fetch_details(ordered, now):
    """Descarca textul integral pentru actele relevante care nu il au deja.

    Fiecare rulare completeaza un numar limitat de acte, ca sa nu solicitam
    excesiv portalul; in cateva rulari acoperirea ajunge la zi.
    """
    import detail

    cutoff = (now - timedelta(days=DETAIL_RETENTION_DAYS)).date().isoformat()
    wanted, keep = [], set()
    for a in ordered:
        ref = a.get("data_publicare") or (a.get("first_seen") or "")[:10]
        if a["scor"] < DETAIL_MIN_SCORE or (ref and ref < cutoff):
            continue
        keep.add(a["id"])
        if not os.path.exists(detail.path_for(a["id"])):
            wanted.append(a)

    if wanted:
        batch = wanted[:MAX_DETAILS]
        print("\nText integral: %d de descarcat (%d in coada)"
              % (len(batch), len(wanted) - len(batch)))
        for a in batch:
            try:
                detail.save(detail.build(a["id"], a))
                a["are_text"] = True
                print("  ✓ %s %s" % (a["tip"], a["numar"] or a["id"]))
            except Exception as e:                      # noqa: BLE001
                print("  ! %s: %s" % (a["id"], e), file=sys.stderr)
            time.sleep(1.2)

    # Marcam ce acte au text disponibil si stergem fisierele iesite din fereastra.
    removed = 0
    if os.path.isdir(detail.ACTS_DIR):
        for fn in os.listdir(detail.ACTS_DIR):
            if fn.endswith(".json") and fn[:-5] not in keep:
                os.remove(os.path.join(detail.ACTS_DIR, fn))
                removed += 1
    for a in ordered:
        a["are_text"] = os.path.exists(detail.path_for(a["id"]))
    have = sum(1 for a in ordered if a.get("are_text"))
    print("Text integral disponibil pentru %d acte (%d fisiere eliminate)"
          % (have, removed))


def main():
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat(timespec="seconds")

    db = {}
    if os.path.exists(DB_PATH):
        try:
            with open(DB_PATH, encoding="utf-8") as f:
                old = json.load(f)
            db = {a["id"]: a for a in old.get("acts", [])}
            print("Baza existenta: %d acte" % len(db))
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            print("! nu am putut citi baza existenta (%s), pornesc de la zero" % e,
                  file=sys.stderr)

    acts = scrape()
    if not acts:
        print("! scraping fara rezultate — pastrez baza neschimbata", file=sys.stderr)
        if not db:
            sys.exit(1)
        return

    new_ids = []
    for act in acts:
        if act["id"] in db:
            prev = db[act["id"]]
            act = enrich(act, prev.get("first_seen", now_iso))
        else:
            act = enrich(act, now_iso)
            new_ids.append(act["id"])
        db[act["id"]] = act

    # Recalculam scorurile pentru toata baza, nu doar pentru actele proaspete:
    # altfel o ajustare a lexiconului s-ar aplica doar de aici inainte, iar
    # actele mai vechi ar ramane cu scoruri calculate dupa reguli diferite.
    for act in db.values():
        act["categorie"] = classify(act)
        scor, det = score_act(act, act["categorie"])
        act["scor"] = scor
        act["termeni"] = det["keywords"][:5]

    # Retentie: pastram fereastra utila, dupa data publicarii (sau prima vedere).
    cutoff = (now - timedelta(days=RETENTION_DAYS)).date().isoformat()
    kept = {}
    for k, a in db.items():
        ref = a.get("data_publicare") or (a.get("first_seen") or "")[:10]
        if not ref or ref >= cutoff:
            kept[k] = a
    dropped = len(db) - len(kept)
    db = kept

    ordered = sorted(
        db.values(),
        key=lambda a: (a.get("data_publicare") or "0000-00-00",
                       a.get("first_seen") or "",
                       a.get("id")),
        reverse=True,
    )

    cats = {}
    for a in ordered:
        cats[a["categorie"]] = cats.get(a["categorie"], 0) + 1

    out = {
        "generated_at": now_iso,
        "source": SEARCH,
        "total": len(ordered),
        "new_this_run": len(new_ids),
        "pages_scanned": PAGES,
        "categories": cats,
        "acts": ordered,
    }
    fetch_details(ordered, now)

    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = DB_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    os.replace(tmp, DB_PATH)

    print("\n%d acte in baza (%d noi, %d eliminate prin retentie)"
          % (len(ordered), len(new_ids), dropped))
    top = [a for a in ordered if a["scor"] >= 8][:10]
    if top:
        print("\nCele mai relevante acte din aceasta rulare:")
        for a in top:
            print("  [%d] %s — %s" % (a["scor"], a["categorie"], a["titlu"][:90]))


if __name__ == "__main__":
    main()
