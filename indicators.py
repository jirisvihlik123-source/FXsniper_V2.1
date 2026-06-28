import pandas as pd
import pandas_ta as ta

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Přidá všechny indikátory, které analyzer očekává:
      - ema50, ema200
      - rsi (14)
      - atr (14)
      - adx (14)
    """
    out = df.copy()

    # EMA
    out["ema50"] = ta.ema(out["close"], length=50)
    out["ema200"] = ta.ema(out["close"], length=200)

    # RSI
    out["rsi"] = ta.rsi(out["close"], length=14)

    # ATR (v absolutní cenové hodnotě – analyzer si to pak přepočítává na pity)
    out["atr"] = ta.atr(high=out["high"], low=out["low"], close=out["close"], length=14)

    # ADX – pandas_ta vrací víc sloupců, my potřebujeme čistě ADX
    adx_df = ta.adx(high=out["high"], low=out["low"], close=out["close"], length=14)
    if adx_df is not None:
        # typicky ADX_14
        adx_col = [c for c in adx_df.columns if "ADX_" in c]
        if adx_col:
            out["adx"] = adx_df[adx_col[0]]
        else:
            # fallback: když by se něco změnilo v knihovně
            out["adx"] = adx_df.iloc[:, 0]
    else:
        out["adx"] = None

    return out
