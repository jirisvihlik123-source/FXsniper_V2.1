import math
from typing import Dict, Any, Tuple

try:
    from .features import extract_last_features
    from .scorer import AIScorer
except Exception:
    extract_last_features = None
    AIScorer = None

def heuristic_adx(adx: float) -> float:
    if adx is None or adx <= 0: return 0.0
    return max(0.0, min(100.0, (adx / 40.0) * 100.0))

def heuristic_rsi(rsi: float, lo: float=35, hi: float=65) -> float:
    if rsi is None: return 0.0
    if rsi <= lo:
        return max(0.0, min(100.0, (lo - rsi) / max(lo,1e-9) * 100.0 + 30.0))
    if rsi >= hi:
        return max(0.0, min(100.0, (rsi - hi) / max(100-hi,1e-9) * 100.0 + 30.0))
    return 0.0

def heuristic_wick(wick: float) -> float:
    if wick is None: return 50.0
    return max(0.0, min(100.0, 100.0 * (1.0 - min(1.0, wick/3.0))))

class Ensemble:
    """
    Kombinuje několik zdrojů skóre:
      - AIScorer (pokud existuje model.pkl)
      - Heuristika ADX
      - Heuristika RSI (vzdálenost od extrémů)
      - Wick (kratší těla knotu = lepší)
    Vrací (total_score 0..100, component_scores dict).
    """
    def __init__(self, ai_model: AIScorer = None, weights: Dict[str,float]=None):
        self.ai = ai_model
        self.weights = weights or {
            "ai": 0.35,
            "adx": 0.25,
            "rsi": 0.25,
            "wick": 0.15
        }
        s = sum(self.weights.values()) or 1.0
        for k in list(self.weights.keys()):
            self.weights[k] /= s

    def score_from_features(self, feat: Dict[str, Any]) -> Tuple[float, Dict[str,float]]:
        ai_score = None
        if self.ai is not None:
            try:
                ai_score = float(self.ai.score(feat))
            except Exception:
                ai_score = None

        adx_s = heuristic_adx(float(feat.get("adx", 0.0)))
        rsi_s = heuristic_rsi(float(feat.get("rsi", 50.0)))
        wick_s = heuristic_wick(float(feat.get("wick_ratio", 1.0)))

        comp = {
            "ai": float(ai_score) if ai_score is not None else 0.0,
            "adx": adx_s,
            "rsi": rsi_s,
            "wick": wick_s
        }

        total = 0.0
        for k, w in self.weights.items():
            total += comp.get(k, 0.0) * w

        if ai_score is None and self.weights.get("ai",0)>0:
            wsum = sum([self.weights[k] for k in self.weights if k!="ai"]) or 1.0
            total = total / wsum

        total = max(0.0, min(100.0, total))
        return float(total), comp
