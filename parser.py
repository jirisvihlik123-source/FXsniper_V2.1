import re
import unicodedata

PAIRS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCAD",
    "AUDCAD", "EURGBP", "GBPJPY", "USDCHF"
]

def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.upper()

def parse_open(text: str):
    t = normalize(text)
    if "CLOSED" in t:
        return None

    # tolerantní: AI 70, AI:70, AI_SCORE 70...
    ai = re.search(r"\bAI(?:_SCORE)?\b\s*[:=]?\s*(\d{1,3})\b", t)
    adx = re.search(r"\bADX\b\s*[:=]?\s*([\d.]+)\b", t)

    pair = next((p for p in PAIRS if p in t), None)

    if not (ai and adx and pair):
        return None

    try:
        ai_v = float(ai.group(1))
        adx_v = float(adx.group(1))
    except Exception:
        return None

    return {"pair": pair, "ai": ai_v, "adx": adx_v}

def parse_closed(text: str):
    t = normalize(text)
    if "CLOSED" not in t:
        return None

    pair = next((p for p in PAIRS if p in t), None)
    if not pair:
        return None

    # sjednocení výsledků: WIN / LOSS
    if ("WON" in t) or (" WIN" in t) or ("✅" in t):
        result = "WIN"
    elif ("LOSS" in t) or ("LOST" in t) or ("❌" in t):
        result = "LOSS"
    else:
        # když si nejsme jistí, radši nic (aby to nedělalo bordel)
        return None

    return {"pair": pair, "result": result}
