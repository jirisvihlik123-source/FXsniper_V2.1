import re
import unicodedata

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
# UTIL: NORMALIZACE TEXTU
# ======================

def normalize(text: str) -> str:
    # odstraní emoji a zvláštní znaky
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s\.\|\:\-\+]", " ", text)
    return text.upper()

# ======================
# OPEN ALERT
# ======================

def parse_open(message: str):
    text = normalize(message)

    # OPEN nesmí být CLOSED
    if "CLOSED" in text:
        return None

    # AI
    ai_match = re.search(r"\bAI\s*(\d+)", text)
    # ADX
    adx_match = re.search(r"\bADX\s*([\d\.]+)", text)

    if not ai_match or not adx_match:
        return None

    pair = next((p for p in PAIRS if p in text), None)
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
    text = normalize(message)

    if "CLOSED" not in text:
        return None

    # WON / WIN / LOSS / LOST
    result_match = re.search(r"\b(WON|WIN|LOSS|LOST)\b", text)
    if not result_match:
        return None

    raw = result_match.group(1)
    result = "WIN" if raw in ("WIN", "WON") else "LOST"

    pair = next((p for p in PAIRS if p in text), None)
    if not pair:
        return None

    return {
        "pair": pair,
        "result": result,
    }
