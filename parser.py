import re
import unicodedata

PAIRS = [
    "EURUSD","GBPUSD","USDJPY","USDCAD",
    "AUDCAD","EURGBP","GBPJPY","USDCHF"
]

def normalize(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.upper()

def parse_open(text):
    t = normalize(text)
    if "CLOSED" in t:
        return None

    ai = re.search(r"\bAI\b\s*[:=]?\s*(\d+)", t)
    adx = re.search(r"\bADX\b\s*[:=]?\s*([\d.]+)", t)
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

    if "LOST" in t:
        result = "LOSS"
    elif "WIN" in t or "WON" in t:
        result = "WIN"
    else:
        if "❌" in text:
            result = "LOSS"
        elif "✅" in text:
            result = "WIN"
        else:
            return None

    return {"pair": pair, "result": result}
