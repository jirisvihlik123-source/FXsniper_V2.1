
from typing import List, Tuple
import pandas as pd

def analyze_frame(df: pd.DataFrame, symbol: str) -> Tuple[str, List[str], str]:
    if len(df) < 210:
        return (f"{symbol}: not enough candles to analyze.", [], "Add more data or use higher timeframe.")
    last = df.iloc[-1]
    prev = df.iloc[-2]

    price = float(last["close"])
    ema50 = float(last.get("ema50") or 0)
    ema200 = float(last.get("ema200") or 0)
    rsi = float(last.get("rsi") or 50)

    # Trend & crosses
    if ema50 > ema200:
        trend = "up"
    elif ema50 < ema200:
        trend = "down"
    else:
        trend = "flat"

    crossed_up = (float(prev.get("ema50") or 0) < float(prev.get("ema200") or 0)) and (ema50 > ema200)
    crossed_down = (float(prev.get("ema50") or 0) > float(prev.get("ema200") or 0)) and (ema50 < ema200)

    bullets = []
    if crossed_up:
        bullets.append("Bullish EMA50/200 cross ↑")
    if crossed_down:
        bullets.append("Bearish EMA50/200 cross ↓")
    if rsi < 30:
        bullets.append("RSI oversold (<30)")
    if rsi > 70:
        bullets.append("RSI overbought (>70)")

    # Simple suggestion
    if trend == "up" and rsi <= 60:
        idea = "Bias: LONG on pullback to EMA50. Wait for rejection candle."
    elif trend == "down" and rsi >= 40:
        idea = "Bias: SHORT on pullback to EMA50. Wait for rejection candle."
    elif crossed_up:
        idea = "Possible new uptrend. Consider LONG after retest of the cross zone."
    elif crossed_down:
        idea = "Possible new downtrend. Consider SHORT after retest of the cross zone."
    else:
        idea = "No high-conviction setup right now. Patience."

    header = f"{symbol} @ {price:.5f} | Trend: {trend.upper()} | RSI: {rsi:.1f} | EMA50: {ema50:.5f} | EMA200: {ema200:.5f}"
    return header, bullets, idea
