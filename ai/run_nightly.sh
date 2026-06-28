set -euo pipefail

# aktivuj venv + přepni do rootu projektu
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$ROOT_DIR/.venv/bin/activate"
cd "$ROOT_DIR"

echo "[RUN] $(date -u +"%Y-%m-%d %H:%M:%S") UTC začínám…"

# 1) merge logů (pokud něco chybí, jen varuje)
python ai/dream.py \
  --logs logs \
  --out dream_out.csv \
  --csv dream_out.csv \
  --head 0

# 2) natrénuj model (uloží ai/model.pkl)
python ai/train_model.py

# 3) nascoreuj všechny řádky (přidá ai_score_model)
python ai/score_csv.py --in dream_out.csv --out dream_scored.csv --head 0

# 4) udělej feedback (ai/brain_memory.csv + ai/brain_summary.json)
python ai/brain_feedback.py

# 5) pošli přehled do Telegramu (použije vložené tokeny v brain_to_telegram.py)
python ai/brain_to_telegram.py

echo "[DONE] $(date -u +"%Y-%m-%d %H:%M:%S") UTC hotovo."
