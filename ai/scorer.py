# ai/scorer.py
from __future__ import annotations
import os
import numpy as np

try:
    import joblib  # optional
except Exception:
    joblib = None

from .features import FEATURE_COLUMNS


class AIScorer:
    """
    Finální AI skórovací modul:
      - pokud existuje ai/model.pkl → použije trénovaný sklearn model
      - jinak používá heuristiku 0..100 nad FEATURE_COLUMNS z ai/features.py
      - váží výsledek s pamětí (BRAIN_WEIGHT) přes environment
    """

    def __init__(self, model_path: str | None = "ai/model.pkl"):
        self.model = None
        self.feature_order = list(FEATURE_COLUMNS)
        self.debug = os.getenv("DEBUG_SIGNALS", "0") == "1"

        if model_path and os.path.exists(model_path) and joblib is not None:
            try:
                loaded = joblib.load(model_path)
                if isinstance(loaded, dict) and "model" in loaded:
                    self.model = loaded["model"]
                    fo = loaded.get("feature_order")
                    if isinstance(fo, (list, tuple)) and len(fo) > 0:
                        self.feature_order = list(fo)
                else:
                    self.model = loaded
                if self.debug:
                    print(f"[scorer] model loaded from {model_path}")
            except Exception as e:
                self.model = None
                if self.debug:
                    print(f"[scorer] model load failed: {e.__class__.__name__}: {e}")

    # ===============================
    # Heuristické skóre (laděno na FEATURE_COLUMNS z ai/features.py)
    # ===============================
    def _heur_score(self, f: dict, penalty: float = 0.0) -> float:
        # Vstupy přesně dle ai/features.py
        adx_patterns         = float(f.get("adx_patterns", 0.0))          # 0–2
        adx_alerts           = float(f.get("adx_alerts", 0.0))            # 0–10
        atr_patterns         = float(f.get("atr_patterns", 0.0))          # 0–2
        rsi_patterns         = float(f.get("rsi_patterns", 0.0))          # 0–6
        fvg_present_patterns = float(f.get("fvg_present_patterns", 0.0))  # 0/1
        htf_trend_alerts     = float(f.get("htf_trend_alerts", 0.0))      # 0/1
        near_sr_alerts       = float(f.get("near_sr_alerts", 0.0))        # 0/1
        session_patterns     = float(f.get("session_patterns", 0.0))      # 0..4

        # Normalizace do 0..1
        adx_block   = np.clip(0.5 * (adx_patterns / 2.0) + 0.5 * (adx_alerts / 10.0), 0.0, 1.0)
        atr_block   = np.clip(atr_patterns / 2.0, 0.0, 1.0)
        rsi_block   = np.clip(rsi_patterns / 6.0, 0.0, 1.0)
        fvg_block   = np.clip(fvg_present_patterns, 0.0, 1.0)
        trend_block = np.clip(htf_trend_alerts, 0.0, 1.0)
        sr_block    = np.clip(near_sr_alerts, 0.0, 1.0)

        # Seance: 0→0.5, 1→1.0, 2→1.0, 3→0.7, 4→0.3
        sess_map = {0: 0.5, 1: 1.0, 2: 1.0, 3: 0.7, 4: 0.3}
        session_w = sess_map.get(int(round(session_patterns)), 0.6)

        # Kompozit (víc alertů při WR ~55 %)
        base01 = (
            0.25 * adx_block +
            0.18 * atr_block +
            0.18 * rsi_block +
            0.12 * trend_block +
            0.12 * sr_block +
            0.08 * fvg_block +
            0.07 * session_w
        )

        # Bonusy / penalizace
        combo_bonus = 0.10 if (trend_block > 0.5 and sr_block > 0.0) else 0.0
        weak_pen = 0.10 if (adx_block < 0.2 and rsi_block < 0.2) else 0.0

        base01 = np.clip(base01 + combo_bonus - weak_pen, 0.0, 1.2)

        # Penalizace „mozku“ (brain_penalty 0..1)
        score = 100.0 * base01 * (1.0 - 0.4 * np.clip(penalty, 0.0, 1.0))
        return float(np.clip(score, 0.0, 100.0))

    # ===============================
    # Veřejné API
    # ===============================
    def score(self, feat: dict, brain_penalty: float = 0.0) -> float:
        """
        Vrací finální skóre 0–100 kombinací AI modelu (pokud je), heuristiky a penalizace z paměti.
        """
        model_score = None

        if self.model is not None:
            try:
                cols = self.feature_order if self.feature_order else FEATURE_COLUMNS
                X = np.array([[float(feat.get(k, 0.0) or 0.0) for k in cols]], dtype=float)
                try:
                    prob = float(self.model.predict_proba(X)[0, 1])
                except Exception:
                    df = float(self.model.decision_function(X)[0])
                    prob = 1.0 / (1.0 + np.exp(-df))
                model_score = float(100.0 * prob)
            except Exception as e:
                model_score = None
                if self.debug:
                    print(f"[scorer] model inference failed: {e.__class__.__name__}: {e}")

        heur_score = self._heur_score(feat, penalty=brain_penalty)

        if model_score is not None:
            weight = float(os.getenv("BRAIN_WEIGHT", "0.3"))
            final = (1 - weight) * heur_score + weight * model_score
        else:
            final = heur_score

        if self.debug:
            ms = f"{model_score:.1f}" if model_score is not None else "None"
            print(f"[scorer] heur={heur_score:.1f} model={ms} final={final:.1f} penalty={brain_penalty:.2f}")

        return float(np.clip(final, 0.0, 100.0))
