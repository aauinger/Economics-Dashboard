#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scope · Risk-Tracker Updater
============================
Erzeugt  data/risk.json  aus den offiziellen Quellen der Unsicherheits-Indizes.
Das Dashboard (Scope) laedt diese Datei zyklisch (gleicher Origin -> kein CORS)
und stellt "Niveau vs. historischer Durchschnitt" dar.

Quellen
-------
  EPU  Global Economic Policy Uncertainty   FRED: GEPUCURRENT         (monatlich)
  WUI  World Uncertainty Index (global)      FRED: WUIGLOBALWEIGHTAVG  (quartalsweise)
  TPU  Trade Policy Uncertainty (Welt)       FRED: EPUTRADE            (monatlich)
  GPR  Geopolitical Risk Index               matteoiacoviello.com      (monatlich)

Alle FRED-Reihen werden ueber den oeffentlichen CSV-Endpunkt geladen
(https://fred.stlouisfed.org/graph/fredgraph.csv?id=...), GPR aus dem
Excel-Export. Hinweis: FRED-Reihen sind public domain (Zitat erwuenscht);
GPR/TPU bitte gemaess den Hinweisen der jeweiligen Seiten zitieren.

Aufruf
------
  python3 update_risk.py            # schreibt ./data/risk.json
Empfohlen einmal pro Monat per cron / Task Scheduler (siehe README-risk.md).

Abhaengigkeiten:  pip install pandas requests openpyxl xlrd
"""

import json, sys, os, tempfile, datetime
import pandas as pd

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
GPR_XLS  = "https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls"

HERE   = os.path.dirname(os.path.abspath(__file__))
OUT    = os.path.join(HERE, "data", "risk.json")

WINDOW = 14          # Anzahl der Punkte fuer Sparkline/Anzeige (juengste zuerst weg)
AVG_FROM = "2000-01" # Basiszeitraum fuer den "historischen Durchschnitt"

# Falls FRED-IDs einmal abweichen, hier zentral anpassen:
FRED_IDS = {
    "EPU": "GEPUCURRENT",
    "WUI": "WUIGLOBALWEIGHTAVG",
    "TPU": "EPUTRADE",
}
NAMES = {
    "EPU": "Economic Policy Uncertainty",
    "WUI": "World Uncertainty Index",
    "TPU": "Trade Policy Uncertainty",
    "GPR": "Geopolitical Risk",
}


def fred_series(sid):
    """FRED-CSV laden -> DataFrame[date, value]."""
    df = pd.read_csv(FRED_CSV.format(sid=sid))
    df.columns = ["date", "value"]
    df = df[df["value"] != "."]
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df.dropna()


def gpr_series():
    """GPR-Excel laden -> DataFrame[date, value] (Spalte 'GPR')."""
    df = pd.read_excel(GPR_XLS)
    date_col = next(c for c in df.columns if str(c).lower() in ("month", "date"))
    val_col  = next(c for c in df.columns if str(c).upper() == "GPR")
    out = df[[date_col, val_col]].copy()
    out.columns = ["date", "value"]
    # 'month' kann YYYYMM (int) oder Datum sein
    out["date"] = pd.to_datetime(out["date"].astype(str).str.replace(r"\.0$", "", regex=True),
                                 format="%Y%m", errors="coerce").fillna(
                  pd.to_datetime(out["date"], errors="coerce"))
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    return out.dropna()


def pack(df, key, unit="index"):
    """DataFrame -> normalisiertes Series-Objekt fuer risk.json."""
    df = df.sort_values("date")
    hist = df.tail(WINDOW)
    base = df[df["date"] >= pd.Timestamp(AVG_FROM)]["value"]
    avg = float(base.mean()) if len(base) else float(df["value"].mean())
    history = [{"t": d.strftime("%Y-%m"), "v": round(float(v), 2)}
               for d, v in zip(hist["date"], hist["value"])]
    return {
        "name": NAMES.get(key, key),
        "unit": unit,
        "asof": history[-1]["t"] if history else "",
        "avg": round(avg, 1),
        "history": history,
    }


def main():
    series = {}

    for key in ("EPU", "WUI", "TPU"):
        try:
            series[key] = pack(fred_series(FRED_IDS[key]), key)
            print(f"  {key:<3} ok  (asof {series[key]['asof']}, avg {series[key]['avg']})")
        except Exception as e:
            print(f"  {key:<3} FEHLER: {e}", file=sys.stderr)

    try:
        series["GPR"] = pack(gpr_series(), "GPR")
        print(f"  GPR ok  (asof {series['GPR']['asof']}, avg {series['GPR']['avg']})")
    except Exception as e:
        print(f"  GPR FEHLER: {e}", file=sys.stderr)

    if not series:
        print("Keine Quelle erreichbar - risk.json bleibt unveraendert.", file=sys.stderr)
        sys.exit(1)

    doc = {
        "meta": {
            "updated": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "FRED (GEPUCURRENT · WUIGLOBALWEIGHTAVG · EPUTRADE) · Caldara–Iacoviello GPR",
        },
        "series": series,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    # atomar schreiben: alte Datei bleibt bei Fehler erhalten (wartungssicher)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(OUT), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OUT)
    print("OK ->", OUT, "(" + ", ".join(series.keys()) + ")")


if __name__ == "__main__":
    main()
