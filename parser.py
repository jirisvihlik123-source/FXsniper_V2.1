import re
import unicodedata

PAIRS = [
    "EURUSD","GBPUSD","USDJPY","USDCAD",
    "AUDCAD","EURGBP","GBPJPY","USDCHF"
]

def normalize(text):
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.upper()

def parse_open(text):
    t = normalize(text)
    if "CLOSED" in t:
        return None

    ai = re.search(r"AI\s*(\d+)", t)
    adx = re.search(r"ADX\s*([\d.]+)", t)
    pair = next((p for p in PAIRS if p in t), None)

    if not (ai and adx and pair):
        return None

    return {
        "pair": pair,
        "ai": float(ai.group(1)),
        "adx": float(adx.group(1))
    }

def parse_closed(text):
    t = normalize(text)
    if "CLOSED" not in t:
        return None

    pair = next((p for p in PAIRS if p in t), None)
    if not pair:
        return None

    result = "WIN" if "WON" in t or "WIN" in t else "LOST"
    return {"pair": pair, "result": result}
