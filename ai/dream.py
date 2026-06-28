#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# dream.py — ultra-robust merge (trades / alerts / patterns / features)
# v1.5 NO-KEYERROR + SMART-TIME-PARSER

from __future__ import annotations
import argparse
from pathlib import Path
import pandas as pd
import numpy as np
import hashlib

VERSION = "dream.py v1.5 (NO-KEYERROR + SMART-TIME-PARSER)"

# ====== KONSTANTY ======
TIME_CANDIDATES = [
    # obecné
    "merged_time","timestamp","time","ts","ts_iso","datetime","date",
    # naše logy
    "sent_at","created_at","opened_at","closed_at","event_time",
    "utc_open","utc_close","open_time","close_time","entry_time","exit_time",
]
SYMBOL_CANDIDATES = ("symbol","Symbol","SYMBOL","pair","Pair","PAIR")

# ====== IO SAFE ======
def read_csv_safe(path: Path) -> pd.DataFrame:
    if not path.exists():
        print(f"[WARN] {path} neexistuje")
        return pd.DataFrame()
    try:
        df = pd.read_csv(path)
        if df.empty:
            print(f"[WARN] {path} je prázdný")
        return df
    except Exception as e:
        print(f"[ERR] čtení {path} selhalo: {e}")
        return pd.DataFrame()

# ====== DATETIME HELPERS ======
def _try_parse_series(s: pd.Series) -> pd.Series:
    try:
        return pd.to_datetime(s, errors="coerce", utc=True)
    except Exception:
        return pd.to_datetime(pd.Series([pd.NaT]*len(s)), errors="coerce", utc=True)

def _parse_epoch_series(s: pd.Series) -> pd.Series:
    """Epoch sekundy i milisekundy → UTC; jinak NaT."""
    try:
        s_num = pd.to_numeric(s, errors="coerce")
        s_dt = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns, UTC]")
        ms_mask  = s_num > 1_000_000_000_000  # ms
        sec_mask = (s_num > 1_000_000_000) & ~ms_mask  # s
        if ms_mask.any():
            s_dt.loc[ms_mask]  = pd.to_datetime(s_num[ms_mask],  unit="ms", utc=True)
        if sec_mask.any():
            s_dt.loc[sec_mask] = pd.to_datetime(s_num[sec_mask], unit="s",  utc=True)
        return s_dt
    except Exception:
        return pd.to_datetime(pd.Series([pd.NaT]*len(s)), errors="coerce", utc=True)

COMMON_DT_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
]

def _parse_with_common_formats(s: pd.Series) -> pd.Series:
    for fmt in COMMON_DT_FORMATS:
        dt = pd.to_datetime(s, format=fmt, errors="coerce", utc=True)
        if dt.notna().any():
            return dt
    # poslední pokus: dayfirst=True
    return pd.to_datetime(s, errors="coerce", utc=True, dayfirst=True)

def coerce_time_col(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    # 1) známé kandidáty
    for c in TIME_CANDIDATES:
        if c in df.columns:
            dt = _try_parse_series(df[c])
            if dt.notna().any():
                df["merged_time"] = dt
                return df
    # 2) autodetekce
    for c in df.columns:
        dt = _try_parse_series(df[c])
        if dt.notna().sum() >= max(3, int(0.05*len(dt))):
            df["merged_time"] = dt
            return df
    # 3) fallback
    df["merged_time"] = pd.NaT
    return df

def _extract_symbol(df: pd.DataFrame, default=pd.NA) -> pd.Series:
    for cand in SYMBOL_CANDIDATES:
        if cand in df.columns:
            return df[cand]
    return pd.Series([default]*len(df))

# ====== PREP TABLES ======
def prepare_trades(tr: pd.DataFrame) -> pd.DataFrame:
    """Sjednotí 'symbol' a vyrobí 'merged_time' z close/open/aliasů (ISO, epoch s/ms, CZ formáty)."""
    if tr.empty:
        return tr
    tr = tr.copy()

    # symbol aliasy
    if "symbol" not in tr.columns:
        tr["symbol"] = _extract_symbol(tr, default=pd.NA)

    # zdroj času (priorita close)
    time_cols = [
        "ts_close","utc_close","closed_at","close_time","exit_time",
        "ts_open","utc_open","opened_at","open_time","entry_time",
        "timestamp","datetime","time","ts","ts_iso",
    ]
    source_col = next((c for c in time_cols if c in tr.columns), None)

    if source_col:
        s = tr[source_col]
        # 1) ISO/standard
        dt = pd.to_datetime(s, errors="coerce", utc=True)
        # 2) epoch s/ms
        if dt.notna().sum() == 0:
            dt = _parse_epoch_series(s)
        # 3) common CZ/EU formáty
        if dt.notna().sum() == 0 and s.dtype == object:
            dt = _parse_with_common_formats(s)
        tr["merged_time"] = dt
    else:
        tr = coerce_time_col(tr)

    if "merged_time" not in tr.columns:
        tr["merged_time"] = pd.NaT

    # diagnostika
    has_symbol = tr["symbol"].notna().sum()
    has_time   = tr["merged_time"].notna().sum()
    print(f"[DEBUG] trades rows in: {len(tr)}, has_symbol: {has_symbol}, has_time: {has_time}")

    # filtr přes masku (žádné dropna(subset=...))
    m = tr["symbol"].notna() & tr["merged_time"].notna()
    print(f"[DEBUG] trades valid after filter: {int(m.sum())}")
    return tr.loc[m].copy()

def prepare_generic(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    if "symbol" not in df.columns:
        df["symbol"] = _extract_symbol(df, default=pd.NA)
    df = coerce_time_col(df)
    if "merged_time" not in df.columns:
        df["merged_time"] = pd.NaT
    m = df["symbol"].notna() & df["merged_time"].notna()
    return df.loc[m].copy()

# ====== SAFE MERGE ======
def asof_merge(left: pd.DataFrame, right: pd.DataFrame, label: str, tol="90s") -> pd.DataFrame:
    """Bezpečný merge_asof — nikdy KeyError, nikdy pád."""
    if right is None or right.empty:
        print(f"[WARN] {label}: prázdná tabulka → přeskočeno")
        return left

    # zajisti klíče (bez dropna)
    if "merged_time" not in right.columns:
        print(f"[FIX] {label}: chyběl 'merged_time' → doplněn NaT")
        right = right.copy(); right["merged_time"] = pd.NaT
    if "symbol" not in right.columns:
        print(f"[FIX] {label}: chyběl 'symbol' → doplněn NaN")
        right = right.copy(); right["symbol"] = np.nan
    if "merged_time" not in left.columns:
        print(f"[FIX] left: chyběl 'merged_time' → doplněn NaT")
        left = left.copy(); left["merged_time"] = pd.NaT
    if "symbol" not in left.columns:
        print(f"[FIX] left: chyběl 'symbol' → doplněn NaN")
        left = left.copy(); left["symbol"] = np.nan

    # masky místo dropna
    r2 = right[(right["merged_time"].notna()) & (right["symbol"].notna())].copy()
    if r2.empty:
        print(f"[WARN] {label}: po filtraci prázdné → přeskočeno")
        return left
    l2 = left[(left["merged_time"].notna()) & (left["symbol"].notna())].copy()
    if l2.empty:
        print(f"[WARN] left: po filtraci prázdné → nemerguji {label}")
        return left

    r2 = r2.sort_values("merged_time")
    l2 = l2.sort_values("merged_time")

    try:
        out = pd.merge_asof(
            l2, r2,
            on="merged_time", by="symbol",
            direction="nearest", tolerance=pd.Timedelta(tol)
        )
    except Exception as e:
        print(f"[WARN] merge_asof({label}) selhalo: {e} → ponechávám left beze změny")
        return left

    # kolize názvů z pravé tabulky
    rename_map = {}
    for c in r2.columns:
        if c not in ("merged_time","symbol") and c in out.columns:
            rename_map[c] = f"{c}_{label}"
    if rename_map:
        out = out.rename(columns=rename_map)
    return out

# ====== PIPELINE ======
def merge_logs(data: dict[str, pd.DataFrame], debug: bool=False) -> pd.DataFrame:
    trades   = prepare_trades(data.get("trades",   pd.DataFrame()))
    alerts   = prepare_generic(data.get("alerts",   pd.DataFrame()))
    patterns = prepare_generic(data.get("patterns", pd.DataFrame()))
    feats    = prepare_generic(data.get("features", pd.DataFrame()))

    if trades.empty:
        print("[WARN] trades.csv prázdné/bez použitelných řádků")
        return pd.DataFrame()

    # extra fail-safe pro alerts (když by po prepare neměly merged_time)
    if not alerts.empty and "merged_time" not in alerts.columns:
        for c in ["sent_at","created_at","timestamp","datetime","time","ts","ts_iso","opened_at","closed_at"]:
            if c in alerts.columns:
                alerts = alerts.copy()
                alerts["merged_time"] = pd.to_datetime(alerts[c], errors="coerce", utc=True)
                print(f"[FIX] alerts: merged_time vytvořen ze '{c}'")
                break

    if debug:
        for name, df in [("trades", trades), ("alerts", alerts), ("patterns", patterns), ("features", feats)]:
            print(f"[DEBUG] {name}: len={len(df)}, has_time={'merged_time' in df.columns}, cols={list(df.columns)[:12]}")

    merged = trades.copy()
    merged = asof_merge(merged, alerts,   "alerts")
    merged = asof_merge(merged, patterns, "patterns")
    merged = asof_merge(merged, feats,    "features")

    merged = merged.sort_values("merged_time").reset_index(drop=True)
    if debug:
        print(f"[DEBUG] Výsledných řádků po merge: {len(merged)}")
    return merged

# ====== SAVE ======
def save_output(df: pd.DataFrame, out_path: Path, csv_path: Path | None, head: int):
    if df.empty:
        print("[WARN] výstup je prázdný")
    else:
        try:
            df.to_parquet(out_path, index=False)
            print(f"[saved] parquet: {out_path} rows={len(df)}")
        except Exception as e:
            print(f"[WARN] Parquet selhal ({e}) – ukládám jen CSV")
        if csv_path:
            try:
                df.to_csv(csv_path, index=False)
                print(f"[saved] csv: {csv_path} rows={len(df)}")
            except Exception as e:
                print(f"[ERR] Uložení CSV selhalo: {e}")
    if head > 0:
        print(df.head(head))

# ====== MAIN ======
def main():
    ap = argparse.ArgumentParser(description="Merge trades/alerts/patterns/features podle času+symbolu (ultra-robust).")
    ap.add_argument("--logs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--csv")
    ap.add_argument("--head", type=int, default=10)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    here = Path(__file__).resolve()
    sha = hashlib.md5(here.read_bytes()).hexdigest()[:8]
    print(f"[BOOT] {VERSION} | file={here} | md5={sha}")

    p = Path(args.logs)
    data = {
        "trades":   read_csv_safe(p / "trades.csv"),
        "alerts":   read_csv_safe(p / "alerts.csv"),
        "patterns": read_csv_safe(p / "pattern_events.csv"),
        "features": read_csv_safe(p / "feature_events.csv"),
    }

    df = merge_logs(data, debug=args.debug)
    save_output(df, Path(args.out), Path(args.csv) if args.csv else None, args.head)

if __name__ == "__main__":
    main()
