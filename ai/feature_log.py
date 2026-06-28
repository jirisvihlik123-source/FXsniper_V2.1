from pathlib import Path
import csv

FEATURES_FILE = Path("logs/feature_events.csv")
COLUMNS = [
    "timestamp","symbol","tf","side","price","entry_hint",
    "atr","adx","rsi","ema50_slope","ema200_slope","htf_trend",
    "dist_to_sr_atr","wick_ratio","fvg_up","fvg_down","dist_to_fvg_atr",
    "eq_highs","eq_lows","sweep_up","sweep_down","hh","hl","lh","ll",
    "features_version"
]

def _ensure_header():
    FEATURES_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not FEATURES_FILE.exists():
        with FEATURES_FILE.open("w", newline="") as f:
            csv.DictWriter(f, fieldnames=COLUMNS).writeheader()

def log_candidate(meta: dict, feats: dict, features_version: int = 1):
    """
    meta: {"timestamp", "symbol", "tf", "side", "price", "entry_hint"}
    feats: viz COLUMNS (číselné hodnoty)
    """
    _ensure_header()
    row = {c: "" for c in COLUMNS}
    row.update({
        "timestamp": meta.get("timestamp"),
        "symbol": meta.get("symbol"),
        "tf": meta.get("tf"),
        "side": meta.get("side"),
        "price": meta.get("price"),
        "entry_hint": meta.get("entry_hint"),
        "features_version": features_version,
    })
    for k in COLUMNS:
        if k in feats:
            row[k] = feats[k]
    with FEATURES_FILE.open("a", newline="") as f:
        csv.DictWriter(f, fieldnames=COLUMNS).writerow(row)
