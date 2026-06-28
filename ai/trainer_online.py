from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer

DATASET = Path("logs/ml_dataset.csv")
ONLINE_DIR = Path("ai/models/current_online")
ONLINE_DIR.mkdir(parents=True, exist_ok=True)

FEATURE_COLUMNS = [
    "atr","adx","rsi","ema50_slope","ema200_slope","dist_to_sr_atr","wick_ratio",
    "fvg_up","fvg_down","dist_to_fvg_atr","eq_highs","eq_lows","sweep_up","sweep_down",
    "hh","hl","lh","ll"
]

def _sym_path(symbol: str) -> Path:
    return ONLINE_DIR / f"{symbol.upper()}.pkl"

def update_online_models_for_symbol(symbol: str,
                                    min_labels: int = 60,
                                    min_per_class: int = 20,
                                    batch_size: int = 50):
    """
    Načte z ml_dataset poslední batch pro daný symbol a provede partial_fit.
    Uloží/aktualizuje model na ai/models/current_online/<SYMBOL>.pkl
    """
    if not DATASET.exists():
        return None
    df = pd.read_csv(DATASET)
    if df.empty:
        return None
    df = df[df["symbol"]==symbol].dropna(subset=["y"])
    if df.empty or len(df) < min_labels:
        return None

    # class balance guard
    c0 = (df["y"]==0).sum(); c1 = (df["y"]==1).sum()
    if c0 < min_per_class or c1 < min_per_class:
        return None

    df = df.tail(batch_size)
    X = df[FEATURE_COLUMNS]
    y = df["y"].astype(int).values

    model_path = _sym_path(symbol)
    if model_path.exists():
        try:
            clf = joblib.load(model_path)
        except Exception:
            clf = None
    else:
        clf = None

    if clf is None:
        clf = Pipeline([
            ("imp", SimpleImputer()),
            ("sc", StandardScaler(with_mean=False)),
            ("sgd", SGDClassifier(loss="log_loss", class_weight="balanced", random_state=42))
        ])
        # warm start: první partial_fit musí znát třídy
        clf.named_steps["sgd"].partial_fit(np.zeros((1, X.shape[1])), np.array([0]), classes=np.array([0,1]))

    # train
    try:
        clf.named_steps["sgd"].partial_fit(X.fillna(0.0).values, y)
    except Exception:
        clf.fit(X, y)

    joblib.dump(clf, model_path)
    return True
