
def pip_value(symbol: str) -> float:
    # Approximate pip value per 1.00 lot (standard lot) in USD
    # USD-quoted pairs (EURUSD, GBPUSD, etc.): ~$10 per pip
    # JPY pairs ~ $9 per pip (approx depends on price)
    if symbol.upper().endswith("JPY"):
        return 9.0
    return 10.0

def position_size(balance: float, risk_pct: float, sl_pips: float, symbol: str) -> float:
    risk_amount = balance * (risk_pct / 100.0)
    per_lot_pip_value = pip_value(symbol)
    # lot size = risk_amount / (sl_pips * pip_value_per_lot)
    lots = risk_amount / max(sl_pips * per_lot_pip_value, 1e-9)
    return max(lots, 0.0)
