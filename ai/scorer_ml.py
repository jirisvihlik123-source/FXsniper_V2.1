from __future__ import annotations
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
import math
import joblib
import numpy as np

ONLINE_DIR = Path("ai/models/current_online")
GLOBAL_PATH = Path("ai/models/current_global.pkl")

FEATURE_COLUMNS = [
    "atr","adx","rsi","ema50_slope","ema200_slope","dist_to_sr_atr","wick_ratio",
    "fvg_up","fvg_down","dist_to_fvg_atr","eq_highs","eq_lows","sweep_up","sweep_down",
    "hh","hl","lh","ll"
]

# --- jednoduchý cache, ať nečteme modely z disku pořád dokola ---
_cache_online: Dict[str, Any] = {}
_cache_global: Dict[str, Any] = {"model": None, "mtime": None}

def _sigmoid(x: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0

def _vectorize(feats: dict) -> np.ndarray:
    v = [feats.get(c, 0.0) for c in FEATURE_COLUMNS]
    # nahraď NaN/inf nulou
    vv = [0.0 if (isinstance(x, float) and (math.isnan(x) or math.isinf(x))) else x for x in v]
    return np.array(vv, dtype=float).reshape(1, -1)

def _load_online(symbol: str):
    p = ONLINE_DIR / f"{symbol.upper()}.pkl"
    if not p.exists():
        return None
    mt = p.stat().st_mtime
    key = symbol.upper()
    cached = _cache_online.get(key)
    if cached and cached.get("mtime") == mt:
        return cached.get("model")
    try:
        model = joblib.load(p)
        _cache_online[key] = {"model": model, "mtime": mt}
        return model
    except Exception:
        return None

def _load_global():
    p = GLOBAL_PATH
    if not p.exists():
        return None
    mt = p.stat().st_mtime
    cached = _cache_global
    if cached.get("model") is not None and cached.get("mtime") == mt:
        return cached.get("model")
    try:
        model = joblib.load(p)
        _cache_global["model"] = model
        _cache_global["mtime"] = mt
        return model
    except Exception:
        return None

def _predict_proba(model, X: np.ndarray) -> Optional[float]:
    if model is None:
        return None
    try:
        # sklearn Pipeline s .predict_proba
        if hasattr(model, "predict_proba"):
            p = model.predict_proba(X)
            return float(p[:, 1][0])
        # pipeline: poslední krok může mít decision_function
        if hasattr(model, "decision_function"):
            d = model.decision_function(X)
            return float(_sigmoid(float(d[0])))
        # pipeline s pojmenovanými kroky
        if hasattr(model, "named_steps"):
            last = list(model.named_steps.values())[-1]
            if hasattr(last, "predict_proba"):
                p = last.predict_proba(X)
                return float(p[:, 1][0])
            if hasattr(last, "decision_function"):
                d = last.decision_function(X)
                return float(_sigmoid(float(d[0])))
    except Exception:
        return None
    return None

def get_probs_for_symbol(symbol: str, feats: dict) -> Tuple[Optional[float], Optional[float]]:
    """
    Vrací (p_online, p_global) jako pravděpodobnosti WIN v rozsahu 0..1 (nebo None).
    """
    X = _vectorize(feats)

    online = _load_online(symbol)
    p_online = _predict_proba(online, X)

    global_m = _load_global()
    p_global = _predict_proba(global_m, X)

    return p_online, p_global
