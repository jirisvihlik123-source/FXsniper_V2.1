import re
import unicodedata

PAIRS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCAD",
    "AUDCAD", "EURGBP", "GBPJPY", "USDCHF"
]

def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s\.\|\:\-\+]", " ", text)
    return text.upper()

def parse_open(message: str):
    text = normalize(message)

    if "CLOSED" in text:
        return None

    ai = re.search(r"\bAI\s*(\d+)", text)
    adx = re.search(r"\bADX\s*([\d.]+)", text)

    if not ai or not adx:
        return None

    pair = next((p for p in PAIRS if p in text), None)
    if not pair:
        return None

    return {
        "pair": pair,
        "ai": float(ai.group(1)),
        "adx": float(adx.group(1))
    }

def parse_closed(message: str):
    text = normalize(message)

    if "CLOSED" not in text:
        return None

    result_match = re.search(r"\b(WIN|WON|LOSS|LOST)\b", text)
    if not result_match:
        return None

    result = "WIN" if result_match.group(1) in ("WIN", "WON") else "LOST"

    pair = next((p for p in PAIRS if p in text), None)
    if not pair:
        return None

    return {
        "pair": pair,
        "result": result
    }

