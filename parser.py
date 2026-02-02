import re

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "USDCAD", "AUDCAD", "EURGBP"]


def parse_signal(message: str):
    """
    Parsuje UZAVŘENÉ obchody (WIN / LOSS / LOST)
    """

    text = message.upper()

    # výsledek obchodu – tolerantní
    result_match = re.search(r"CLOSED.*?(WIN|LOSS|LOST)", text)
    if not result_match:
        return None

    raw_result = result_match.group(1)
    result = "WIN" if raw_result == "WIN" else "LOST"

    # AI a ADX
    ai_match = re.search(r"AI\s*(\d+)", text)
    adx_match = re.search(r"ADX\s*([\d.]+)", text)

    if not ai_match or not adx_match:
        return None

    # měnový pár
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
        "result": result,
    }
