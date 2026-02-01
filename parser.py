import re


def parse_open(message: str):
    """
    Parsuje OPEN alert (LONG / SHORT)
    """

    open_match = re.search(
        r"(EURUSD|GBPUSD|GBPJPY|USDJPY|USDCAD|AUDCAD|EURGBP)\s+(M\d+)\s+–\s+(LONG|SHORT)",
        message
    )
    if not open_match:
        return None

    entry = re.search(r"Entry:\s*([\d.]+)", message)
    sl_pips = re.search(r"\(([\d.]+)\s*pips\)", message)
    rrr = re.search(r"RRR\s*([\d.]+)", message)
    ai = re.search(r"AI\s*(\d+)", message)
    adx = re.search(r"ADX\s*([\d.]+)", message)
    adx_delta = re.search(r"ADXΔ\s*([+\-]?[\d.]+)", message)

    if not (entry and sl_pips and rrr and ai and adx):
        return None

    return {
        "pair": open_match.group(1),
        "timeframe": open_match.group(2),
        "side": open_match.group(3),
        "entry": float(entry.group(1)),
        "sl_pips": float(sl_pips.group(1)),
        "rrr": float(rrr.group(1)),
        "ai": float(ai.group(1)),
        "adx": float(adx.group(1)),
        "adx_delta": float(adx_delta.group(1)) if adx_delta else None,
    }


def parse_close(message: str):
    """
    Parsuje CLOSED → WIN / LOSS
    """

    close_match = re.search(
        r"(EURUSD|GBPUSD|GBPJPY|USDJPY|USDCAD|AUDCAD|EURGBP)\s+(M\d+)\s+(LONG|SHORT)\s+CLOSED.*?(WON|WIN|LOST|LOSS)",
        message,
        re.IGNORECASE
    )

    if not close_match:
        return None

    result_raw = close_match.group(4).upper()
    result = "WIN" if result_raw in ("WIN", "WON") else "LOSS"

    entry = re.search(r"Entry\s*([\d.]+)", message)

    return {
        "pair": close_match.group(1),
        "timeframe": close_match.group(2),
        "side": close_match.group(3),
        "entry": float(entry.group(1)) if entry else None,
        "result": result,
    }
