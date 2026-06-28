from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import pandas as pd
import numpy as np

@dataclass
class ContextFlags:
    recent_sweep: bool = False
    recent_sweep_side: Optional[str] = None   # "long"|"short"|None
    fvg_nearby: bool = False
    fvg_side: Optional[str] = None            # "bull"|"bear"|None
    bars_since_flag: int = 999


TF_TO_MIN = {
    "M1":1, "M5":5, "M15":15, "M30":30,
    "H1":60, "H4":240, "D":1440
}


# =========================
# Safe getters
# =========================
def _v(row, key, default=0.0):
    try:
        return float(row.get(key, default))
    except:
        return float(default)


# =========================
# Pomocné funkce
# =========================
def _wick_ratio(row) -> float:
    """Bezpečný výpočet poměru knotu k tělu."""
    try:
        o = _v(row, "open")
        c = _v(row, "close")
        h = _v(row, "high")
        l = _v(row, "low")

        body = abs(c - o) + 1e-9
        upper = h - max(c, o)
        lower = min(c, o) - l
        return float(max(upper, lower) / body)
    except:
        return 0.0


def _liquidity_sweep(prev: pd.Series, cur: pd.Series) -> Optional[str]:
    """Bezpečný sweep — nikdy nepadne."""
    try:
        prev_low  = _v(prev, "low")
        prev_high = _v(prev, "high")
        cur_low   = _v(cur, "low")
        cur_high  = _v(cur, "high")
        cur_close = _v(cur, "close")

        if cur_low < prev_low and cur_close > prev_low:
            return "long"
        if cur_high > prev_high and cur_close < prev_high:
            return "short"
        return None
    except:
        return None


def _has_fvg(a: pd.Series, b: pd.Series, c: pd.Series) -> Optional[str]:
    """Bezpečná FVG detekce — nikdy KeyError."""
    try:
        a_h = _v(a, "high"); a_l = _v(a, "low")
        b_h = _v(b, "high"); b_l = _v(b, "low")
        c_h = _v(c, "high"); c_l = _v(c, "low")

        if b_l > a_h and c_h > b_l:
            return "bull"
        if b_h < a_l and c_l < b_h:
            return "bear"
        return None
    except:
        return None


# =========================
# Hlavní funkce
# =========================
def scan_context(df: pd.DataFrame, tf: str,
                 lookback_min: int = 120,
                 max_check_bars: int = 48,
                 wick_th: float = 2.4) -> ContextFlags:

    flags = ContextFlags()

    if df is None or df.empty:
        return flags

    # bezpečný počet barů
    tf_min = TF_TO_MIN.get(tf, 5)
    bars_back = min(max_check_bars, max(3, int(lookback_min / max(1, tf_min))))

    window = df.tail(bars_back).reset_index(drop=True)
    n = len(window)
    if n < 3:
        return flags

    # ===== Sweep detection =====
    for i in range(n - 1, 0, -1):
        prev = window.iloc[i - 1]
        cur = window.iloc[i]

        side = _liquidity_sweep(prev, cur)
        if side and _wick_ratio(cur) >= wick_th:
            flags.recent_sweep = True
            flags.recent_sweep_side = side
            flags.bars_since_flag = n - 1 - i
            break

    # ===== FVG detection =====
    for i in range(n - 1, 1, -1):
        a = window.iloc[i - 2]
        b = window.iloc[i - 1]
        c = window.iloc[i]

        side = _has_fvg(a, b, c)
        if side:
            flags.fvg_nearby = True
            flags.fvg_side = side
            flags.bars_since_flag = min(flags.bars_since_flag, n - 1 - i)
            break

    return flags
