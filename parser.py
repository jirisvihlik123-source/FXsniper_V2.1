import re

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "USDCAD", "AUDCAD", "EURGBP", "GBPJPY", "USDCHF"]

def parse_open(message: str):
    text = message.upper()

    ai = re.search(r"AI\s*(\d+)", text)
    adx = re.search(r"ADX\s*([\d.]+)", text)

    if not ai or not adx:
        return None

    pair = next((p for p in PAIRS if p in text), None)
    if not pair:
        return None

    # OPEN alert = má AI + ADX, ale NEMÁ CLOSED
    if "CLOSED" in text:
        return None

    return {
        "pair": pair,
        "ai": float(ai.group(1)),
        "adx": float(adx.group(1)),
    }


def parse_closed(message: str):
    text = message.upper()

    if "CLOSED" not in text:
        return None

    result_match = re.search(r"(WIN|LOSS|LOST)", text)
    if not result_match:
        return None

    result = "WIN" if result_match.group(1) == "WIN" else "LOST"
    pair = next((p for p in PAIRS if p in text), None)

    if not pair:
        return None

    return {
        "pair": pair,
        "result": result,
    }
ch.group(1)),
        "result": result,
    }
