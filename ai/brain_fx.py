# ai/brain_fx.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import json, math, pathlib
from typing import Dict, Any, Optional

# reálný umístění v projektu: logs/brain_memory.json
MEM_PATH = pathlib.Path(os.getenv("BRAIN_MEMORY_PATH", "logs/brain_memory.json"))
MEM_PATH.parent.mkdir(parents=True, exist_ok=True)
if not MEM_PATH.exists():
    MEM_PATH.write_text("{}", encoding="utf-8")

def _load_mem():
    try:
        return json.loads(MEM_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_mem(data):
    MEM_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def _record_experience(symbol:str, side:str, feat:Dict[str,Any], result:str|None=None):
    mem = _load_mem()
    key = f"{symbol}:{side.upper()}"
    entry = {
        "result": (result or "").upper(),
        "rsi": float(feat.get("rsi", float("nan"))),
        "adx": float(feat.get("adx", float("nan"))),
        "atr": float(feat.get("atr", float("nan"))),
        "ema50": float(feat.get("ema50", float("nan"))),
        "ema200": float(feat.get("ema200", float("nan"))),
        "tf": feat.get("tf"),
    }
    arr = mem.get(key, [])
    arr.append(entry)
    mem[key] = arr[-500:]
    _save_mem(mem)

def _penalty(symbol:str, side:str)->float:
    """Vrací penalizaci 0..1 podle winrate z posledních 30 obchodů."""
    mem = _load_mem()
    key = f"{symbol}:{side.upper()}"
    arr = mem.get(key, [])
    if not arr:
        return 0.0
    last = [x for x in arr[-30:] if x.get("result") in ("WIN","LOSS")]
    if not last:
        return 0.0
    wins = sum(1 for x in last if x.get("result")=="WIN")
    wr = wins / len(last)
    # penalizace = 1 - WR (0=žádný trest při 100% WR)
    return round(1.0 - wr, 3)

# ====== pomocné funkce ======
def _safe_float(x: Any, default: float = float("nan")) -> float:
    try:
        v = float(x)
        return v if not math.isnan(v) else default
    except Exception:
        return default

def _trend_side(feat: Dict[str, Any]) -> Optional[str]:
    close  = _safe_float(feat.get("close"))
    ema50  = _safe_float(feat.get("ema50"))
    ema200 = _safe_float(feat.get("ema200"))
    if math.isnan(close) or math.isnan(ema50) or math.isnan(ema200):
        return None
    if ema50 > ema200 and close >= ema50:
        return "LONG"
    if ema50 < ema200 and close <= ema50:
        return "SHORT"
    return "LONG" if close < ema50 else "SHORT"

def _base_score(feat: Dict[str, Any]) -> float:
    adx   = _safe_float(feat.get("adx"), 0.0)
    rsi   = _safe_float(feat.get("rsi"), 50.0)
    close = _safe_float(feat.get("close"))
    ema50 = _safe_float(feat.get("ema50"))
    ema200= _safe_float(feat.get("ema200"))
    atr   = _safe_float(feat.get("atr"), 0.0)
    adx_n = max(0.0, min(1.0, (adx - 12.0) / 28.0))
    ema_align = 1.0 if ((ema50>ema200 and close>=ema50) or (ema50<ema200 and close<=ema50)) else -0.3
    dist_bonus = 0.0
    if atr>0 and not math.isnan(close) and not math.isnan(ema50):
        dist_atr = min(1.6, abs(close - ema50) / atr)
        dist_bonus = max(0.0, 1.0 - abs(dist_atr - 0.6))
    rsi_bonus = 0.2 if 35.0 <= rsi <= 65.0 else 0.0
    base = 45.0 + 30.0*adx_n + 15.0*ema_align + 10.0*dist_bonus + 5.0*rsi_bonus
    return float(max(0.0, min(100.0, base)))

def _apply_penalty(symbol:str, side:str, base:float, brain_weight:float=0.3)->float:
    pen = _penalty(symbol, side)
    eff = base * (1.0 - brain_weight*min(0.6, pen))
    return float(max(0.0, min(100.0, eff)))

# ====== hlavní API ======
def brain_signal(feat: Dict[str, Any], cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    symbol = str(feat.get("symbol","") or "").upper()
    if not symbol or "close" not in feat:
        return None
    side = _trend_side(feat) or "LONG"
    base = _base_score(feat)
    eff  = _apply_penalty(symbol, side, base, brain_weight=0.30)

    headsup_min = float(cfg.get("BRAIN_HEADSUP_MIN",55.0))
    alert_min   = float(cfg.get("BRAIN_ALERT_MIN",72.0))

    if eff >= alert_min:
        return {"type":"BRAIN_ALERT","side":side,"entry":_safe_float(feat.get("close"),0.0),"score":round(eff,1)}
    if eff >= headsup_min:
        return {"type":"BRAIN_HEADSUP","side":side,"entry":_safe_float(feat.get("close"),0.0),"score":round(eff,1)}
    return None

def brain_confidence(feat: Dict[str, Any]) -> Dict[str, Any]:
    symbol = str(feat.get("symbol","") or "").upper()
    side = _trend_side(feat) or "LONG"
    base = _base_score(feat)
    eff  = _apply_penalty(symbol, side, base, brain_weight=0.30)
    return {"confidence": round(eff,1)}

def brain_record_result(symbol: str, side: str, feat: Dict[str, Any], status: str) -> None:
    s = (status or "").upper()
    if s == "LOST":
        s = "LOSS"
    if s not in ("WIN", "LOSS"):
        return
    _record_experience(symbol.upper(), side.upper(), feat, result=s)


__all__ = ["brain_signal","brain_confidence","brain_record_result"]

