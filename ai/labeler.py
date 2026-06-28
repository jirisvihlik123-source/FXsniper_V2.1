from pathlib import Path
import pandas as pd
import numpy as np

FEATURES = Path("logs/feature_events.csv")
TRADES   = Path("logs/trades.csv")
DATASET  = Path("logs/ml_dataset.csv")

def _side_from_row(row):
    s = str(row).upper()
    if "LONG" in s:  return "long"
    if "SHORT" in s: return "short"
    return None

def _safe_ts(s):
    return pd.to_datetime(s, utc=True, errors="coerce")

def build_dataset(max_lookback_days: int = 45, max_delta_min: int = 20) -> int:
    """
    Spojí feature snapshoty s uzavřenými obchody:
      - match podle symbol+tf+side a blízkosti času (|opened_at - timestamp| <= max_delta_min)
      - pokud máme entry_hint i entry, zúží výběr i podle blízkosti ceny
    Uloží logs/ml_dataset.csv se sloupcem y (1=win, 0=loss).
    Vrací počet záznamů v datasetu (po přepisu).
    """
    if not FEATURES.exists() or not TRADES.exists():
        return 0
    df_f = pd.read_csv(FEATURES)
    df_t = pd.read_csv(TRADES)

    if df_f.empty or df_t.empty:
        return 0

    # jen uzavřené obchody s labely
    if "closed_at" in df_t.columns:
        df_t["closed_at"] = _safe_ts(df_t["closed_at"])
        cutoff = pd.Timestamp.utcnow() - pd.Timedelta(days=max_lookback_days)
        df_t = df_t[df_t["closed_at"] >= cutoff]

    df_t = df_t[df_t["status"].isin(["WON","LOST"])].copy()
    if df_t.empty:
        return 0

    # normalizace času
    for c in ("opened_at","closed_at"):
        if c in df_t.columns:
            df_t[c] = _safe_ts(df_t[c])
    df_f["timestamp"] = _safe_ts(df_f["timestamp"])

    # side
    if "side" not in df_t.columns and "Side" in df_t.columns:
        df_t["side"] = df_t["Side"]
    if "side" in df_t.columns:
        df_t["side"] = df_t["side"].apply(_side_from_row)

    # základní sloupce
    base_cols = ["symbol","tf","side"]
    for c in base_cols:
        if c not in df_f.columns: df_f[c] = np.nan
        if c not in df_t.columns: df_t[c] = np.nan

    out_rows = []
    df_t_small = df_t[["symbol","tf","side","opened_at","entry","status"]].copy() if "entry" in df_t.columns else df_t[["symbol","tf","side","opened_at","status"]].copy()
    for _, f in df_f.dropna(subset=["timestamp"]).iterrows():
        cand = df_t_small[
            (df_t_small["symbol"].astype(str) == str(f["symbol"])) &
            (df_t_small["tf"].astype(str) == str(f["tf"])) &
            (df_t_small["side"].astype(str) == str(f.get("side", None)))
        ].copy()
        if cand.empty:
            continue
        cand["dt"] = (cand["opened_at"] - f["timestamp"]).abs() / pd.Timedelta(minutes=1)
        cand = cand[cand["dt"] <= max_delta_min].sort_values("dt")
        if cand.empty:
            continue

        # preferuj i cenově bližší match (pokud dostupné)
        if "entry" in cand.columns and not pd.isna(f.get("entry_hint", np.nan)):
            try:
                eh = float(f["entry_hint"])
                cand["dp"] = (cand["entry"] - eh) ** 2
                cand = cand.sort_values(["dt","dp"])
            except Exception:
                pass

        match = cand.iloc[0]
        y = 1 if str(match["status"]).upper()=="WON" else 0

        row = f.to_dict()
        row["y"] = int(y)
        out_rows.append(row)

    if not out_rows:
        return 0

    df_out = pd.DataFrame(out_rows)
    df_out.to_csv(DATASET, index=False)
    return len(df_out)
