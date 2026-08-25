# Monitor Legislativ — dialog social & economie socială

Dashboard actualizat automat de două ori pe zi cu actele normative publicate în
Monitorul Oficial, preluate din
[Portalul Legislativ](https://legislatie.just.ro/Public/RezultateCautare).

Fiecare act este:

- **catalogat** într-una din 16 categorii tematice (Muncă și dialog social,
  Economie socială, Protecție socială și pensii, Sănătate, Fiscalitate etc.);
- **punctat de la 1 la 10** după relevanța pentru dialogul social și economia socială,
  pe o scară de culoare rece → cald (albastru = irelevant, roșu = impact direct);
- afișat cu data publicării, data intrării în vigoare, emitentul, titlul și o
  descriere scurtă;
- **citibil integral în aplicație**, fără să fie nevoie de un drum pe portal.

## Cum funcționează scorul

Scorul combină patru semnale, calculate pe titlul și descrierea actului:

| Semnal | Exemple | Pondere |
|---|---|---|
| Termeni de bază (Tier A) | dialog social, contract colectiv de muncă, sindicat, patronat, grevă, Codul muncii, economie socială, întreprindere socială, salariul minim | 4–6 |
| Sfera muncii și protecției sociale (Tier B) | salarizare, șomaj, pensii, asigurări sociale, formare profesională, telemuncă | 2–3 |
| Context social larg (Tier C) | dizabilitate, egalitate de șanse, incluziune, sănătate, educație | 1–2 |
| Emitent | Ministerul Muncii, Consiliul Economic și Social, CNPP, ANOFM, Inspecția Muncii | 1–6 |
| Forța juridică | lege și OUG cântăresc mai mult decât un ordin | −2…+4 |

Din total se scad **penalizări de zgomot** pentru actele fără conținut normativ
substanțial (exproprieri, numiri și eliberări din funcție, actualizări de
inventar, erate, curs de schimb).

Un act care conține un termen de bază puternic urcă automat în jumătatea
superioară a scalei (8–10); restul se așază după punctajul brut acumulat:
`8` ≥ 12 · `7` ≥ 10 · `6` ≥ 8 · `5` ≥ 6 · `4` ≥ 4 · `3` ≥ 2 · `2` ≥ 1 · `1` restul.

Două detalii de implementare contează pentru acuratețe:

- **Potrivire pe rădăcina cuvântului.** Româna articulează și declină substantivele
  („economie” → „economia”, „consiliul” → „consiliului”), așa că o potrivire exactă
  ar pierde majoritatea aparițiilor reale.
- **Numărare pe concept.** Fiindcă rădăcinile colapsează variantele, „salariu”,
  „salarii”, „salariați” și „salarizare” se potrivesc pe același cuvânt din text.
  Cheile echivalente sunt grupate automat și numărate o singură dată.

Scorul este un **instrument de triere, nu o evaluare juridică**.

## Textul actului și modificările

Pentru actele cu scor ≥ 4, dashboard-ul descarcă și textul integral, care se
deschide direct în aplicație. Modificările sunt evidențiate astfel:

| Culoare | Înseamnă |
|---|---|
| 🟦 albastru | act complet nou — toate dispozițiile sunt text nou |
| 🟩 verde | text adăugat sau forma nouă instalată de act |
| 🟥 roșu tăiat | dispoziții și acte abrogate |

Sub titlu apare tabelul **acțiunilor induse** preluat de la portal: ce articol al
actului curent modifică, completează sau abrogă ce anume, cu link către actul vizat.

**O limitare de care merită să știi:** portalul publică doar forma *consolidată* a
actelor, fără istoric de versiuni. Când un act spune „Punctul 3 se modifică și va
avea următorul cuprins:", textul **nou** e disponibil, dar forma **dinaintea**
modificării nu mai există nicăieri pe portal. De aceea evidențiem ce se adaugă și
ce se abrogă — dar nu afișăm un diff cuvânt-cu-cuvânt între vechi și nou, fiindcă
partea „ștearsă" ar trebui ghicită, iar un diff inventat induce în eroare mai rău
decât absența lui.

## Actualizare automată

Colectarea rulează **local**, la **08:00** și **16:00** ora României, prin
`scripts/run-update.sh`; publicarea pe GitHub Pages se face automat la fiecare
push, prin `.github/workflows/deploy.yml`.

> **De ce nu rulează colectarea pe GitHub Actions?**
> Portalul `legislatie.just.ro` refuză conexiunile venite din centre de date.
> De pe un runner GitHub, DNS-ul rezolvă și handshake-ul TLS reușește, dar
> serverul închide conexiunea fără să trimită vreun răspuns (curl iese cu 92 la
> HTTP/2 și 52 la HTTP/1.1, identic pentru Python). De pe o conexiune din
> România totul funcționează normal, așa că partea de colectare stă pe mașina
> locală, iar GitHub se ocupă doar de publicare.

Fiecare rulare scanează primele 6 pagini de rezultate (300 de acte), le adaugă în
`data/acts.json` (bază cumulativă, cheia = id-ul documentului de pe portal),
recalculează scorurile pentru toate actele, descarcă textul integral pentru cel
mult 40 de acte relevante noi și redeployează site-ul.

Textul integral se păstrează doar pentru actele cu scor ≥ 4 și doar 180 de zile:
la ~16 KB per act, arhivarea întregului Monitor Oficial ar depăși 350 MB pe an.

## Rulare locală

```bash
python3 scripts/scrape.py          # PAGES=4 implicit
python3 -m http.server 8801        # apoi deschide http://localhost:8801
```

```bash
python3 scripts/detail.py 313622     # textul unui singur act, pentru depanare
```

Variabile de mediu: `PAGES` (pagini de câte 50 scanate, implicit 4),
`RETENTION_DAYS` (fereastra bazei, implicit 365), `DETAIL_MIN_SCORE` (scorul de
la care se descarcă textul integral, implicit 4), `DETAIL_RETENTION_DAYS`
(implicit 180), `MAX_DETAILS` (acte cu text descărcate pe rulare, implicit 40).

## Ajustarea lexiconului

Toată logica de clasificare și scorare stă în `scripts/lexicon.py`. Pentru a
schimba ce contează ca relevant, editează dicționarele de acolo — gruparea pe
concepte și potrivirea pe rădăcină se aplică automat cheilor noi. Scrie cheile
**fără diacritice și cu litere mici**; textul este normalizat înainte de potrivire.

## Structură

```
index.html            dashboard (tabel, filtre, sortare, vizualizator, export CSV)
data/acts.json        baza cumulativă de acte (index)
data/acts/<id>.json   textul integral + operațiunile, încărcat la cerere
scripts/scrape.py     colectare, parsare, clasificare, scorare
scripts/detail.py     textul integral și marcarea modificărilor
scripts/lexicon.py    termenii și ponderile — aici se fac ajustările
```

Sursa oficială rămâne [legislatie.just.ro](https://legislatie.just.ro).
