# ai/tuner_runtime.py
import json, pathlib, time
from collections import deque

STATE_FILE = pathlib.Path("logs/tuner_state.json")
STATE_FILE.parent.mkdir(exist_ok=True)

# parametry
WINDOW = 20               # kolik posledních výsledků hodnotíme
TARGET_WR = 55            # cílová winrate
MAX_SHIFT = 8.0           # max zpřísnění AI/ADX
MAX_SR_SHIFT = 0.20       # max zpřísnění/povolení SR
ADAPT_STEP = 0.6          # krok adaptace
COOLDOWN_AFTER_LOSS_N = 3 # po 3 prohrách zpřísníme na 25 minut
COOLDOWN_MINUTES = 25*60  # 25 min

# runtime stav
_state = {
    "recent": deque(maxlen=WINDOW),   # posledních 20 WIN/LOSS
    "ai_shift": 0.0,
    "adx_boost": 0.0,
    "sr_tighten": 0.0,
    "cooldown_until": 0,
    "last_update": None
}

def _save():
    data = dict(_state)
    data["recent"] = list(_state["recent"])
    with open(STATE_FILE,"w") as f:
        json.dump(data,f,indent=2)

def _load():
    if STATE_FILE.exists():
        try:
            data = json.load(open(STATE_FILE))
            _state.update(data)
            if isinstance(data.get("recent"), list):
                _state["recent"] = deque(data["recent"], maxlen=WINDOW)
        except:
            pass

_load()

def get_adjustments():
    """Analyzer očekává objekt s atributy: ai_shift, adx_boost, sr_tighten."""
    class A:
        ai_shift = float(_state["ai_shift"])
        adx_boost = float(_state["adx_boost"])
        sr_tighten = float(_state["sr_tighten"])
    return A()

def apply_result(symbol: str, side: str, status: str):
    """Ukotvení výsledku a adaptace prahů."""
    now = time.time()
    s = status.upper()

    # přidej výsledek
    _state["recent"].append(s)

    # cooldown trigger
    if s == "LOSS" and len(_state["recent"]) >= COOLDOWN_AFTER_LOSS_N:
        if all(x == "LOSS" for x in list(_state["recent"])[-COOLDOWN_AFTER_LOSS_N:]):
            _state["cooldown_until"] = now + COOLDOWN_MINUTES

    # pokud málo dat → nic neupravujeme
    if len(_state["recent"]) < WINDOW:
        _save()
        return

    # winrate
    wr = 100 * sum(1 for x in _state["recent"] if x == "WIN") / len(_state["recent"])

    delta = wr - TARGET_WR

    # adaptace
    if wr < TARGET_WR:
        # zhoršení → zpřísnit
        _state["ai_shift"]     = min(MAX_SHIFT,     _state["ai_shift"]     + ADAPT_STEP)
        _state["adx_boost"]    = min(MAX_SHIFT,     _state["adx_boost"]    + ADAPT_STEP)
        _state["sr_tighten"]   = min(MAX_SR_SHIFT,  _state["sr_tighten"]   + ADAPT_STEP*0.2)
    else:
        # zlepšení → povolit
        _state["ai_shift"]     = max(0.0, _state["ai_shift"]     - ADAPT_STEP*0.5)
        _state["adx_boost"]    = max(0.0, _state["adx_boost"]    - ADAPT_STEP*0.5)
        _state["sr_tighten"]   = max(0.0, _state["sr_tighten"]   - ADAPT_STEP*0.2)

    _state["last_update"] = time.time()
    _save()
