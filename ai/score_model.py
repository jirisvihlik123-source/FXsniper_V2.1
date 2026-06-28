from __future__ import annotations
import joblib, pandas as pd, numpy as np
from pathlib import Path

DATA = Path("dream_out.csv")
OUT  = Path("dream_scored.csv")
MODEL = Path("ai/model.pkl")

bundle = joblib.load(MODEL)
pipe   = bundle["model"]
order  = bundle["feature_order"]

df = pd.read_csv(DATA).copy()

# znovu vyrobte featury stejně jako v tréninku (jednoduše: pokud chybí sloupce → doplň 0)
for c in order:
    if c not in df.columns:
        df[c] = 0

X = df[order].replace([np.inf,-np.inf], np.nan).fillna(0.0)
for c in X.columns:
    if not pd.api.types.is_numeric_dtype(X[c]):
        X[c] = pd.to_numeric(X[c], errors="coerce").fillna(0.0)

proba = pipe.predict_proba(X)[:,1]
df["ai_score_model"] = (proba * 100.0).round(1)

df.to_csv(OUT, index=False)
print(f"[saved] {OUT} rows={len(df)}")
