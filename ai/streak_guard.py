import os, json, time, pathlib
from collections import deque
from typing import Deque

STATE_FILE = pathlib.Path(os.getenv("STREAK_GUARD_FILE", "logs/streak_guard.json"))
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

# =========================
# KONFIGURACE
# =========================
COOLDOWN_AFTER_LOSS_N = int(os.getenv("COOLDOWN_AFTER_LOSS_N", "3"))
COOLDOWN_MINUTES      = int(os.getenv("COOLDOWN_MINUTES", "25"))
MAX_ADX_SHIFT         = float(os.getenv("MAX_ADX_SHIFT", "2"))
MAX_AI_TIGHTEN        = float(os.getenv("MAX_AI_TIGHTEN", "6"))
MAX_SR_SHIFT          = float(os.getenv("MAX_SR_SHIFT", "0.15"))
RSI_TIGHTEN_STEP      = float(os.getenv("RSI_TIGHTEN_STEP", "2.0"))

# =========================
# PAMĚŤ / STAV
# =========================
_state = {
    # ukládáme jen statusy ("WIN"/"LOSS"), symbol/side zatím nepotřebujeme
    "recent": deque(maxlen=20),    # poslední výsledky
    "guard_active": False,
    "guard_until": 0.0,
    "last_loss_ts": 0.0,
    "adjust": {
        "adx_bonus": 0.0,
        "ai_raise": 0.0,
        "sr_tighten": 0.0,
        "rsi_tighten": 0.0,
    },
}

# =========================
# ULOŽENÍ / NAČTENÍ
# =========================
def _save():
    try:
        data = dict(_state)
        data["recent"] = list(_state["recent"])
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def _load():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # recent přetvoříme zpět na deque
                if isinstance(data.get("recent"), list):
                    _state["recent"] = deque(data["recent"], maxlen=20)
                data.pop("recent", None)
                _state.update(data)
        except Exception:
            pass

_load()

# =========================
# HLAVNÍ FUNKCE
# =========================
def record_result(symbol: str, side: str, status: str):
    """
    API volané z analyzer.record_result(symbol, side, status).

    Zajímá nás jen status:
      - přidáme do fronty recent
      - když přijde COOLDOWN_AFTER_LOSS_N proher po sobě,
        zapneme guard + zpřísníme prahy.
    """
    now = time.time()
    status = (status or "").upper()
    if status not in ("WIN", "LOSS"):
        return

    _state["recent"].append(status)

    if status == "LOSS":
        _state["last_loss_ts"] = now

    losses = list(_state["recent"])[-COOLDOWN_AFTER_LOSS_N:]
    if len(losses) == COOLDOWN_AFTER_LOSS_N and all(x == "LOSS" for x in losses):
        # zapnout guard na COOLDOWN_MINUTES dopředu
        _state["guard_active"] = True
        _state["guard_until"] = now + COOLDOWN_MINUTES * 60

        # zpřísnění:
        # - vyšší ADX/AI prahy
        # - menší tolerovaná vzdálenost od SR (pozitivní hodnota → analyzer pak odečte)
        # - přísnější RSI pásma (analyzer může využít rsi_tighten)
        _state["adjust"] = {
            "adx_bonus":   float(MAX_ADX_SHIFT),
            "ai_raise":    float(MAX_AI_TIGHTEN),
            "sr_tighten":  float(MAX_SR_SHIFT),
            "rsi_tighten": float(RSI_TIGHTEN_STEP),
        }

    _save()

def _check_guard() -> bool:
    """
    Zkontroluje, jestli cooldown stále běží.
    Když doběhne, guard se vypne a úpravy se vynulují.
    """
    now = time.time()
    if _state["guard_active"] and now >= _state["guard_until"]:
        _state["guard_active"] = False
        _state["adjust"] = {
            "adx_bonus": 0.0,
            "ai_raise": 0.0,
            "sr_tighten": 0.0,
            "rsi_tighten": 0.0,
        }
        _save()
    return _state["guard_active"]

# =========================
# VEŘEJNÉ API PRO ANALYZÉR
# =========================
def get_streak_adjustments():
    """
    Vrací objekt s úpravami během šňůry proher:
      - active: jestli je cooldown aktivní
      - adx_bonus: o kolik zvýšit ADX prah
      - ai_raise: o kolik zvýšit AI skóre minimum
      - sr_tighten: o kolik zmenšit povolenou SR vzdálenost (analyzer dělá sr_eff -= sr_tighten)
      - rsi_tighten: o kolik „přitvrdit“ RSI pásma (analyzer to může použít)
    """
    _check_guard()
    adj = _state["adjust"]

    class Guard:
        active      = bool(_state["guard_active"])
        adx_bonus   = float(adj.get("adx_bonus", 0.0))
        ai_raise    = float(adj.get("ai_raise", 0.0))
        sr_tighten  = float(adj.get("sr_tighten", 0.0))
        rsi_tighten = float(adj.get("rsi_tighten", 0.0))

    return Guard()
