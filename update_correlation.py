#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scope · Korrelations-Updater
============================
Erzeugt  data/correlation.json  fuer das "Korrelation"-Panel.

Das Dashboard rechnet die rollierende 36-Monats-Korrelation selbst
(Aktien-Monatsrendite vs. Veraenderung der 10J-Rendite). Dieser Updater
liefert nur die beiden ROHEN Monatsreihen, ausgerichtet nach Monat:

  spx  S&P 500 Monatsschlusskurse   Yahoo Finance v8 chart (^GSPC)
  y10  US-10J-Treasury-Rendite      FRED: GS10  (monatlich, % p.a.)

Schema (vom Dashboard akzeptiert, siehe refreshCorr):
  { "meta": {...}, "window": 36, "dates": ["YYYY-MM", ...],
    "spx": [num, ...], "y10": [num, ...] }   (alle Arrays gleich lang)

Hinweis: Der Yahoo-CSV-Download (v7) erfordert Cookie/Crumb; der hier
genutzte v8-chart-JSON-Endpunkt funktioniert ohne Auth (User-Agent noetig).

Aufruf:  python update_correlation.py     # schreibt ./data/correlation.json
"""

import json, os, sys, tempfile, datetime
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(HERE, "data", "correlation.json")

WINDOW   = 36
YAHOO    = "https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?range=30y&interval=1mo"
FRED_GS10 = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=GS10"
UA = {"User-Agent": "Mozilla/5.0 (Scope-Dashboard data updater)"}


def spx_monthly():
    """{YYYY-MM: close} aus Yahoo v8 chart (^GSPC, monatlich)."""
    r = requests.get(YAHOO, headers=UA, timeout=30)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    out = {}
    for t, c in zip(ts, closes):
        if c is None:
            continue
        ym = datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m")
        out[ym] = round(float(c), 2)   # letzter Eintrag pro Monat gewinnt
    return out


def y10_monthly():
    """{YYYY-MM: yield} aus FRED GS10 (CSV)."""
    r = requests.get(FRED_GS10, timeout=30)
    r.raise_for_status()
    out = {}
    for line in r.text.splitlines()[1:]:
        date, _, val = line.partition(",")
        if not val or val == ".":
            continue
        out[date[:7]] = round(float(val), 2)
    return out


def main():
    try:
        spx = spx_monthly()
        y10 = y10_monthly()
    except Exception as e:
        print(f"Quelle nicht erreichbar: {e}", file=sys.stderr)
        print("correlation.json bleibt unveraendert.", file=sys.stderr)
        sys.exit(1)

    months = sorted(m for m in spx if m in y10)   # nur Monate mit BEIDEN Reihen
    if len(months) < WINDOW + 2:
        print(f"Zu wenige gemeinsame Monate ({len(months)}).", file=sys.stderr)
        sys.exit(1)

    doc = {
        "meta": {
            "asof": months[-1],
            "updated": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "S&P 500 (Yahoo Finance) · US 10Y (FRED GS10) · 36M rolling corr",
        },
        "window": WINDOW,
        "dates": months,
        "spx": [spx[m] for m in months],
        "y10": [y10[m] for m in months],
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(OUT), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OUT)
    print(f"OK -> {OUT}  ({months[0]} .. {months[-1]}, {len(months)} Monate)")


if __name__ == "__main__":
    main()
