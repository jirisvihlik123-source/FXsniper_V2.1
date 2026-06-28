from __future__ import annotations
from pathlib import Path
import json
import time
import joblib
import pandas as pd
import numpy as np
from typing import Optional, Tuple
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

DATASET = Path("logs/ml_dataset.csv")
MODELS_DIR = Path("ai/models")
GLOBAL_PATH = MODELS_DIR / "current_global.pkl"
HISTORY_DIR = MODELS_DIR / "history"
ONLINE_DIR  = MODELS_DIR / "current_online"

FEATURE_COLUMNS = [
    "atr","adx","rsi","ema50_slope","ema200_slope","dist_to_sr_atr","wick_ratio",
    "fvg_up","fvg_down","dist_to_fvg_atr","eq_highs","eq_lows","sweep_up","sweep_down",
    "hh","hl","lh","ll"
]

def _model_pipeline() -> Pipeline:
    return Pipeline([
        ("imp", SimpleImputer()),                      # doplní NaN
        ("sc",  StandardScaler(with_mean=False)),      # škáluje
        ("lr",  LogisticRegression(
                    solver="liblinear",
                    class_weight="balanced",
                    max_iter=1000,
                    random_state=42))
    ])

def _chronological_split(df: pd.DataFrame, test_ratio: float = 0.2) -> Tuple[pd.DataFrame, pd.DataFrame]:
    df = df.sort_values("timestamp")
    n = len(df)
    if n < 10:
        # moc málo, vrať celé jako „train“
        return df, pd.DataFrame(columns=df.columns)
    cut = max(1, int((1.0 - test_ratio) * n))
    return df.iloc[:cut], df.iloc[cut:]

def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    # filtr platných labelů
    df = df.dropna(subset=["y"]).copy()
    # timestamp pro chrono split – když chybí, vytvoř
    if "timestamp" not in df.columns:
        df["timestamp"] = pd.Timestamp.utcnow()
    else:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce").fillna(pd.Timestamp.utcnow())
    # symbol/side/tf jen pro info
    return df

def _evaluate_auc(model: Pipeline, X: np.ndarray, y: np.ndarray) -> Optional[float]:
    try:
        p = model.predict_proba(X)[:,1]
        return float(roc_auc_score(y, p))
    except Exception:
        return None

def maybe_train_nightly(min_labels: int = 300, min_auc: float = 0.60) -> Optional[dict]:
    """
    Trénuje globální model nad všemi symboly.
    - dataset: logs/ml_dataset.csv (sloupce FEATURE_COLUMNS + y)
    - chrono split 80/20
    - pokud AUC >= min_auc, uloží jako current_global.pkl a archivuje do history/
    Vrací dict s metrikami, jinak None.
    """
    if not DATASET.exists():
        return None
    df = pd.read_csv(DATASET)
    if df.empty or df.shape[0] < min_labels:
        return None

    df = _prepare(df)
    df = df.dropna(subset=FEATURE_COLUMNS + ["y"])
    if df.shape[0] < min_labels:
        return None

    train_df, test_df = _chronological_split(df, test_ratio=0.2)
    X_train = train_df[FEATURE_COLUMNS].fillna(0.0).values
    y_train = train_df["y"].astype(int).values
    model = _model_pipeline()
    model.fit(X_train, y_train)

    metrics = {"train_count": int(len(train_df)), "test_count": int(len(test_df))}
    if len(test_df) > 0:
        X_test = test_df[FEATURE_COLUMNS].fillna(0.0).values
        y_test = test_df["y"].astype(int).values
        auc = _evaluate_auc(model, X_test, y_test)
        metrics["auc"] = auc
        if auc is None or auc < min_auc:
            return None

    # save current + history snapshot
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, GLOBAL_PATH)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    hist_path = HISTORY_DIR / f"global_{stamp}.pkl"
    joblib.dump(model, hist_path)

    meta = {
        "saved_at": stamp,
        "path": str(GLOBAL_PATH),
        "history": str(hist_path),
        **metrics
    }
    # ulož metriky vedle modelu
    with (GLOBAL_PATH.with_suffix(".json")).open("w") as f:
        json.dump(meta, f, indent=2)
    return meta
