#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scope · Global-Outlook Updater
==============================
Erzeugt  data/global.json  fuer das "Global"-Panel des Dashboards.

Live-Quelle:  IMF DataMapper API (World Economic Outlook)
  - Welt-BIP-Wachstum   NGDP_RPCH / WEOWORLD   (real GDP growth, % p.a.)
  - Welt-Inflation       PCPIPCH  / WEOWORLD   (avg consumer prices, % p.a.)

Hinweis zur API: Die Pfad-Filterung der DataMapper-API (.../NGDP_RPCH/WEOWORLD)
ist unzuverlaessig (liefert teils falsche Entitaeten). Wir holen daher den
vollstaendigen Indikator-Dump (.../NGDP_RPCH) und greifen den Schluessel
"WEOWORLD" selbst heraus.

OECD / World Bank (GEP) / UN (WESP) veroeffentlichen ihre Welt-Wachstums-
prognosen NICHT ueber eine stabile API. Diese drei Werte sind daher unten als
gepflegte Konstanten hinterlegt und ~2x/Jahr (nach den jeweiligen Releases)
manuell zu aktualisieren -> siehe CURATED.

Aufruf:  python update_global.py        # schreibt ./data/global.json
"""

import json, os, sys, tempfile, datetime
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(HERE, "data", "global.json")

IMF = "https://www.imf.org/external/datamapper/api/v1/{ind}"

# --- Manuell gepflegt: OECD / World Bank / UN (nach jedem Release pruefen) ----
# v = Welt-BIP-Wachstum (%), note = Reportname, url = Quelle
CURATED = [
    {"key": "OECD", "v": 3.0, "note": "Economic Outlook",
     "url": "https://www.oecd.org/en/publications/oecd-economic-outlook-volume-2026-issue-1_2d1956f0-en.html"},
    {"key": "WB",   "v": 2.7, "note": "Global Economic Prospects",
     "url": "https://openknowledge.worldbank.org/server/api/core/bitstreams/d01f39ea-732b-4816-92ac-d6c26205dda9/content"},
    {"key": "UN",   "v": 2.9, "note": "WESP",
     "url": "https://desapublications.un.org/publications/world-economic-situation-and-prospects-mid-2026"},
]
IMF_URL = "https://www.imf.org/en/publications/weo"


def imf_world(indicator):
    """Vollen Indikator-Dump holen und WEOWORLD (Jahr->Wert) zurueckgeben."""
    r = requests.get(IMF.format(ind=indicator), timeout=30)
    r.raise_for_status()
    return r.json()["values"][indicator]["WEOWORLD"]


def pick_year(series):
    """Aktuelles Kalenderjahr bevorzugen, sonst naechstgelegenes verfuegbares."""
    cur = datetime.datetime.utcnow().year
    if str(cur) in series:
        return cur
    past = [int(y) for y in series if int(y) <= cur]
    if past:
        return max(past)
    return max(int(y) for y in series)


def main():
    try:
        growth = imf_world("NGDP_RPCH")
        infl   = imf_world("PCPIPCH")
    except Exception as e:
        print(f"IMF-Quelle nicht erreichbar: {e}", file=sys.stderr)
        print("global.json bleibt unveraendert.", file=sys.stderr)
        sys.exit(1)

    yr = pick_year(growth)
    bip = round(float(growth[str(yr)]), 1)
    cpi = round(float(infl[str(yr)]), 1) if str(yr) in infl else round(float(infl[max(infl)]), 1)

    bigfour = [{"key": "IMF", "v": bip, "note": "World Economic Outlook", "url": IMF_URL}] + CURATED

    doc = {
        "meta": {
            "asof": str(yr),
            "updated": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "IMF WEO · OECD · World Bank · UN (DESA)",
        },
        "bip": bip,
        "infl": cpi,
        "bigfour": bigfour,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(OUT), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OUT)
    print(f"OK -> {OUT}  (IMF {yr}: bip {bip} %, infl {cpi} %)")


if __name__ == "__main__":
    main()
