from __future__ import annotations
import argparse, math
from pathlib import Path
import pandas as pd

from ai.scorer import AIScorer

def build_feat_dict(row: pd.Series, keys: list[str]) -> dict:
    d = {}
    for k in keys:
        if k in row and pd.notna(row[k]):
            try:
                d[k] = float(row[k])
            except Exception:
                d[k] = 0.0
        else:
            d[k] = 0.0
    return d

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in",  dest="inp",  required=True, help="vstupní CSV (např. dream_out.csv)")
    ap.add_argument("--out", dest="out",  required=True, help="výstupní CSV (např. dream_scored.csv)")
    ap.add_argument("--model", default="ai/model.pkl", help="cesta k modelu (joblib)")
    ap.add_argument("--head", type=int, default=0, help="ukázat prvních N řádků po skóringu")
    args = ap.parse_args()

    inp  = Path(args.inp)
    outp = Path(args.out)

    print(f"[LOAD] {inp}")
    df = pd.read_csv(inp)
    if df.empty:
        print("[WARN] vstup prázdný")
        df.to_csv(outp, index=False)
        return

    sc = AIScorer(args.model)
    keys = sc.feature_order  # pořadí vstupních feature
    print(f"[INFO] numeric keys: {len(keys)} [{', '.join(keys)}]")

    scores = []
    for _, r in df.iterrows():
        feat = build_feat_dict(r, keys)
        s = sc.score(feat)
        scores.append(round(float(s), 1))

    df["ai_score_model"] = scores
    if "ai_score_at_event" not in df.columns:
        df["ai_score_at_event"] = df["ai_score_model"]

    outp.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(outp, index=False)
    print(f"[SAVED] {outp} rows={len(df)}")

    if args.head > 0:
        print(df.head(args.head).to_string(index=False))

if __name__ == "__main__":
    main()
