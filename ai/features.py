# ai/features.py
from __future__ import annotations
import os
from typing import Dict, List, Tuple
import pandas as pd
import numpy as np

# ===== Public schema (ke modelu) =====
FEATURE_COLUMNS: List[str] = [
    "adx_patterns",
    "adx_alerts",
    "atr_patterns",
    "rsi_patterns",
    "fvg_present_patterns",
    "htf_trend_alerts",
    "near_sr_alerts",
    "session_patterns",
]

# ===== Env / constants =====
TRADING_TZ = os.getenv("TRADING_TZ", "Europe/Prague")
ADX_STRONG = float(os.getenv("ADX_STRONG", "22"))
ADX_MIN    = float(os.getenv("ADX_MIN", "16"))
RSI_LO     = float(os.getenv("RSI_LO", "39"))
RSI_HI     = float(os.getenv("RSI_HI", "61"))
SR_MAX_DIST_ATR = float(os.getenv("SR_MAX_DIST_ATR", "0.75"))

FEATURE_EVENTS_CSV = os.getenv("FEATURE_EVENTS_CSV", "logs/feature_events.csv")

# ===== Utilities =====
def _pip_size(sym: str) -> float:
    s = sym.replace("/", "").upper()
    return 0.01 if s.endswith("JPY") else 1e-4

def _safe_series(x, default=np.nan):
    try:    return float(x)
    except: return float(default)

def _new_bar_ts(df: pd.DataFrame) -> pd.Timestamp:
    ts = df.iloc[-1].get("datetime")
    ts = pd.to_datetime(ts, utc=True, errors="coerce")
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts

def _tz(ts: pd.Timestamp) -> pd.Timestamp:
    try:
        return ts.tz_convert(TRADING_TZ)
    except Exception:
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.tz_convert(TRADING_TZ)

def _session_bucket(ts_local: pd.Timestamp) -> int:
    h = ts_local.hour
    # 0: Asia pre-London 00–07, 1: London 08–12, 2: NY open 13–17, 3: NY late 18–22, 4: off 23
    if 8 <= h <= 12:   return 1
    if 13 <= h <= 17:  return 2
    if 18 <= h <= 22:  return 3
    if h == 23:        return 4
    return 0

def _fvg_side(a: pd.Series, b: pd.Series, c: pd.Series) -> int:
    # bull=+1, bear=-1, none=0
    try:
        if (b["low"] > a["high"]) and (c["high"] > b["low"]):
            return +1
        if (b["high"] < a["low"]) and (c["low"]  < b["high"]):
            return -1
    except Exception:
        pass
    return 0

def _near_sr(last: pd.Series, side: str) -> int:
    atr = _safe_series(last.get("atr"))
    if not (atr > 0): return 0
    close = _safe_series(last.get("close"))
    sup   = _safe_series(last.get("low"),  close)
    res   = _safe_series(last.get("high"), close)
    lim = SR_MAX_DIST_ATR * atr
    if side == "long":
        return 1 if (close - sup) <= lim else 0
    else:
        return 1 if (res - close) <= lim else 0

# ===== Core feature extractor =====
def extract_last_features(df_ind: pd.DataFrame, *, symbol: str = "EURUSD", tf: str = "M5") -> Dict[str, float]:
    """
    Očekává DF s kolonami: datetime, open, high, low, close, rsi, adx, atr, ema50, ema200 (viz add_indicators).
    Vrací dict přesně v pořadí FEATURE_COLUMNS (číselné hodnoty).
    """
    if df_ind is None or len(df_ind) < 20:
        # minimální fallback, ať scorer nespadne
        return {k: 0.0 for k in FEATURE_COLUMNS}

    last = df_ind.iloc[-1]
    ts_local = _tz(_new_bar_ts(df_ind))

    # --- ADX patterny / alerts ---
    adx = df_ind["adx"].tail(10).astype(float).values
    adx_now = float(adx[-1])
    adx_slope = float(adx[-1] - adx[-2]) if len(adx) >= 2 else 0.0
    adx_rising = int(adx_slope > 0)
    adx_strong = int(adx_now >= ADX_STRONG)
    adx_above_min_count = int((adx >= ADX_MIN).sum())
    adx_patterns = adx_rising + adx_strong  # 0–2
    adx_alerts   = min(10, adx_above_min_count)  # 0–10 (posledních 10 barů)

    # --- ATR / chop-trend ---
    atr = df_ind["atr"].astype(float)
    if len(atr) < 15:
        atr_patterns = 0.0
    else:
        rng = float(df_ind["high"].tail(15).max() - df_ind["low"].tail(15).min())
        atr_now = float(atr.iloc[-1] or 1e-9)
        rar = rng / atr_now if atr_now > 0 else 0.0
        # „trend-like“ když range je rozumná vs. ATR a ADX stoupá
        atr_patterns = float((rar <= 0.85) + (adx_slope > 0))  # 0–2

    # --- RSI patterny ---
    rsi = df_ind["rsi"].astype(float).values
    rsi_now = float(rsi[-1])
    rsi_hits = int(((rsi <= RSI_LO) | (rsi >= RSI_HI))[-5:].sum())  # posledních 5 barů zabodovalo?
    rsi_edge_now = int((rsi_now <= RSI_LO) or (rsi_now >= RSI_HI))
    rsi_patterns = float(min(5, rsi_hits) + rsi_edge_now)  # 0–6

    # --- FVG (3-svíčková) ---
    fvg_flag = 0
    if len(df_ind) >= 3:
        a, b, c = df_ind.iloc[-3], df_ind.iloc[-2], df_ind.iloc[-1]
        fvg_flag = _fvg_side(a, b, c)  # -1/0/+1
    fvg_present_patterns = float(fvg_flag != 0)

    # --- „HTF trend alerts“ (proxy z LTF: ema50 vs ema200 + cena vs ema50) ---
    ema50 = _safe_series(last.get("ema50"))
    ema200= _safe_series(last.get("ema200"))
    close = _safe_series(last.get("close"))
    trend_up = (ema50 > ema200) and (close > ema50)
    trend_down = (ema50 < ema200) and (close < ema50)
    htf_trend_alerts = float(trend_up or trend_down)

    # --- Near SR (pro obě strany posuzujeme symetricky a bereme max) ---
    near_long  = _near_sr(last, "long")
    near_short = _near_sr(last, "short")
    near_sr_alerts = float(max(near_long, near_short))

    # --- Session bucket ---
    session_patterns = float(_session_bucket(ts_local))

    feats = {
        "adx_patterns": float(adx_patterns),
        "adx_alerts": float(adx_alerts),
        "atr_patterns": float(atr_patterns),
        "rsi_patterns": float(rsi_patterns),
        "fvg_present_patterns": float(fvg_present_patterns),
        "htf_trend_alerts": float(htf_trend_alerts),
        "near_sr_alerts": float(near_sr_alerts),
        "session_patterns": float(session_patterns),
    }
    return feats

# ===== Optional: log feature snapshot (for dream.py merge) =====
def emit_feature_event(symbol: str, tf: str, feats: Dict[str, float], ts: pd.Timestamp | None = None) -> None:
    """
    Zapíše 1 řádek do logs/feature_events.csv (bez výjimky při chybě).
    """
    try:
        import csv, pathlib
        p = pathlib.Path(FEATURE_EVENTS_CSV)
        p.parent.mkdir(parents=True, exist_ok=True)
        exists = p.exists()
        with open(p, "a", newline="") as f:
            w = csv.writer(f)
            if not exists:
                w.writerow(["merged_time", "symbol", "tf"] + FEATURE_COLUMNS)
            if ts is None:
                ts = pd.Timestamp.utcnow().tz_localize("UTC")
            row = [ts.isoformat(), symbol.replace("/", "").upper(), tf] + [feats.get(k, 0.0) for k in FEATURE_COLUMNS]
            w.writerow(row)
    except Exception:
        pass
