import re

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "USDCAD", "AUDCAD", "EURGBP"]


def parse_signal(message: str):
    """
    Parsuje pouze UZAVŘENÉ obchody:
    CLOSED → WIN / LOST
    """

    result_match = re.search(r"CLOSED\s*→\s*(WIN|LOST)", message)
    ai_match = re.search(r"AI\s*(\d+)", message)
    adx_match = re.search(r"ADX\s*([\d.]+)", message)

    pair = None
    for p in PAIRS:
        if p in message:
            pair = p
            break

    if not (result_match and ai_match and adx_match and pair):
        return None

    return {
        "pair": pair,
        "ai": float(ai_match.group(1)),
        "adx": float(adx_match.group(1)),
        "result": result_match.group(1),
    }

