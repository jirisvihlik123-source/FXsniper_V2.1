# brain_memory.py
import os, json, pathlib, time
from typing import Dict, Any

BRAIN_DB_FILE = pathlib.Path(os.getenv("BRAIN_DB_FILE", "logs/brain_memory.json"))
BRAIN_DB_FILE.parent.mkdir(parents=True, exist_ok=True)

# =========================
# Pomocné funkce
# =========================
def _load() -> Dict[str, Any]:
    if not BRAIN_DB_FILE.exists():
        return {}
    try:
        with open(BRAIN_DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save(d: Dict[str, Any]) -> None:
    try:
        with open(BRAIN_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
    except Exception:
        pass

# =========================
# Penalty výpočet
# =========================
def brain_penalty(symbol: str, side: str, meta: Dict[str, Any] | None = None) -> float:
    """
    Vrací penalizaci 0.0–1.0 podle posledních výsledků a „paměti“ pro daný symbol/směr.
    Vyšší hodnota = horší výkon = snížit důvěru (AI skóre se krátí).
    """
    d = _load()
    key = f"{symbol.upper()}_{side.upper()}"
    rec = d.get(key, {})
    losses = int(rec.get("losses", 0))
    wins   = int(rec.get("wins", 0))
    last_ts = float(rec.get("last_ts", 0))
    age_min = (time.time() - last_ts) / 60 if last_ts else 999

    if wins + losses == 0:
        return 0.0

    wr = wins / (wins + losses)
    penalty = max(0.0, min(1.0, (0.6 - wr) * 1.8))  # <60 % WR → penalizace
    # staré výsledky = menší váha penalizace
    if age_min > 180:
        penalty *= 0.5
    return round(penalty, 3)

# =========================
# Záznam obchodu
# =========================
def record_trade(symbol: str, side: str, data: Dict[str, Any]) -> None:
    """
    Aktualizuje paměť (wins/losses, timestamp, poslední výsledek).
    """
    d = _load()
    key = f"{symbol.upper()}_{side.upper()}"
    rec = d.get(key, {"wins": 0, "losses": 0})
    status = data.get("status", "").upper()

    if status == "WIN":
        rec["wins"] = rec.get("wins", 0) + 1
    elif status == "LOSS":
        rec["losses"] = rec.get("losses", 0) + 1

    rec["last_ts"] = time.time()
    rec["last_status"] = status
    d[key] = rec
    _save(d)

# =========================
# Shrnutí / reset
# =========================
def brain_summary() -> Dict[str, Any]:
    d = _load()
    total_wins = sum(v.get("wins", 0) for v in d.values())
    total_losses = sum(v.get("losses", 0) for v in d.values())
    total_trades = total_wins + total_losses
    return {
        "symbols_tracked": len(d),
        "total_trades": total_trades,
        "winrate": (total_wins / total_trades * 100.0) if total_trades else None,
        "total_wins": total_wins,
        "total_losses": total_losses,
    }

def brain_reset() -> None:
    """Vymaže celou paměť Brainu."""
    _save({})
