import pandas as pd, numpy as np, json, os
from pathlib import Path

DATA = os.getenv("DREAM_SCORED_CSV", "dream_scored.csv")
OUT  = os.getenv("BRAIN_MEMORY_CSV", "ai/brain_memory.csv")

df = pd.read_csv(DATA)

# status normalize
if "status" not in df.columns:
    raise SystemExit("[ERR] Missing column: status")

df["status"] = df["status"].astype(str).str.upper().replace({"LOST": "LOSS"})
df = df[df["status"].isin(["WIN", "LOSS"])].copy()
if df.empty:
    raise SystemExit("[ERR] No valid trades with WIN/LOSS status.")

# score column autodetect (kvůli realitě: někdy je to ai_score, jindy ai_score_model atd.)
score_col = None
for c in ("ai_score_model", "ai_score", "score", "brain_score", "final_score"):
    if c in df.columns:
        score_col = c
        break
if not score_col:
    raise SystemExit("[ERR] No score column found (expected ai_score_model / ai_score / score / brain_score / final_score)")

df[score_col] = pd.to_numeric(df[score_col], errors="coerce")
df = df.dropna(subset=[score_col]).copy()
if df.empty:
    raise SystemExit("[ERR] No rows with numeric score.")

df["bin"] = (df[score_col] // 5) * 5
stats = df.groupby("bin")["status"].apply(lambda x: (x == "WIN").mean() * 100).reset_index()
stats.columns = ["score_bin", "winrate"]

print("[INFO] Winrate by AI score:")
print(stats)

avg_winrate = stats["winrate"].mean()
best_bin = stats.loc[stats["winrate"].idxmax()]
low_bin = stats.loc[stats["winrate"].idxmin()]

summary = {
    "avg_winrate": float(avg_winrate),
    "best_bin": int(best_bin["score_bin"]),
    "best_winrate": float(best_bin["winrate"]),
    "worst_bin": int(low_bin["score_bin"]),
    "worst_winrate": float(low_bin["winrate"]),
    "bins": stats.to_dict(orient="records")
}

Path("ai").mkdir(exist_ok=True)
pd.DataFrame(summary["bins"]).to_csv(OUT, index=False)
with open("ai/brain_summary.json", "w") as f:
    json.dump(summary, f, indent=2)

print("\n[SAVED] ai/brain_memory.csv & ai/brain_summary.json")
print(json.dumps(summary, indent=2))
