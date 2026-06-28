
import os
import requests
import pandas as pd

API_KEY = os.getenv("TWELVE_API_KEY")
BASE_URL = "https://api.twelvedata.com"

class DataError(Exception):
    pass

def map_timeframe(tf: str) -> str:
    tf = tf.strip().upper()
    mapping = {
        "M1": "1min",
        "M5": "5min",
        "M15": "15min",
        "M30": "30min",
        "H1": "1h",
        "H4": "4h",
        "D": "1day",
        "1MIN": "1min",
        "5MIN": "5min",
        "15MIN": "15min",
        "30MIN": "30min",
        "1H": "1h",
        "4H": "4h",
        "1D": "1day",
    }
    if tf in mapping:
        return mapping[tf]
    raise ValueError(f"Unsupported timeframe: {tf}")

def fetch_timeseries(symbol: str, timeframe: str = "5min", outputsize: int = 500) -> pd.DataFrame:
    if not API_KEY:
        raise DataError("TWELVE_API_KEY is not set.")
    params = {
        "symbol": symbol,
        "interval": timeframe,
        "outputsize": outputsize,
        "apikey": API_KEY,
        "format": "JSON",
        "dp": "5",  # 5 decimal places when applicable
    }
    r = requests.get(f"{BASE_URL}/time_series", params=params, timeout=25)
    try:
        data = r.json()
    except Exception as e:
        raise DataError(f"Bad JSON from API: {e}")
    if "values" not in data:
        raise DataError(data.get("message", "No 'values' in response."))
    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.sort_values("datetime").reset_index(drop=True)
    return df
