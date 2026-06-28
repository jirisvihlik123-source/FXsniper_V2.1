from __future__ import annotations
import joblib, pandas as pd, numpy as np
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.metrics import classification_report, roc_auc_score

DATA_PATH = Path("dream_out.csv")
MODEL_PATH = Path("ai/model.pkl")

print(f"[LOAD] {DATA_PATH}")
df = pd.read_csv(DATA_PATH)

# ----- label (WON/LOST -> 1/0) -----
y = None
if "status" in df.columns:
    lab = df["status"].astype(str).str.upper().map({"WON":1, "LOST":0})
    if lab.notna().any():
        y = lab
if y is None and "outcome" in df.columns:
    y = pd.to_numeric(df["outcome"], errors="coerce")
if y is None:
    raise SystemExit("[ERR] Nenalezen label (status/outcome).")

df = df[y.notna()].copy()
y  = y.loc[df.index].astype(int)

# ----- candidates by prefix -----
CANDIDATES = [
    "adx", "atr", "rsi", "htf_trend", "near_sr",
    "fvg_present", "wick_ratio", "range_atr", "session",
    "ema50", "ema200", "engulf", "pinbar", "vol_pctl"
]

def find_cols(d: pd.DataFrame, keys):
    cols = []
    for k in keys:
        cols += [c for c in d.columns if c.startswith(k)]
    # odfiltruj zjevné ID a textové poznámky
    drop_like = ("notes", "reason", "chat_id", "event_id", "trade_id", "meta_json")
    cols = [c for c in cols if not any(p in c for p in drop_like)]
    return sorted(set(cols))

Xcols_raw = find_cols(df, CANDIDATES)
if len(Xcols_raw) < 3:
    print("[ERR] Málo featur. Dostupné sloupce:", df.columns.tolist())
    raise SystemExit(1)

print("[OK] Kandidátní featury:", Xcols_raw)

X = df[Xcols_raw].copy()

# ----- převod ne-numerických sloupců -----
bin_maps = {
    "true":1, "false":0, "yes":1, "no":0, "y":1, "n":0,
    "present":1, "absent":0, "near":1, "far":0, "none":0, "null":0, "nan":0,
}

num_cols, cat_cols, dropped = [], [], []

for c in X.columns:
    if pd.api.types.is_numeric_dtype(X[c]):
        num_cols.append(c)
        continue

    s = X[c].astype(str).str.strip().str.lower()

    # 1) pokus o binární mapování
    if s.isin(bin_maps.keys()).mean() > 0.9:
        X[c] = s.map(bin_maps).astype(float).fillna(0)
        num_cols.append(c)
        continue

    # 2) málo kategorií → one-hot
    nunique = int(s.nunique(dropna=True))
    if 1 < nunique <= 8:
        dummies = pd.get_dummies(s, prefix=c, dummy_na=False)
        X = pd.concat([X.drop(columns=[c]), dummies], axis=1)
        cat_cols.append(c)
        continue

    # 3) poslední pokus: to_numeric
    tmp = pd.to_numeric(X[c], errors="coerce")
    if tmp.notna().mean() > 0.8:
        X[c] = tmp.fillna(0.0)
        num_cols.append(c)
    else:
        dropped.append(c)
        X = X.drop(columns=[c])

# finální čištění
X = X.replace([np.inf, -np.inf], np.nan).fillna(0.0)
for c in X.columns:
    if not pd.api.types.is_numeric_dtype(X[c]):
        # safety: cokoliv co zbylo ještě přeparsovat
        X[c] = pd.to_numeric(X[c], errors="coerce").fillna(0.0)

if X.shape[1] < 3:
    raise SystemExit("[ERR] Po čištění zbylo méně než 3 numerické featury.")

print(f"[INFO] numeric cols: {len(num_cols)} | one-hot cols: {len(cat_cols)} | dropped: {dropped}")

# ----- train/test -----
Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, random_state=42, stratify=y)

pipe = Pipeline([
    ("scaler", StandardScaler(with_mean=True, with_std=True)),
    ("clf", LogisticRegression(max_iter=300, solver="lbfgs"))
])

pipe.fit(Xtr, ytr)
pred  = pipe.predict(Xte)
proba = pipe.predict_proba(Xte)[:,1]

print("\n=== EVAL ===")
print(classification_report(yte, pred, digits=3))
try:
    print("ROC-AUC:", roc_auc_score(yte, proba))
except Exception as e:
    print("AUC error:", e)

MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
joblib.dump({"model":pipe, "feature_order":list(X.columns)}, MODEL_PATH)
print(f"\n[saved] model: {MODEL_PATH} (features: {list(X.columns)})")
