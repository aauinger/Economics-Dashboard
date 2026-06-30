#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scope · Korrelations-Updater
============================
Erzeugt  data/correlation.json  fuer das Modul "Korrelation".

Reihen:
  10-Jahres-US-Treasury-Rendite  ->  FRED  GS10              (monatlich, ab 1953)
  S&P 500 (Monatswerte)          ->  Shiller ie_data.xls     (ab 1871, PRIMAER)
                                       Fallback: Yahoo v8 chart (^GSPC, 30J)
                                       oder eigene CSV via --spx

Das Dashboard liest die rohen Monatsreihen (dates / spx / y10 / window) und rechnet
daraus selbst die rollierende Korrelation der S&P-Returns mit der Veraenderung (Delta)
der Rendite. Standardfenster: 36 Monate (= 3 Jahre, wie im Muster).

Quellen-Strategie (unbeaufsichtigter Job): Shiller ist autoritativ + lange Historie,
liegt aber als .xls vor. Faellt das Parsen/der Abruf aus, wird automatisch Yahoo
(JSON) genutzt. Nur wenn BEIDE scheitern, bleibt die alte correlation.json erhalten.

Aufruf:
  python update_correlation.py                  # Shiller -> sonst Yahoo
  python update_correlation.py --spx sp500.csv  # S&P aus eigener CSV (Spalten: date,close)
  python update_correlation.py --window 12      # 12-Monats-Fenster
  python update_correlation.py --since 1999-01  # Startmonat begrenzen

Abhaengigkeiten:  pip install pandas requests openpyxl xlrd
Empfohlen: einmal pro Monat (cron / Task Scheduler / GitHub Action).
"""

import argparse, json, os, sys, re, tempfile, datetime
import pandas as pd
import requests

FRED_CSV    = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
SHILLER_XLS = "http://www.econ.yale.edu/~shiller/data/ie_data.xls"
YAHOO       = "https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?range=30y&interval=1mo"
UA = {"User-Agent": "Mozilla/5.0 (Scope-Dashboard data updater)"}

HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(HERE, "data", "correlation.json")


# ---------- reine Hilfsfunktionen (ohne Netz, leicht testbar) ----------
def parse_shiller_date(x):
    """Shiller-Datum -> 'YYYY-MM'. Achtung: 1871.1 bedeutet Oktober (nicht Jaenner),
    weil Excel die Null bei .10 abschneidet."""
    f = float(x)
    year = int(f)
    month = int(round((f - year) * 100))
    if month <= 0:
        month = 1
    if month > 12:
        month = 12
    return "%04d-%02d" % (year, month)


def to_month(s):
    """Beliebiges Datum (Text) -> 'YYYY-MM'."""
    s = str(s).strip()
    m = re.match(r"(\d{4})[-/.](\d{1,2})", s)
    if m:
        return "%04d-%02d" % (int(m.group(1)), int(m.group(2)))
    d = pd.to_datetime(s, errors="coerce")
    return None if pd.isna(d) else d.strftime("%Y-%m")


def align(spx, y10, since=None):
    """Gemeinsame Monate -> (dates, spx_vals, y10_vals), chronologisch."""
    months = sorted(set(spx) & set(y10))
    if since:
        months = [m for m in months if m >= since]
    return months, [round(float(spx[m]), 2) for m in months], [round(float(y10[m]), 2) for m in months]


# ---------- Datenquellen (Netz) ----------
def fred_monthly(sid):
    df = pd.read_csv(FRED_CSV.format(sid=sid))
    df.columns = ["date", "value"]
    df = df[df["value"] != "."]
    out = {}
    for d, v in zip(df["date"], df["value"]):
        mm = to_month(d)
        if mm:
            out[mm] = float(v)
    return out


def shiller_spx():
    """S&P-500-Monatspreis (Spalte 'P') aus Shillers ie_data.xls."""
    raw = pd.read_excel(SHILLER_XLS, sheet_name="Data", header=None)
    hdr = None
    for i in range(min(15, len(raw))):
        row = [str(c).strip() for c in raw.iloc[i].tolist()]
        if "Date" in row and "P" in row:
            hdr = i
            break
    if hdr is None:
        raise RuntimeError("Shiller-Kopfzeile (Date/P) nicht gefunden")
    cols = [str(c).strip() for c in raw.iloc[hdr].tolist()]
    di, pi = cols.index("Date"), cols.index("P")
    out = {}
    for _, r in raw.iloc[hdr + 1:].iterrows():
        dv, pv = r.iloc[di], r.iloc[pi]
        if pd.isna(dv) or pd.isna(pv):
            continue
        try:
            out[parse_shiller_date(dv)] = float(pv)
        except Exception:
            continue
    if len(out) < 200:
        raise RuntimeError("Shiller lieferte zu wenige Punkte (%d)" % len(out))
    return out


def yahoo_spx():
    """Fallback: S&P-500-Monatsschlusskurse aus Yahoo v8 chart (^GSPC)."""
    r = requests.get(YAHOO, headers=UA, timeout=30)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    out = {}
    for t, c in zip(ts, closes):
        if c is None:
            continue
        out[datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m")] = float(c)
    if len(out) < 60:
        raise RuntimeError("Yahoo lieferte zu wenige Punkte (%d)" % len(out))
    return out


def csv_spx(path):
    """Eigene S&P-CSV mit Spalten date,close (oder erste zwei Spalten)."""
    df = pd.read_csv(path)
    cols = list(df.columns)
    dcol = next((c for c in cols if str(c).lower() in ("date", "datum", "month")), cols[0])
    vcol = next((c for c in cols if str(c).lower() in ("close", "price", "value", "spx", "sp500", "p")), cols[1])
    out = {}
    for d, v in zip(df[dcol], df[vcol]):
        mm = to_month(d)
        if mm and pd.notna(v):
            out[mm] = float(v)
    return out


def load_spx(custom_csv):
    """S&P-Quelle mit Fallback-Kette: CSV -> Shiller -> Yahoo."""
    if custom_csv:
        return csv_spx(custom_csv), "eigene CSV"
    try:
        return shiller_spx(), "Shiller"
    except Exception as e:
        print("  Shiller fehlgeschlagen (%s) -> Fallback Yahoo" % e, file=sys.stderr)
        return yahoo_spx(), "Yahoo"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spx", help="Pfad zu eigener S&P-CSV (date,close); sonst Shiller/Yahoo")
    ap.add_argument("--window", type=int, default=36, help="Rolling-Fenster in Monaten (Default 36)")
    ap.add_argument("--since", default="1996-01", help="Startmonat YYYY-MM (Default 1996-01)")
    args = ap.parse_args()

    try:
        y10 = fred_monthly("GS10")
        print("  GS10 ok  (%d Monate)" % len(y10))
    except Exception as e:
        print("  GS10 FEHLER:", e, file=sys.stderr); sys.exit(1)

    try:
        spx, src = load_spx(args.spx)
        print("  S&P 500 ok  (%d Monate, Quelle: %s)" % (len(spx), src))
    except Exception as e:
        print("  S&P 500 FEHLER (alle Quellen):", e, file=sys.stderr); sys.exit(1)

    dates, spx_s, y10_s = align(spx, y10, since=args.since)
    if len(dates) < args.window + 2:
        print("  Zu wenige gemeinsame Monate (%d)." % len(dates), file=sys.stderr); sys.exit(1)

    doc = {
        "meta": {
            "asof": dates[-1],
            "updated": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "FRED GS10 (US 10y) + %s (S&P 500) · %dM rolling corr" % (src, args.window),
        },
        "window": args.window,
        "dates": dates,
        "spx": spx_s,
        "y10": y10_s,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(OUT), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OUT)
    print("OK ->", OUT, "(%d Monate %s..%s, Fenster %d, %s)" % (len(dates), dates[0], dates[-1], args.window, src))


if __name__ == "__main__":
    main()
