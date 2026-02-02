import re

PAIRS = [
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCAD",
    "AUDCAD",
    "EURGBP",
    "GBPJPY",
    "USDCHF",
]

# ======================
# OPEN ALERT
# ======================

def parse_open(message: str):
    """
    Parsuje OPEN alerty:
    - obsahují AI a ADX
    - NESMÍ obsahovat CLOSED
    """

    text = message.upper()

    # OPEN nesmí být CLOSED
    if "CLOSED" in text:
        return None

    ai_match = re.search(r"AI\s*(\d+)", text)
    adx_match = re.search(r"ADX\s*([\d.]+)", text)

    if not ai_match or not adx_match:
        return None

    pair = None
    for p in PAIRS:
        if p in text:
            pair = p
            break

    if not pair:
        return None

    return {
        "pair": pair,
        "ai": float(ai_match.group(1)),
        "adx": float(adx_match.group(1)),
    }

# ======================
# CLOSED ALERT
# ======================

def parse_closed(message: str):
    """
    Parsuje CLOSED alerty:
    - WIN / LOSS / LOST
    """

    text = message.upper()

    if "CLOSED" not in text:
        return None

    result_match = re.search(r"(WIN|LOSS|LOST)", text)
    if not result_match:
        return None

    result_raw = result_match.group(1)
    result = "WIN" if result_raw == "WIN" else "LOST"

    pair = None
    for p in PAIRS:
        if p in text:
            pair = p
            break

    if not pair:
        return None

    return {
        "pair": pair,
        "result": result,
    }
