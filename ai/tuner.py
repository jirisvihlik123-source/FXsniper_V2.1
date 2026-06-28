import os, json, time
import pandas as pd
from typing import Dict, Any

DEFAULT_STATE = {
    "updated_at": 0.0,
    "offsets": {
        "AI_SCORE_MIN": 0.0,
        "ADX_MIN": 0.0,
        "RSI_LO": 0.0,
        "RSI_HI": 0.0,
    },
    "stats": {"win": 0, "loss": 0, "winrate": None, "sample": 0}
}

class AutoTweaker:
    def __init__(self, path: str = "ai/auto_tune.json",
                 target_win_min: float = 55.0,
                 target_win_max: float = 65.0,
                 min_sample: int = 30):
        self.path = path
        self.target_win_min = target_win_min
        self.target_win_max = target_win_max
        self.min_sample = min_sample
        self.state = DEFAULT_STATE.copy()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, "r") as f:
                    obj = json.load(f)
                for k,v in DEFAULT_STATE.items():
                    if k not in obj: obj[k]=v
                self.state = obj
        except Exception:
            self.state = DEFAULT_STATE.copy()

    def save(self):
        try:
            with open(self.path, "w") as f:
                json.dump(self.state, f, indent=2)
        except Exception:
            pass

    def reset(self):
        self.state = DEFAULT_STATE.copy()
        self.save()

    def update_from_logs(self, alerts_csv: str, days: int = 14):
        try:
            df = pd.read_csv(alerts_csv)
        except Exception:
            return
        if df.empty or "result" not in df.columns:
            return
        if "type" in df.columns:
            df = df[df["type"]=="alert"]
        if "utc_time" in df.columns:
            df["utc_time"] = pd.to_datetime(df["utc_time"], utc=True, errors="coerce")
            th = pd.Timestamp.utcnow().tz_localize("UTC") - pd.Timedelta(days=days)
            df = df[df["utc_time"]>=th]
        df = df[df["result"].isin(["win","loss"])]
        wins = (df["result"]=="win").sum()
        losses = (df["result"]=="loss").sum()
        sample = wins+losses
        winrate = (wins/sample*100.0) if sample>0 else None

        self.state["stats"] = {"win": int(wins), "loss": int(losses), "winrate": winrate, "sample": int(sample)}
        if sample < self.min_sample or winrate is None:
            self.state["updated_at"] = time.time()
            self.save()
            return

        offs = self.state["offsets"]
        step_ai  = 1.5
        step_adx = 0.7
        step_rsi = 1.0

        if winrate < self.target_win_min:
            offs["AI_SCORE_MIN"] = min(+20.0, offs.get("AI_SCORE_MIN",0.0) + step_ai)
            offs["ADX_MIN"]      = min(+10.0, offs.get("ADX_MIN",0.0) + step_adx)
            offs["RSI_LO"]       = min(+10.0, offs.get("RSI_LO",0.0) + step_rsi/2)
            offs["RSI_HI"]       = max(-10.0, offs.get("RSI_HI",0.0) - step_rsi/2)
        elif winrate > self.target_win_max:
            offs["AI_SCORE_MIN"] = max(-20.0, offs.get("AI_SCORE_MIN",0.0) - step_ai)
            offs["ADX_MIN"]      = max(-10.0, offs.get("ADX_MIN",0.0) - step_adx)
            offs["RSI_LO"]       = max(-10.0, offs.get("RSI_LO",0.0) - step_rsi/2)
            offs["RSI_HI"]       = min(+10.0, offs.get("RSI_HI",0.0) + step_rsi/2)

        self.state["offsets"] = offs
        self.state["updated_at"] = time.time()
        self.save()

    def apply(self, ai_min: float, adx_min: float, r_lo: float, r_hi: float):
        offs = self.state.get("offsets", {})
        ai_min = max(0.0, ai_min + offs.get("AI_SCORE_MIN", 0.0))
        adx_min = max(0.0, adx_min + offs.get("ADX_MIN", 0.0))
        r_lo = max(0.0, r_lo + offs.get("RSI_LO", 0.0))
        r_hi = min(100.0, r_hi + offs.get("RSI_HI", 0.0))
        if r_lo >= r_hi:
            mid = (r_lo + r_hi)/2
            r_lo = mid - 1.0
            r_hi = mid + 1.0
        return ai_min, adx_min, r_lo, r_hi

    def status(self) -> Dict[str, Any]:
        return self.state
