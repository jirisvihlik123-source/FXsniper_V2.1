from __future__ import annotations
import os, math, datetime as dt
from typing import Dict, List, Tuple, Optional
import numpy as np
import pandas as pd
from .pattern_log import PatternLogger

# ========== logger ==========
_LOGGER = None
def _get_logger() -> PatternLogger:
    global _LOGGER
    if _LOGGER is None:
        csv_path = os.getenv("PATTERN_EVENTS_CSV", "logs/pattern_events.csv")
        _LOGGER = PatternLogger(csv_path)
    return _LOGGER

# ========== základní indikátory (lightweight, bez pandas_ta) ==========
def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()

def rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    delta = df["close"].diff()
    gain = (delta.clip(lower=0)).rolling(period, min_periods=1).mean()
    loss = (-delta.clip(upper=0)).rolling(period, min_periods=1).mean()
    rs = gain / (loss.replace(0, 1e-9))
    return 100 - (100 / (1 + rs))

def session_from_ts(ts: pd.Timestamp, tz: str = "Europe/Prague") -> str:
    try:
        local_ts = ts.tz_convert(tz) if ts.tzinfo else ts.tz_localize("UTC").tz_convert(tz)
    except Exception:
        local_ts = pd.Timestamp(ts).tz_localize("UTC").tz_convert(tz)
    h = int(local_ts.hour)
    if 8 <= h < 12: return "london_open"
    if 12 <= h < 16: return "london_mid"
    if 16 <= h < 20: return "ny_overlap"
    if 20 <= h or h < 1: return "ny_late"
    return "asia"

# ---------- helpers pro pozicovou práci ----------
def _argmax_pos(s: pd.Series) -> int:
    return int(np.nanargmax(s.to_numpy()))

def _argmin_pos(s: pd.Series) -> int:
    return int(np.nanargmin(s.to_numpy()))

# ========== klasické patterny ==========
def detect_double_top(df: pd.DataFrame, lookback: int = 50, sep: int = 5, tol_atr_mult: float = 0.25) -> bool:
    if len(df) < max(lookback, sep + 3): return False
    sub = df.tail(lookback)
    n = len(sub)
    pos_a = _argmax_pos(sub["high"])
    idxs = np.arange(n)
    mask = (idxs < pos_a - sep) | (idxs > pos_a + sep)
    if not mask.any(): return False
    sub2_high = sub["high"].to_numpy()[mask]
    if sub2_high.size == 0: return False
    pos_b_rel = int(np.nanargmax(sub2_high))
    pos_b = int(np.arange(n)[mask][pos_b_rel])

    left, right = (pos_a, pos_b) if pos_b > pos_a else (pos_b, pos_a)

    atr_now = float(atr(df).iloc[-1])
    if math.isnan(atr_now) or atr_now == 0:
        atr_now = float((df["high"] - df["low"]).tail(14).mean())

    tops_close = abs(sub["high"].iloc[left] - sub["high"].iloc[right]) <= tol_atr_mult * atr_now
    neck = float(sub["low"].iloc[min(left, right):max(left, right)+1].rolling(5, min_periods=1).min().iloc[-1])
    return bool(tops_close and df["close"].iloc[-1] < neck)

def detect_double_bottom(df: pd.DataFrame, lookback: int = 50, sep: int = 5, tol_atr_mult: float = 0.25) -> bool:
    if len(df) < max(lookback, sep + 3): return False
    sub = df.tail(lookback)
    n = len(sub)
    pos_a = _argmin_pos(sub["low"])
    idxs = np.arange(n)
    mask = (idxs < pos_a - sep) | (idxs > pos_a + sep)
    if not mask.any(): return False
    sub2_low = sub["low"].to_numpy()[mask]
    if sub2_low.size == 0: return False
    pos_b_rel = int(np.nanargmin(sub2_low))
    pos_b = int(np.arange(n)[mask][pos_b_rel])

    left, right = (pos_a, pos_b) if pos_b > pos_a else (pos_b, pos_a)

    atr_now = float(atr(df).iloc[-1])
    if math.isnan(atr_now) or atr_now == 0:
        atr_now = float((df["high"] - df["low"]).tail(14).mean())

    bots_close = abs(sub["low"].iloc[left] - sub["low"].iloc[right]) <= tol_atr_mult * atr_now
    neck = float(sub["high"].iloc[min(left, right):max(left, right)+1].rolling(5, min_periods=1).max().iloc[-1])
    return bool(bots_close and df["close"].iloc[-1] > neck)

def detect_head_and_shoulders(df: pd.DataFrame, lookback: int = 60, shoulder_tol: float = 0.6) -> bool:
    if len(df) < lookback: return False
    sub = df.tail(lookback)
    highs = sub["high"].to_numpy()
    locs = [i for i in range(2, len(highs)-2) if highs[i] > highs[i-1] and highs[i] > highs[i+1]]
    if len(locs) < 3: return False
    lsh, head, rsh = locs[-3], locs[-2], locs[-1]
    h_l, h_h, h_r = highs[lsh], highs[head], highs[rsh]
    if not (h_h > h_l and h_h > h_r): return False
    if min(h_l, h_r) / max(h_l, h_r) < shoulder_tol: return False
    neckline = float(sub["low"].iloc[-5:-1].min())
    return bool(df["close"].iloc[-1] < neckline)

def detect_fvg(df: pd.DataFrame) -> Tuple[bool, bool]:
    if len(df) < 3: return (False, False)
    low_n  = float(df["low"].iloc[-1]);  high_n2 = float(df["high"].iloc[-3])
    high_n = float(df["high"].iloc[-1]); low_n2  = float(df["low"].iloc[-3])
    bull = low_n > high_n2
    bear = high_n < low_n2
    return (bool(bull), bool(bear))

def detect_sweep(df: pd.DataFrame, wick_ratio_threshold: float = None) -> Tuple[bool, bool]:
    if len(df) < 10: return (False, False)
    wthr = wick_ratio_threshold or float(os.getenv("WICK_RATIO_THRESHOLD", "2.0"))
    last = df.iloc[-1]
    prev_high = float(df["high"].iloc[-10:-1].max())
    prev_low  = float(df["low"].iloc[-10:-1].min())
    body = abs(float(last["close"]) - float(last["open"]))
    up_wick = float(last["high"]) - max(float(last["close"]), float(last["open"]))
    dn_wick = min(float(last["close"]), float(last["open"])) - float(last["low"])
    up_ratio = (up_wick / body) if body > 0 else 999
    dn_ratio = (dn_wick / body) if body > 0 else 999
    buy_sweep  = (float(last["high"]) > prev_high) and (float(last["close"]) < prev_high) and (up_ratio >= wthr)
    sell_sweep = (float(last["low"])  < prev_low ) and (float(last["close"]) > prev_low ) and (dn_ratio >= wthr)
    return (bool(buy_sweep), bool(sell_sweep))

# ========== PLAYBOOK helpers / detektory ==========
def _donchian(df: pd.DataFrame, n: int) -> Tuple[pd.Series, pd.Series]:
    hi = df["high"].rolling(n, min_periods=max(5, n//4)).max()
    lo = df["low"].rolling(n, min_periods=max(5, n//4)).min()
    return hi, lo

def detect_breakout_retest(df: pd.DataFrame, n: int, retest_bars_max: int) -> dict:
    """
    Donchian breakout + retest hrany do X barů.
    Vrací dict: {"side":"long|short","level":float,"bars_since_break":int} nebo prázdný dict.
    """
    if len(df) < n + retest_bars_max + 6: 
        return {}
    hi, lo = _donchian(df, n)
    window = df.iloc[-(retest_bars_max+6):]
    brk = {}
    for i in range(len(window)-1, 1, -1):
        idx = window.index[i]
        p = window.loc[idx]
        if pd.notna(hi.loc[idx]) and p["close"] >= hi.loc[idx]:
            brk = {"side":"long", "level": float(hi.loc[idx]), "break_idx": idx}
            break
        if pd.notna(lo.loc[idx]) and p["close"] <= lo.loc[idx]:
            brk = {"side":"short","level": float(lo.loc[idx]), "break_idx": idx}
            break
    if not brk:
        return {}
    sub = df.loc[brk["break_idx"]:]
    sub = sub.iloc[1:retest_bars_max+2]
    if sub.empty:
        return {}
    if brk["side"] == "long":
        touched = sub[(sub["low"] <= brk["level"])]
    else:
        touched = sub[(sub["high"] >= brk["level"])]
    if touched.empty:
        return {}
    bars_since = len(sub) - len(sub.loc[touched.index[0]:])
    brk["bars_since_break"] = int(bars_since)
    return brk

def detect_trend_pullback(df: pd.DataFrame, ema_len: int, max_dist_atr: float) -> dict:
    """
    Pullback k EMA (typicky 50) – jen M5/M15 část. H1 trend se řeší v analyzeru.
    Vrací {"side":"long|short","ema":float} nebo {}.
    """
    if len(df) < ema_len + 5:
        return {}
    last = df.iloc[-1]
    ema_col = f"ema{ema_len}"
    e = last.get(ema_col)
    if pd.isna(e) or pd.isna(last.get("atr")):
        return {}
    dist = abs(float(last["close"]) - float(e)) / float(last["atr"])
    if dist > max_dist_atr:
        return {}
    side = "long" if float(last["close"]) >= float(e) else "short"
    return {"side": side, "ema": float(e)}

# ========== agregátor pro logování/monitoring ==========
def detect_patterns(df: pd.DataFrame,
                    symbol: str,
                    env: Optional[Dict[str, str]] = None,
                    base_ai_score: float = 0.0,
                    regime: str = "unknown") -> List[str]:
    """
    Vracím seznam detekovaných patternů (double top/bottom, H&S, FVG, sweep)
    a zároveň to zaloguju do CSV (pokud něco najdu).
    """
    env = env or {}
    if len(df) < 20: return []
    atr_now = float(atr(df).iloc[-1])
    rsi_now = float(rsi(df).iloc[-1])
    adx_now = float(env.get("ADX_VALUE", 20))
    sess = session_from_ts(df.index[-1])

    detected: List[str] = []
    bull_fvg, bear_fvg = detect_fvg(df)
    buy_sweep, sell_sweep = detect_sweep(df)

    if detect_double_top(df): detected.append("double_top")
    if detect_double_bottom(df): detected.append("double_bottom")
    if detect_head_and_shoulders(df): detected.append("head_and_shoulders")
    if bull_fvg: detected.append("fvg_bull")
    if bear_fvg: detected.append("fvg_bear")
    if buy_sweep: detected.append("sweep_buy_side")
    if sell_sweep: detected.append("sweep_sell_side")

    if detected:
        lg = _get_logger()
        for p in detected:
            lg.log_event(
                symbol=symbol, pattern=p, regime=regime, session=sess,
                adx=adx_now, atr=atr_now, rsi=rsi_now,
                fvg_present=int(bull_fvg or bear_fvg), sweep_present=int(buy_sweep or sell_sweep),
                ai_score_at_event=float(base_ai_score),
                entry_ts=dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc),
                trade_id=None, taken=0
            )
    return detected

# ========== ADAPTER pro analyzer (kompatibilita) ==========
def detect_patterns_bias(df: pd.DataFrame, *,
                         adx: float,
                         ema50: float,
                         ema200: float,
                         opts: Optional[Dict[str, str]] = None) -> Dict[str, Optional[str]]:
    """
    Vrátí dict s klíčem 'bias' pro analyzer:
    {'bias': 'long' | 'short' | None}
    Heuristika: 
      long pokud (double_bottom | fvg_bull | sweep_buy_side) a trend není vyloženě down
      short pokud (double_top | head_and_shoulders | fvg_bear | sweep_sell_side) a trend není up
    """
    if df is None or len(df) < 20:
        return {"bias": None}

    pats = detect_patterns(df, symbol=opts.get("symbol","UNK") if opts else "UNK",
                           env={"ADX_VALUE": adx}, base_ai_score=float(opts.get("ai",0.0)) if opts else 0.0,
                           regime=opts.get("regime","unknown") if opts else "unknown")

    trend_up = (ema50 is not None and ema200 is not None and float(ema50) > float(ema200))
    trend_down = (ema50 is not None and ema200 is not None and float(ema50) < float(ema200))

    has_long = any(p in pats for p in ["double_bottom","fvg_bull","sweep_buy_side"])
    has_short= any(p in pats for p in ["double_top","head_and_shoulders","fvg_bear","sweep_sell_side"])

    if has_long and not has_short and (not trend_down):
        return {"bias": "long"}
    if has_short and not has_long and (not trend_up):
        return {"bias": "short"}
    return {"bias": None}

__all__ = [
    "detect_patterns",
    "detect_patterns_bias",
    "detect_breakout_retest",
    "detect_trend_pullback",
    "detect_fvg",
    "detect_sweep",
    "detect_double_top",
    "detect_double_bottom",
    "detect_head_and_shoulders",
    "atr",
    "rsi",
    "session_from_ts",
]
