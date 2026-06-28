from __future__ import annotations
import os
import sys
import csv
import time
import logging
import pathlib
import httpx
import json
import asyncio
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
import datetime as dt
import uuid
from collections import deque
from datetime import timezone
from dotenv import load_dotenv

from ta.trend import EMAIndicator, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    Application,
)

HTTP_CLIENT: httpx.AsyncClient | None = None

def detect_env_duplicates(env_path: str) -> list[str]:
    seen = {}
    dupes = []
    if not os.path.exists(env_path):
        return dupes
    with open(env_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key = line.split("=", 1)[0].strip()
            if key in seen:
                dupes.append(f"{key} (line {seen[key]} and {i})")
            else:
                seen[key] = i
    return dupes

def enforce_env_hygiene(env_path: str, fail_fast: bool = True) -> None:
    dupes = detect_env_duplicates(env_path)
    if dupes:
        msg = "ENV DUPLICATES FOUND:\n" + "\n".join(f" - {d}" for d in dupes)
        print(msg)
        if fail_fast:
            print("Fix .env duplicates and restart.")
            sys.exit(1)

ENV_PATH = os.getenv("ENV_PATH", ".env")
enforce_env_hygiene(ENV_PATH, fail_fast=True)
load_dotenv(ENV_PATH, override=True)

try:
    from ai.features import extract_last_features
except Exception:
    extract_last_features = None

try:
    from ai.scorer import AIScorer
except Exception:
    AIScorer = None

try:
    from ai.execution import TradeEngine
except Exception:
    TradeEngine = None

try:
    from ai.context import scan_context
except Exception:
    def scan_context(*a, **k):
        class C:
            recent_sweep = False
            fvg_nearby = False
            bars_since_flag = 999
            recent_sweep_side = None
            fvg_side = None
        return C()

try:
    from ai.tuner_runtime import get_adjustments, apply_result
except Exception:
    def get_adjustments(*a, **k):
        class Adj:
            adx_boost = 0.0
            sr_tighten = 0.0
            hyst_add = 0.0
            ai_shift = 0.0
        return Adj()
    def apply_result(*a, **k):
        pass

try:
    from ai.streak_guard import (
        get_streak_adjustments,
        record_result as streak_record_result,
    )
except Exception:
    def get_streak_adjustments(*a, **k):
        class S:
            active = False
            adx_bonus = 0.0
            ai_raise = 0.0
            sr_tighten = 0.0
        return S()
    def streak_record_result(*a, **k):
        pass

try:
    from ai.brain_fx import brain_record_result
    from ai.brain_fx import _penalty as brain_penalty
except Exception:
    def brain_penalty(*a, **k):
        return 0.0
    def brain_record_result(*a, **k):
        pass

try:
    from ai.dream import dream_log, dream_summary
except Exception:
    def dream_log(*a, **k):
        return
    def dream_summary(days: int):
        return {
            "alert": 0,
            "alert_plus": 0,
            "headsup": 0,
            "wins": 0,
            "losses": 0,
            "winrate": 0.0,
        }

try:
    import ai.dedup as _dedup_mod
    can_emit = getattr(_dedup_mod, "can_emit", lambda *a, **k: (True, None))
    mark_emitted = getattr(_dedup_mod, "mark_emitted", lambda *a, **k: None)
    SOURCE_ANALYZER = getattr(_dedup_mod, "SOURCE_ANALYZER", "analyzer")
except Exception:
    SOURCE_ANALYZER = "analyzer"
    def can_emit(*a, **k):
        return True, None
    def mark_emitted(*a, **k):
        return

def enforce_prod_dependencies() -> None:
    missing = []

    if REQUIRE_AI_FEATURES and extract_last_features is None:
        missing.append("ai.features.extract_last_features")

    if REQUIRE_AI_SCORER and AIScorer is None:
        missing.append("ai.scorer.AIScorer")

    if REQUIRE_AI_BRAIN:
        if not BRAIN_ON:
            missing.append("BRAIN_ON=0 but REQUIRE_AI_BRAIN=1")
        else:
            mod_name = getattr(brain_penalty, "__module__", "")
            if mod_name in ("__main__", ""):
                missing.append("ai.brain_fx._penalty / brain_record_result")

    if REQUIRE_AI_DEDUP:
        dedup_mod = getattr(can_emit, "__module__", "")
        if dedup_mod in ("__main__", "") or SOURCE_ANALYZER == "analyzer":
            missing.append("ai.dedup.can_emit / mark_emitted")

    if STRICT_PROD_MODE and missing:
        msg = "STRICT_PROD_MODE failed. Missing required modules:\n" + "\n".join(f" - {m}" for m in missing)
        print(msg)
        sys.exit(1)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TWELVE_API_KEY = os.getenv("TWELVE_API_KEY", "")
OWNER_TELEGRAM_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0") or 0)

WATCHLIST = [
    s.strip().upper()
    for s in os.getenv(
        "WATCHLIST",
        "EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF",
    ).split(",")
    if s.strip()
]

BASE_TF = os.getenv("BASE_TF", "M15").upper()
REPORT_TF = os.getenv("REPORT_TF", BASE_TF).upper()
HTF_TF = os.getenv("HTF_TF", "H1").upper()

TRADING_TZ = os.getenv("TRADING_TZ", "Europe/Prague")
TRADING_HOURS = os.getenv("TRADING_HOURS", "08-18")

REALTIME_MODE = os.getenv("REALTIME_MODE", "0") == "1"
REALTIME_POLL_SEC = float(os.getenv("REALTIME_POLL_SEC", "3.0"))
USE_WEBSOCKET = os.getenv("USE_WEBSOCKET", "0") == "1"

HTF_CACHE_TTL_SEC = int(os.getenv("HTF_CACHE_TTL_SEC", "120"))
LTF_CACHE_TTL_SEC = int(os.getenv("LTF_CACHE_TTL_SEC", "5"))

ALERT_INTERVAL_SEC = int(os.getenv("ALERT_INTERVAL_SEC", "120"))
ALERTS_FIRST = int(os.getenv("ALERTS_FIRST", "10"))
REPORT_INTERVAL_SEC = int(os.getenv("REPORT_INTERVAL_SEC", "300"))
REPORT_FIRST = int(os.getenv("REPORT_FIRST", "5"))
HEALTH_INTERVAL_SEC = int(os.getenv("HEALTH_INTERVAL_SEC", "600"))
HEALTH_FIRST = int(os.getenv("HEALTH_FIRST", "30"))

REPORT_MAX_LINES = int(os.getenv("REPORT_MAX_LINES", "12"))
REPORT_STYLE = os.getenv("REPORT_STYLE", "compact").lower()

MIN_ATR_PIPS = float(os.getenv("MIN_ATR_PIPS", "1.8"))
ADX_MIN = float(os.getenv("ADX_MIN", "20"))
RSI_LO_BASE = float(os.getenv("RSI_LO", "40"))
RSI_HI_BASE = float(os.getenv("RSI_HI", "60"))
SR_LOOKBACK = int(os.getenv("SR_LOOKBACK", "60"))
SR_MAX_DIST_ATR = float(os.getenv("SR_MAX_DIST_ATR", "0.65"))
PRICE_EMA_FILTER = os.getenv("PRICE_EMA_FILTER", "1") == "1"

USE_HTF_TREND = os.getenv("USE_HTF_TREND", "1") == "1"
HTF_ADX_MIN = float(os.getenv("HTF_ADX_MIN", "18"))
HTF_TREND_METHOD = os.getenv("HTF_TREND_METHOD", "ema").lower()
HTF_EMA_CONFLUENCE = os.getenv("HTF_EMA_CONFLUENCE", "1") == "1"
ADX_STRONG = float(os.getenv("ADX_STRONG", "25"))
ATR_CHOP_RATIO_MAX = float(os.getenv("ATR_CHOP_RATIO_MAX", "0.88"))
REQUIRE_FRESH_HTF = os.getenv("REQUIRE_FRESH_HTF", "1") == "1"

AI_SCORER_ON = os.getenv("AI_SCORER_ON", "1") == "1"
AI_SCORE_MIN = float(os.getenv("AI_SCORE_MIN", "53"))
AI_HEADSUP_MIN = float(os.getenv("AI_HEADSUP_MIN", "44"))
AI_HEADSUP_ON = os.getenv("AI_HEADSUP_ON", "0") == "1"
AI_OVERRIDE_ON = os.getenv("AI_OVERRIDE_ON", "0") == "1"
AI_OVERRIDE_MIN = float(os.getenv("AI_OVERRIDE_MIN", "75"))
AI_ALERTPLUS_MIN = float(os.getenv("AI_ALERTPLUS_MIN", "70"))
ADX_ALERTPLUS = float(os.getenv("ADX_ALERTPLUS", "28"))
BRAIN_WEIGHT = float(os.getenv("BRAIN_WEIGHT", "0.20"))

BRAIN_ON = os.getenv("BRAIN_ON", "1") == "1"
BRAIN_ONLY = os.getenv("BRAIN_ONLY", "0") == "1"
BRAIN_HEADSUP_MIN = float(os.getenv("BRAIN_HEADSUP_MIN", "45"))
BRAIN_ALERT_MIN = float(os.getenv("BRAIN_ALERT_MIN", "58"))


REEMIT_MIN_ATR = float(os.getenv("REEMIT_MIN_ATR", "0.15"))
REEMIT_MIN_ATR_STRONG = float(os.getenv("REEMIT_MIN_ATR_STRONG", "0.05"))

AUTO_EXEC_ON_ENV = os.getenv("AUTO_EXEC_ON", os.getenv("AUTOEXEC_ON", "0"))
AUTOEXEC_ON = AUTO_EXEC_ON_ENV == "1"

PAPER_TRADES_ON = os.getenv("PAPER_TRADES_ON", "1") == "1"

AUTO_ALERTS_ON = os.getenv("AUTO_ALERTS_ON", "1") == "1"
AUTO_REPORT_ON = os.getenv("AUTO_REPORT_ON", "0") == "1"
HEALTH_ON = os.getenv("HEALTH_ON", "1") == "1"

AUTO_ALERTS_CHAT_ID = int(os.getenv("AUTO_ALERTS_CHAT_ID", "0") or 0)
REPORT_CHAT_ID = int(os.getenv("REPORT_CHAT_ID", "0") or 0)
HEALTH_CHAT_ID = int(os.getenv("HEALTH_CHAT_ID", "0") or 0)

DYNAMIC_RRR = os.getenv("DYNAMIC_RRR", "0") == "1"
FIXED_RRR = float(os.getenv("FIXED_RRR", "1.5"))
ATR_SL_MULT = float(os.getenv("ATR_SL_MULT", "1.15"))
ATR_TP_MULT = float(os.getenv("ATR_TP_MULT", "1.6"))
TREND_SL_MULT = float(os.getenv("TREND_SL_MULT", "1.15"))
TREND_TP_MULT = float(os.getenv("TREND_TP_MULT", "1.6"))
CHOP_SL_MULT = float(os.getenv("CHOP_SL_MULT", "1.15"))
CHOP_TP_MULT = float(os.getenv("CHOP_TP_MULT", "1.4"))
MIN_TP_PIPS = float(os.getenv("MIN_TP_PIPS", "6"))
ENTRY_OFFSET_PIPS = float(os.getenv("ENTRY_OFFSET_PIPS", "0.0"))
MARKET_ENTRY_ON = os.getenv("MARKET_ENTRY_ON", "1") == "1"
MARKET_ENTRY_ADX_MIN = float(os.getenv("MARKET_ENTRY_ADX_MIN", "18"))
SL_BUFFER_PIPS = float(os.getenv("SL_BUFFER_PIPS", "0.2"))
TP_BUFFER_PIPS = float(os.getenv("TP_BUFFER_PIPS", "0.1"))
MIN_STOP_DISTANCE_PIPS = float(os.getenv("MIN_STOP_DISTANCE_PIPS", "5.0"))
TP1_RATIO = float(os.getenv("TP1_RATIO", "0.0"))
TP2_RATIO = float(os.getenv("TP2_RATIO", "1.0"))
USE_TRAILING = os.getenv("USE_TRAILING", "0") == "1"
TRAIL_ATR_MULT = float(os.getenv("TRAIL_ATR_MULT", "0.5"))

TARGET_WINRATE = float(os.getenv("TARGET_WINRATE", "60"))
PERF_WINDOW = int(os.getenv("PERF_WINDOW", "30"))
DEDUP_MINUTES = int(os.getenv("DEDUP_MINUTES", "4"))

TRADE_RESULTS_INTERVAL_SEC = int(os.getenv("TRADE_RESULTS_INTERVAL_SEC", "10"))
TRADE_RESULTS_FIRST = int(os.getenv("TRADE_RESULTS_FIRST", "10"))

ENTRY_TIMEOUT_MINUTES = int(os.getenv("ENTRY_TIMEOUT_MINUTES", "20"))
MAX_TRADE_MINUTES = int(os.getenv("MAX_TRADE_MINUTES", "120"))

TP_SL_TIE_MODE = os.getenv("TP_SL_TIE_MODE", "loss").strip().lower()
if TP_SL_TIE_MODE not in ("loss", "win", "nearest_open"):
    TP_SL_TIE_MODE = "loss"
EXIT_ON_TOUCH = os.getenv("EXIT_ON_TOUCH", "1") == "1"

WATCHDOG_MIN_AGE_MIN = int(os.getenv("WATCHDOG_MIN_AGE_MIN", "10"))
WATCHDOG_PING_SEC = int(os.getenv("WATCHDOG_PING_SEC", "300"))
RATE_LIMIT_BACKOFF_SEC = int(os.getenv("RATE_LIMIT_BACKOFF_SEC", "60"))

DAILY_MAX_TRADES = int(os.getenv("DAILY_MAX_TRADES", "8"))
DAILY_MAX_LOSSES = int(os.getenv("DAILY_MAX_LOSSES", "3"))
DAILY_MAX_RISK_R = float(os.getenv("DAILY_MAX_RISK_R", "-3.0"))
DAILY_FROM_CSV = os.getenv("DAILY_FROM_CSV", "1") == "1"

DREAM_ON = os.getenv("DREAM_ON", "1") == "1"
DREAM_LOG_FILE = pathlib.Path(os.getenv("DREAM_LOG_FILE", "logs/dream_log.json"))
DREAM_SUMMARY_DAYS = int(os.getenv("DREAM_SUMMARY_DAYS", "7"))
DREAM_MIN_AI_SCORE = float(os.getenv("DREAM_MIN_AI_SCORE", "50"))
DREAM_TARGET_WINRATE = float(os.getenv("DREAM_TARGET_WINRATE", "60"))


CORRELATION_GUARD = os.getenv("CORRELATION_GUARD", "1") == "1"
MAX_OPEN_CORR = int(os.getenv("MAX_OPEN_CORR", "1"))

STRICT_PROD_MODE = os.getenv("STRICT_PROD_MODE", "0") == "1"
REQUIRE_AI_FEATURES = os.getenv("REQUIRE_AI_FEATURES", "0") == "1"
REQUIRE_AI_SCORER = os.getenv("REQUIRE_AI_SCORER", "0") == "1"
REQUIRE_AI_BRAIN = os.getenv("REQUIRE_AI_BRAIN", "0") == "1"
REQUIRE_AI_DEDUP = os.getenv("REQUIRE_AI_DEDUP", "0") == "1"


SPREAD_PIPS = float(os.getenv("SPREAD_PIPS", "0.0"))
SLIPPAGE_PIPS = float(os.getenv("SLIPPAGE_PIPS", "0.0"))
COMMISSION_PER_LOT = float(os.getenv("COMMISSION_PER_LOT", "0.0"))
USD_PER_PIP_PER_LOT = float(os.getenv("USD_PER_PIP_PER_LOT", "10.0"))

_apply_costs_env = os.getenv("APPLY_TRADING_COSTS", "").strip()
if _apply_costs_env in ("1", "true", "TRUE", "yes", "YES"):
    APPLY_TRADING_COSTS = True
elif _apply_costs_env in ("0", "false", "FALSE", "no", "NO"):
    APPLY_TRADING_COSTS = False
else:
    APPLY_TRADING_COSTS = any(
        x > 0.0 for x in (SPREAD_PIPS, SLIPPAGE_PIPS, COMMISSION_PER_LOT)
    )

if SPREAD_PIPS < 0 or SLIPPAGE_PIPS < 0 or COMMISSION_PER_LOT < 0:
    raise ValueError("Trading costs must be >= 0")

ACCOUNT_EQUITY_USD = float(
    os.getenv("ACCOUNT_EQUITY_USD", os.getenv("DEFAULT_CAPITAL", "1000"))
)
RISK_PER_TRADE_PCT = float(
    os.getenv("RISK_PER_TRADE_PCT", os.getenv("DEFAULT_RISK_PCT", "1.0"))
)
if ACCOUNT_EQUITY_USD <= 0:
    raise ValueError("ACCOUNT_EQUITY_USD must be > 0")
if RISK_PER_TRADE_PCT <= 0:
    raise ValueError("RISK_PER_TRADE_PCT must be > 0")

MIN_LOT_SIZE = float(os.getenv("MIN_LOT_SIZE", "0.01"))
LOT_STEP = float(os.getenv("LOT_STEP", "0.01"))
MAX_LOT_SIZE = float(os.getenv("MAX_LOT_SIZE", "2.0"))

enforce_prod_dependencies()

LOG_LEVEL = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=LOG_LEVEL,
)
log = logging.getLogger("copilot")
dbg = logging.getLogger("signals")
DEBUG_SIGNALS = os.getenv("DEBUG_SIGNALS", "1") == "1"

logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

if DEBUG_SIGNALS:
    dbg.setLevel(logging.INFO)
    log.info(
        "DEBUG_SIGNALS=ON | AI_SCORE_MIN=%.1f | RT=%s | POLL=%.2fs",
        AI_SCORE_MIN,
        REALTIME_MODE,
        REALTIME_POLL_SEC,
    )

LOG_DIR = pathlib.Path(os.getenv("LOG_DIR", "logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

ALERTS_CSV = pathlib.Path(os.getenv("ALERTS_CSV", "logs/alerts.csv"))
if not ALERTS_CSV.exists():
    with open(ALERTS_CSV, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(
            [
                "utc_time",
                "chat_id",
                "symbol",
                "tf",
                "reason",
                "entry",
                "sl",
                "tp",
                "rrr",
                "adx",
                "near_sr",
                "notes",
                "result",
                "ai_score",
                "type",
                "regime",
                "rsi",
                "atr",
                "weak_pullback",
                "htf_conf",
            ]
        )

TRADES_STATE_FILE = pathlib.Path(os.getenv("TRADES_STATE_FILE", "logs/trades_state.json"))
TRADES_CSV = pathlib.Path(os.getenv("TRADES_CSV", "logs/trades.csv"))
TRADES_MASTER = pathlib.Path(os.getenv("TRADES_MASTER_FILE", "logs/trades_master.json"))

USD_CLUSTER_MAP = {
    ("EURUSD", "LONG"): "USD_WEAK",
    ("GBPUSD", "LONG"): "USD_WEAK",
    ("AUDUSD", "LONG"): "USD_WEAK",
    ("NZDUSD", "LONG"): "USD_WEAK",
    ("USDCHF", "SHORT"): "USD_WEAK",
    ("USDCAD", "SHORT"): "USD_WEAK",
    ("USDJPY", "SHORT"): "USD_WEAK",
    ("EURUSD", "SHORT"): "USD_STRONG",
    ("GBPUSD", "SHORT"): "USD_STRONG",
    ("AUDUSD", "SHORT"): "USD_STRONG",
    ("NZDUSD", "SHORT"): "USD_STRONG",
    ("USDCHF", "LONG"): "USD_STRONG",
    ("USDCAD", "LONG"): "USD_STRONG",
    ("USDJPY", "LONG"): "USD_STRONG",
}

_cache: Dict[Tuple[str, str, int], Tuple[float, pd.DataFrame]] = {}
LAST_SIG_BAR: Dict[Tuple[str, str, str], pd.Timestamp] = {}
_last_rsi_state: Dict[Tuple[str, str], str] = {}
_last_price_emit: Dict[Tuple[str, str], float] = {}
_last_atr_emit: Dict[Tuple[str, str], float] = {}
_recent_results: deque[str] = deque(maxlen=PERF_WINDOW)

_daily_date: Optional[str] = None
_daily_trades: int = 0
_daily_wins: int = 0
_daily_losses: int = 0
_daily_r: float = 0.0
_daily_csv_cache: Optional[Dict[str, Any]] = None
_daily_csv_cache_ts: float = 0.0

def normalize_symbol(sym: str) -> str:
    return (sym or "").strip().upper()

def api_symbol(sym: str) -> str:
    s = normalize_symbol(sym)
    if "/" in s:
        return s
    if len(s) == 6:
        return f"{s[:3]}/{s[3:]}"
    return s

def pip_size(sym: str) -> float:
    sym = normalize_symbol(sym)
    if sym.startswith("XAU") or sym in ("GOLD", "XAU/USD"):
        return 0.01
    return 0.01 if "JPY" in sym else 0.0001

def price_decimals(sym: str) -> int:
    sym = normalize_symbol(sym)
    if sym.startswith("XAU") or sym in ("GOLD", "XAU/USD"):
        return 2
    return 3 if "JPY" in sym else 5

def is_gold_symbol(sym: str) -> bool:
    sym = normalize_symbol(sym)
    return sym.startswith("XAU") or sym in ("GOLD", "XAU/USD")

import math

def _round_lot_size(lots: float) -> float:
    if LOT_STEP <= 0:
        return max(MIN_LOT_SIZE, min(MAX_LOT_SIZE, lots))
    rounded = math.floor(lots / LOT_STEP) * LOT_STEP
    rounded = max(MIN_LOT_SIZE, rounded)
    rounded = min(MAX_LOT_SIZE, rounded)
    return round(rounded, 2)

def usd_per_pip_per_lot(symbol: str, price: float | None = None) -> float:
    sym = normalize_symbol(symbol)

    if sym.startswith("XAU") or sym in ("GOLD", "XAU/USD"):
        return 1.0

    if sym.endswith("USD") and "JPY" not in sym:
        return 10.0

    if sym == "USDJPY":
        px = float(price or 150.0)
        return 1000.0 / max(px, 1e-9)

    if sym.endswith("JPY"):
        px = float(price or 150.0)
        return 1000.0 / max(px, 1e-9)

    if sym == "EURGBP":
        gbpusd_proxy = float(os.getenv("GBPUSD_PROXY", "1.27"))
        return 10.0 * gbpusd_proxy

    return max(0.0001, USD_PER_PIP_PER_LOT)

def compute_lot_size(symbol: str, entry: float, sl: float) -> float:
    ps = pip_size(symbol)
    if ps <= 0:
        return MIN_LOT_SIZE
    stop_pips = abs(entry - sl) / ps
    if stop_pips <= 0:
        return MIN_LOT_SIZE
    risk_usd = max(0.0, ACCOUNT_EQUITY_USD * (RISK_PER_TRADE_PCT / 100.0))
    usd_pppl = usd_per_pip_per_lot(symbol, entry)
    raw_lots = risk_usd / (stop_pips * max(usd_pppl, 0.0001))
    return _round_lot_size(raw_lots)

def estimated_risk_usd(symbol: str, entry: float, sl: float, lots: float) -> float:
    ps = pip_size(symbol)
    if ps <= 0 or lots <= 0:
        return 0.0
    stop_pips = abs(entry - sl) / ps
    return stop_pips * usd_per_pip_per_lot(symbol, entry) * lots

def compute_trade_costs_pips() -> float:
    """Costs still to deduct after entry fill already includes spread + slippage."""
    if not APPLY_TRADING_COSTS:
        return 0.0
    return max(0.0, SLIPPAGE_PIPS)

def compute_total_trade_costs_pips() -> float:
    if not APPLY_TRADING_COSTS:
        return 0.0
    return max(0.0, SPREAD_PIPS) + max(0.0, SLIPPAGE_PIPS) * 2.0

def is_cost_structure_valid() -> bool:
    if not APPLY_TRADING_COSTS:
        return True
    total_costs = max(0.0, SPREAD_PIPS) + max(0.0, SLIPPAGE_PIPS) * 2.0
    return total_costs < max(2.5, MIN_TP_PIPS * 0.5)

def data_is_fresh(df: pd.DataFrame, tf: str, max_lag_bars: int = 2) -> bool:
    if df is None or df.empty or len(df) < 2:
        return False
    try:
        last_ts = pd.Timestamp(df.iloc[-1]["datetime"])
        if last_ts.tzinfo is None:
            last_ts = last_ts.tz_localize("UTC")
        now = pd.Timestamp.now("UTC")
        lag_min = (now - last_ts).total_seconds() / 60.0
        return lag_min <= (tf_to_minutes(tf) * max_lag_bars)
    except Exception:
        return False

def _parse_trading_hours(hstr: str) -> Tuple[int, int]:
    try:
        a, b = hstr.split("-")
        return max(0, min(23, int(a))), max(0, min(24, int(b)))
    except Exception:
        return 0, 24

_TH_START, _TH_END = _parse_trading_hours(TRADING_HOURS)

def in_trading_session(ts: pd.Timestamp) -> bool:
    try:
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        local = ts.tz_convert(TRADING_TZ)
        if local.weekday() >= 5 and os.getenv("ALLOW_WEEKENDS", "0") != "1":
            return False
        if _TH_START == 0 and _TH_END == 24:
            return True
        h = local.hour
        if _TH_START <= _TH_END:
            return _TH_START <= h < _TH_END
        return (h >= _TH_START) or (h < _TH_END)
    except Exception:
        return False

def _interval_from_tf(tf: str) -> str:
    tf = tf.upper()
    return {
        "M1": "1min",
        "M5": "5min",
        "M10": "10min",
        "M15": "15min",
        "M30": "30min",
        "H1": "1h",
        "H4": "4h",
        "D1": "1day",
        "D": "1day",
    }.get(tf, "5min")

def tf_to_minutes(tf: str) -> int:
    tf = str(tf or "").upper()
    return {
        "M1": 1,
        "M5": 5,
        "M10": 10,
        "M15": 15,
        "M30": 30,
        "H1": 60,
        "H4": 240,
        "D1": 1440,
        "D": 1440,
    }.get(tf, 5)

def _today_str() -> str:
    try:
        now_local = pd.Timestamp.now("UTC").tz_convert(TRADING_TZ)
        return now_local.date().isoformat()
    except Exception:
        return dt.date.today().isoformat()

def _ensure_daily_rollover():
    global _daily_date, _daily_trades, _daily_wins, _daily_losses, _daily_r
    today = _today_str()
    if _daily_date != today:
        _daily_date = today
        _daily_trades = 0
        _daily_wins = 0
        _daily_losses = 0
        _daily_r = 0.0

def _daily_cache_bust():
    global _daily_csv_cache, _daily_csv_cache_ts
    _daily_csv_cache = None
    _daily_csv_cache_ts = 0.0

def _load_trades_csv_rows() -> List[Dict[str, Any]]:
    if not TRADES_CSV.exists():
        return []
    try:
        out: List[Dict[str, Any]] = []
        with open(TRADES_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row:
                    out.append(row)
        return out
    except Exception:
        return []

def recent_winrate(window: int = PERF_WINDOW) -> Optional[float]:
    rows = _load_trades_csv_rows()
    if not rows:
        return None
    closed = [r for r in rows if str(r.get("status", "")).upper() in ("WIN", "LOSS")]
    last_rows = closed[-max(1, int(window)):]
    wins = 0
    total = 0
    for r in last_rows:
        status = str(r.get("status", "")).upper()
        if status in ("WIN", "LOSS"):
            total += 1
            if status == "WIN":
                wins += 1
    if total == 0:
        return None
    return (wins / total) * 100.0

def recent_loss_streak() -> int:
    rows = _load_trades_csv_rows()
    closed = [r for r in rows if str(r.get("status", "")).upper() in ("WIN", "LOSS")]
    source = [str(r.get("status", "")).upper() for r in closed] or list(_recent_results)
    streak = 0
    for x in reversed(source):
        sx = str(x).upper()
        if sx == "LOSS":
            streak += 1
        elif sx == "WIN":
            break
    return streak

def cooldown_active() -> bool:
    n = int(os.getenv("COOLDOWN_AFTER_LOSS_N", "0") or 0)
    mins = int(os.getenv("COOLDOWN_MINUTES", "0") or 0)
    if n <= 0 or mins <= 0:
        return False
    if recent_loss_streak() < n:
        return False

    rows = _load_trades_csv_rows()
    if not rows:
        return False

    closed = [r for r in rows if str(r.get("status", "")).upper() in ("WIN", "LOSS")]
    if not closed:
        return False

    last = closed[-1]
    try:
        ts = pd.to_datetime(last.get("closed_utc", ""), utc=True)
    except Exception:
        return False

    age_min = (pd.Timestamp.now("UTC") - ts).total_seconds() / 60.0
    return age_min < mins

def perf_adjustments() -> Tuple[float, float, float]:
    try:
        adj = get_adjustments()
    except Exception:
        return 0.0, 0.0, 0.0
    ai_shift = float(getattr(adj, "ai_shift", 0.0) or 0.0)
    adx_shift = float(getattr(adj, "adx_boost", 0.0) or 0.0)
    sr_shift = float(getattr(adj, "sr_tighten", 0.0) or 0.0)
    return ai_shift, adx_shift, sr_shift

def trades_today_summary() -> Dict[str, Any]:
    rows = _load_trades_csv_rows()
    if not rows:
        today = _today_str()
        return {
            "date": today,
            "total": 0,
            "wins": 0,
            "losses": 0,
            "expired": 0,
            "wr": 0.0,
            "pnl_r": 0.0,
            "by_symbol": {},
        }
    now_local = pd.Timestamp.now("UTC").tz_convert(TRADING_TZ)
    today = now_local.date()
    total = wins = losses = expired = 0
    pnl_r = 0.0
    by_symbol: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        try:
            ts_utc = pd.to_datetime(r.get("closed_utc", ""), utc=True)
        except Exception:
            continue
        ts_local = ts_utc.tz_convert(TRADING_TZ)
        if ts_local.date() != today:
            continue
        status = str(r.get("status", "")).upper()
        if status in ("WIN", "LOSS"):
            total += 1
        try:
            pnl_r += float(r.get("r", 0.0) or 0.0)
        except Exception:
            pass
        if status == "WIN":
            wins += 1
        elif status == "LOSS":
            losses += 1
        elif status == "EXPIRED":
            expired += 1
        sym = normalize_symbol(r.get("symbol", ""))
        s = by_symbol.setdefault(
            sym,
            {"total": 0, "wins": 0, "losses": 0, "expired": 0, "pnl_r": 0.0},
        )
        if status in ("WIN", "LOSS"):
            s["total"] += 1
        try:
            s["pnl_r"] += float(r.get("r", 0.0) or 0.0)
        except Exception:
            pass
        if status == "WIN":
            s["wins"] += 1
        elif status == "LOSS":
            s["losses"] += 1
        elif status == "EXPIRED":
            s["expired"] += 1
    closed_for_wr = wins + losses
    wr = (wins / closed_for_wr * 100.0) if closed_for_wr else 0.0
    return {
        "date": today.isoformat(),
        "total": total,
        "wins": wins,
        "losses": losses,
        "expired": expired,
        "wr": wr,
        "pnl_r": pnl_r,
        "by_symbol": by_symbol,
    }

def _daily_from_csv_stats_cached(ttl_sec: float = 10.0) -> Dict[str, Any]:
    global _daily_csv_cache, _daily_csv_cache_ts
    now = time.time()
    if _daily_csv_cache is not None and (now - _daily_csv_cache_ts) <= ttl_sec:
        return _daily_csv_cache
    stats = trades_today_summary()
    _daily_csv_cache = stats
    _daily_csv_cache_ts = now
    return stats

def is_daily_guard_active() -> bool:
    if DAILY_FROM_CSV:
        s = _daily_from_csv_stats_cached(ttl_sec=10.0)
        total = int(s.get("total", 0) or 0)
        losses = int(s.get("losses", 0) or 0)
        pnl_r = float(s.get("pnl_r", 0.0) or 0.0)
        if DAILY_MAX_TRADES > 0 and total >= DAILY_MAX_TRADES:
            return True
        if DAILY_MAX_LOSSES > 0 and losses >= DAILY_MAX_LOSSES:
            return True
        if DAILY_MAX_RISK_R < 0 and pnl_r <= DAILY_MAX_RISK_R:
            return True
        return False
    _ensure_daily_rollover()
    if DAILY_MAX_TRADES > 0 and _daily_trades >= DAILY_MAX_TRADES:
        return True
    if DAILY_MAX_LOSSES > 0 and _daily_losses >= DAILY_MAX_LOSSES:
        return True
    if DAILY_MAX_RISK_R < 0 and _daily_r <= DAILY_MAX_RISK_R:
        return True
    return False

def daily_summary() -> Dict[str, Any]:
    if DAILY_FROM_CSV:
        s = _daily_from_csv_stats_cached(ttl_sec=10.0)
        total = int(s.get("total", 0) or 0)
        wins = int(s.get("wins", 0) or 0)
        losses = int(s.get("losses", 0) or 0)
        pnl_r = float(s.get("pnl_r", 0.0) or 0.0)
        date = str(s.get("date", _today_str()) or _today_str())
        guard = (
            (DAILY_MAX_TRADES > 0 and total >= DAILY_MAX_TRADES)
            or (DAILY_MAX_LOSSES > 0 and losses >= DAILY_MAX_LOSSES)
            or (DAILY_MAX_RISK_R < 0 and pnl_r <= DAILY_MAX_RISK_R)
        )
        closed_for_wr = wins + losses
        return {
            "date": date,
            "trades": total,
            "closed_for_wr": closed_for_wr,
            "wins": wins,
            "losses": losses,
            "r": pnl_r,
            "max_trades": DAILY_MAX_TRADES,
            "max_losses": DAILY_MAX_LOSSES,
            "max_risk_r": DAILY_MAX_RISK_R,
            "guard_active": guard,
        }
    _ensure_daily_rollover()
    guard = (
        (DAILY_MAX_TRADES > 0 and _daily_trades >= DAILY_MAX_TRADES)
        or (DAILY_MAX_LOSSES > 0 and _daily_losses >= DAILY_MAX_LOSSES)
        or (DAILY_MAX_RISK_R < 0 and _daily_r <= DAILY_MAX_RISK_R)
    )
    closed_for_wr = _daily_wins + _daily_losses
    return {
        "date": _daily_date,
        "trades": _daily_trades,
        "closed_for_wr": closed_for_wr,
        "wins": _daily_wins,
        "losses": _daily_losses,
        "r": _daily_r,
        "max_trades": DAILY_MAX_TRADES,
        "max_losses": DAILY_MAX_LOSSES,
        "max_risk_r": DAILY_MAX_RISK_R,
        "guard_active": guard,
    }

async def fetch_ohlc(symbol: str, tf: str, limit: int, *, use_cache=True) -> pd.DataFrame:
    sym = normalize_symbol(symbol)
    tf = tf.upper()
    key = (sym, tf, int(limit))
    now = time.time()
    ttl = HTF_CACHE_TTL_SEC if tf == HTF_TF else LTF_CACHE_TTL_SEC
    if use_cache and key in _cache:
        t_cached, df_cached = _cache[key]
        if now - t_cached <= ttl:
            return df_cached.copy()
    if not TWELVE_API_KEY:
        raise RuntimeError("TWELVE_API_KEY missing")
    if HTTP_CLIENT is None:
        raise RuntimeError("HTTP_CLIENT is not initialized")
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": api_symbol(sym),
        "interval": _interval_from_tf(tf),
        "outputsize": limit,
        "apikey": TWELVE_API_KEY,
        "timezone": "UTC",
        "format": "JSON",
    }
    retry_http_codes = {429, 502, 503, 504}
    r = None
    for attempt in range(3):
        try:
            r = await HTTP_CLIENT.get(url, params=params, timeout=10.0)
            if r.status_code in retry_http_codes:
                sleep_s = min(RATE_LIMIT_BACKOFF_SEC, 2 ** attempt)
                log.warning(
                    "TwelveData retryable HTTP %s %s %s attempt=%s",
                    r.status_code,
                    sym,
                    tf,
                    attempt + 1,
                )
                await asyncio.sleep(sleep_s)
                continue
            break
        except Exception as e:
            sleep_s = min(RATE_LIMIT_BACKOFF_SEC, 2 ** attempt)
            log.warning(
                "fetch_ohlc request failed %s %s attempt=%s: %s",
                sym,
                tf,
                attempt + 1,
                e,
            )
            await asyncio.sleep(sleep_s)
    else:
        return pd.DataFrame()
    if r is None:
        return pd.DataFrame()
    if r.status_code != 200:
        log.warning("TwelveData HTTP %s %s %s: %s", r.status_code, sym, tf, r.text[:300])
        return pd.DataFrame()
    try:
        data = r.json()
    except Exception:
        log.warning("TwelveData non-JSON %s %s %s: %s", r.status_code, sym, tf, r.text[:300])
        return pd.DataFrame()
    if "values" not in data:
        payload_txt = str(data)[:300]
        try:
            code_txt = str(data.get("code", "")).lower()
            status_txt = str(data.get("status", "")).lower()
            message_txt = str(data.get("message", "")).lower()
        except Exception:
            code_txt = ""
            status_txt = ""
            message_txt = ""
        retryable_payload = (
            "rate" in message_txt
            or "limit" in message_txt
            or "throttle" in message_txt
            or code_txt in {"429", "too_many_requests"}
        )

        plan_blocked = (
            code_txt == "404"
            and "not available with your plan" in message_txt
        )

        if plan_blocked:
            log.warning("TwelveData PLAN BLOCK %s %s: %s", sym, tf, payload_txt)
        elif retryable_payload:
            log.warning("TwelveData retry-like payload %s %s: %s", sym, tf, payload_txt)
        else:
            log.error("CRITICAL TwelveData bad payload %s %s: %s", sym, tf, payload_txt)

        return pd.DataFrame()
    rows = []
    for v in reversed(data["values"]):
        try:
            ts = pd.to_datetime(v["datetime"], utc=True)
            rows.append(
                {
                    "datetime": ts,
                    "open": float(v["open"]),
                    "high": float(v["high"]),
                    "low": float(v["low"]),
                    "close": float(v["close"]),
                }
            )
        except Exception:
            pass
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    required = {"datetime", "open", "high", "low", "close"}
    if df.empty or not required.issubset(df.columns):
        return pd.DataFrame()
    df = df.sort_values("datetime").reset_index(drop=True)
    _cache[key] = (now, df.copy())
    if len(_cache) > 100:
        oldest_key = min(_cache.items(), key=lambda x: x[1][0])[0]
        _cache.pop(oldest_key, None)
    return df

def _compute_sr_features(df: pd.DataFrame):
    if df.empty:
        return
    lookback = min(SR_LOOKBACK, len(df))
    hi = df["high"].rolling(lookback, min_periods=lookback).max()
    lo = df["low"].rolling(lookback, min_periods=lookback).min()
    close = df["close"]
    dist_hi = (close - hi).abs()
    dist_lo = (close - lo).abs()
    df["sr_dist_price"] = dist_hi.combine(dist_lo, min)
    df["sr_dist_price"] = df["sr_dist_price"].fillna(0.0)

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["ema50"] = EMAIndicator(df["close"], window=50, fillna=True).ema_indicator()
    df["ema200"] = EMAIndicator(df["close"], window=200, fillna=True).ema_indicator()
    df["adx"] = ADXIndicator(df["high"], df["low"], df["close"], window=14, fillna=True).adx()
    df["rsi"] = RSIIndicator(df["close"], window=14, fillna=True).rsi()
    df["atr"] = AverageTrueRange(df["high"], df["low"], df["close"], window=14, fillna=True).average_true_range()
    _compute_sr_features(df)
    return df

def range_atr_ratio_from_ohlc(df: pd.DataFrame) -> float:
    try:
        hi = float(df["high"].max())
        lo = float(df["low"].min())
        rng = hi - lo
        atr = float(df["atr"].tail(14).mean())
        return (atr / rng) if rng > 0 else 0.0
    except Exception:
        return 0.0

def ema_flatness(df: pd.DataFrame, bars: int = 8) -> float:
    try:
        s = df["ema50"].tail(bars)
        if len(s) < 2:
            return 0.0
        return abs(float(s.iloc[-1]) - float(s.iloc[0]))
    except Exception:
        return 0.0

def candle_overlap_ratio(df: pd.DataFrame, bars: int = 6) -> float:
    try:
        tail = df.tail(bars)
        if len(tail) < 2:
            return 0.0
        overlaps = 0
        total = 0
        prev = None
        for row in tail.itertuples(index=False):
            if prev is not None:
                hi1, lo1 = float(prev.high), float(prev.low)
                hi2, lo2 = float(row.high), float(row.low)
                overlap = max(0.0, min(hi1, hi2) - max(lo1, lo2))
                rng = max(1e-9, max(hi1, hi2) - min(lo1, lo2))
                if overlap / rng >= 0.5:
                    overlaps += 1
                total += 1
            prev = row
        return overlaps / total if total > 0 else 0.0
    except Exception:
        return 0.0

def adaptive_bands(adx: float, base_lo: float, base_hi: float, strong: float) -> Tuple[float, float]:
    lo, hi = base_lo, base_hi
    if adx < 14:
        lo -= 2
        hi += 2
    elif adx >= strong:
        lo += 1
        hi -= 1
    lo = max(20, min(50, lo))
    hi = max(50, min(80, hi))
    if lo >= hi - 4:
        lo = hi - 4
    return lo, hi

def near_sr(last, sr_ratio: float) -> Tuple[bool, str]:
    atr = float(getattr(last, "atr", 0.0) or 0.0)
    dist = float(getattr(last, "sr_dist_price", 0.0) or 0.0)

    if atr <= 0:
        return True, "none"
    if dist <= 0:
        return False, "blocked"

    d = dist / atr
    block_ratio = max(0.18, sr_ratio * 0.50)

    if d <= block_ratio:
        return False, "blocked"
    if d <= sr_ratio:
        return True, "near"
    return True, "far"

def detect_patterns(df: pd.DataFrame) -> Dict[str, bool]:
    res = {
        "bull_engulf": False,
        "bear_engulf": False,
        "pin_long": False,
        "pin_short": False,
    }
    if len(df) < 2:
        return res
    p = df.iloc[-2]
    l = df.iloc[-1]
    o1, c1 = float(p.open), float(p.close)
    o2, c2 = float(l.open), float(l.close)
    h2, l2 = float(l.high), float(l.low)
    if c1 < o1 and c2 > o2 and c2 >= o1 and o2 <= c1:
        res["bull_engulf"] = True
    if c1 > o1 and c2 < o2 and c2 <= o1 and o2 >= c1:
        res["bear_engulf"] = True
    body = abs(c2 - o2)
    upper = h2 - max(c2, o2)
    lower = min(c2, o2) - l2
    rng = h2 - l2 if h2 > l2 else 1e-9
    if lower > 0.5 * rng and body <= 0.3 * rng:
        res["pin_long"] = True
    if upper > 0.5 * rng and body <= 0.3 * rng:
        res["pin_short"] = True
    return res

def htf_confluence(last_ltf, last_htf) -> bool:
    if not USE_HTF_TREND:
        return True
    if last_htf is None:
        return False
    try:
        ema50_h = float(last_htf.ema50)
        ema200_h = float(last_htf.ema200)
        adx_h = float(last_htf.adx)
        rsi_h = float(last_htf.rsi)
        close_h = float(last_htf.close)
        ema50_l = float(last_ltf.ema50)
        ema200_l = float(last_ltf.ema200)
        close_l = float(last_ltf.close)
    except Exception:
        return False
    method = str(HTF_TREND_METHOD or "ema").lower()
    if method == "ema":
        trend_up_h = (ema50_h > ema200_h) and (close_h > ema50_h)
        trend_down_h = (ema50_h < ema200_h) and (close_h < ema50_h)
    else:
        trend_up_h = (close_h > ema50_h) and (rsi_h >= 50)
        trend_down_h = (close_h < ema50_h) and (rsi_h <= 50)
    trend_up_l = (ema50_l > ema200_l) and (close_l > ema50_l)
    trend_down_l = (ema50_l < ema200_l) and (close_l < ema50_l)
    coherent = (trend_up_h and trend_up_l) or (trend_down_h and trend_down_l)
    if not coherent:
        return False
    if adx_h < max(12.0, HTF_ADX_MIN - 2.0):
        return False
    return True

def ai_score_for_df(symbol: str, df: pd.DataFrame, tf: str) -> float:
    symbol = normalize_symbol(symbol)
    last = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]
    if AI_SCORER_ON and AIScorer and extract_last_features:
        try:
            df_closed = df.iloc[:-1].copy() if len(df) >= 2 else df.copy()
            feats = extract_last_features(df_closed, symbol=symbol, tf=tf)
            if feats is not None:
                s = AIScorer()
                score = float(s.score(feats))
                return max(0.0, min(100.0, score))
        except Exception as e:
            log.warning("AI scorer failed: %s", e)
    adx = float(last.adx)
    rsi = float(last.rsi)
    atr = float(last.atr)
    ema50 = float(last.ema50)
    ema200 = float(last.ema200)
    close = float(last.close)
    df_pat = df.iloc[:-1] if len(df) >= 3 else df
    pat = detect_patterns(df_pat)
    ctx = scan_context(df, tf)
    score = 50.0
    if adx >= ADX_MIN:
        score += 8
    if adx >= ADX_STRONG:
        score += 10
    if adx < 10:
        score -= 10
    trend_up = (ema50 > ema200) and (close > ema50)
    trend_dn = (ema50 < ema200) and (close < ema50)
    score += 5 if (trend_up or trend_dn) else -5
    if trend_up and rsi <= RSI_LO_BASE:
        score += 4
    elif trend_dn and rsi >= RSI_HI_BASE:
        score += 4
    elif 45 <= rsi <= 55:
        score -= 3
    ps = pip_size(symbol)
    atr_pips = atr / ps if ps > 0 else 0
    score += 5 if atr_pips >= MIN_ATR_PIPS else -5
    if pat["bull_engulf"] or pat["bear_engulf"]:
        score += 4
    if pat["pin_long"] or pat["pin_short"]:
        score += 3
    try:
        if ctx.recent_sweep:
            score += 3
        if ctx.fvg_nearby:
            score += 2
    except Exception:
        pass
    return max(0.0, min(100.0, score))

def mk_plan(
    symbol: str,
    side: str,
    price: float,
    atr: float,
    regime: str,
    *,
    structure_stop: float | None = None,
):
    try:
        ps = pip_size(symbol)
        d = price_decimals(symbol)
    except Exception:
        return "", None, None, None, {}
    if atr <= 0 or ps <= 0:
        return "", None, None, None, {}
    atr_pips = atr / ps
    if regime == "trend":
        sl_mult = ATR_SL_MULT * (TREND_SL_MULT if DYNAMIC_RRR else 1.0)
    else:
        sl_mult = ATR_SL_MULT * (CHOP_SL_MULT if DYNAMIC_RRR else 1.0)
    sl_pips = max(sl_mult * atr_pips, MIN_STOP_DISTANCE_PIPS)
    if structure_stop is not None:
        structural_risk = (
            price - float(structure_stop)
            if side == "long"
            else float(structure_stop) - price
        )
        if structural_risk > 0:
            sl_pips = max(sl_pips, structural_risk / ps)
    if sl_pips <= 0:
        return "", None, None, None, {}
    if DYNAMIC_RRR:
        if regime == "trend":
            tp_mult = ATR_TP_MULT * TREND_TP_MULT
        else:
            tp_mult = ATR_TP_MULT * CHOP_TP_MULT
        tp_pips = max(tp_mult * atr_pips, MIN_TP_PIPS)
    else:
        rrr_fix = float(FIXED_RRR or 0.0)
        if rrr_fix <= 0:
            rrr_fix = 1.5
        tp_pips = max(sl_pips * rrr_fix, MIN_TP_PIPS)
    if tp_pips <= 0:
        return "", None, None, None, {}
    planned_tp_pips = tp_pips * TP2_RATIO
    if planned_tp_pips <= 0:
        return "", None, None, None, {}
    entry = price
    if ENTRY_OFFSET_PIPS != 0.0:
        offset = ENTRY_OFFSET_PIPS * ps
        if side == "long":
            entry = price - offset
        else:
            entry = price + offset
    tp1_enabled = float(TP1_RATIO or 0.0) > 0.0
    if side == "long":
        sl_price = entry - (sl_pips + SL_BUFFER_PIPS) * ps
        tp2_price = entry + (planned_tp_pips + TP_BUFFER_PIPS) * ps
        tp1_price = None
        tp1_pips = None
        rrr1 = None
        if tp1_enabled:
            tp1_pips = max(tp_pips * TP1_RATIO, MIN_TP_PIPS * 0.5)
            tp1_price = entry + (tp1_pips + TP_BUFFER_PIPS * 0.5) * ps
            rrr1 = tp1_pips / sl_pips if sl_pips > 0 else 0
    else:
        sl_price = entry + (sl_pips + SL_BUFFER_PIPS) * ps
        tp2_price = entry - (planned_tp_pips + TP_BUFFER_PIPS) * ps
        tp1_price = None
        tp1_pips = None
        rrr1 = None
        if tp1_enabled:
            tp1_pips = max(tp_pips * TP1_RATIO, MIN_TP_PIPS * 0.5)
            tp1_price = entry - (tp1_pips + TP_BUFFER_PIPS * 0.5) * ps
            rrr1 = tp1_pips / sl_pips if sl_pips > 0 else 0
    actual_risk_pips = abs(entry - sl_price) / ps
    actual_target_pips = abs(tp2_price - entry) / ps
    rrr2 = actual_target_pips / actual_risk_pips if actual_risk_pips > 0 else 0.0
    trail_info = ""
    if USE_TRAILING and TRAIL_ATR_MULT > 0:
        trail_info = f"\nTRAIL: po dosažení 1R SL → BE, pak trailing {TRAIL_ATR_MULT:.2f}×ATR"
    side_txt = "LONG" if side == "long" else "SHORT"
    reg_txt = "trend" if regime == "trend" else "chop"
    if is_gold_symbol(symbol):
        risk_move = actual_risk_pips * ps
        target_move = actual_target_pips * ps
        lines = [
            f"Entry  {entry:.{d}f}",
            f"SL     {sl_price:.{d}f} | Risk ${risk_move:.2f}",
        ]
        if tp1_price is not None and tp1_pips is not None and rrr1 is not None:
            tp1_move = tp1_pips * ps
            lines.append(f"TP1    {tp1_price:.{d}f} | Target ${tp1_move:.2f} | RRR 1:{rrr1:.2f}")
        lines.append(f"TP     {tp2_price:.{d}f} | Target ${target_move:.2f} | RRR 1:{rrr2:.2f}")
    else:
        lines = [
            f"{side_txt} | {reg_txt}",
            f"Entry: {entry:.{d}f}",
            f"SL:    {sl_price:.{d}f} ({actual_risk_pips:.1f} pips)",
        ]
        if tp1_price is not None and tp1_pips is not None and rrr1 is not None:
            lines.append(f"TP1:   {tp1_price:.{d}f} ({tp1_pips:.1f} pips, RRR {rrr1:.2f})")
        lines.append(f"TP2:   {tp2_price:.{d}f} ({actual_target_pips:.1f} pips, RRR {rrr2:.2f})")
    if trail_info:
        lines.append(trail_info.strip("\n"))
    txt = "\n".join(lines)
    meta = {
        "tp1": tp1_price,
        "tp2": tp2_price,
        "sl": sl_price,
        "entry": entry,
        "sl_pips": sl_pips,
        "tp_pips": tp_pips,
        "rrr1": rrr1 if rrr1 is not None else 0.0,
        "rrr2": rrr2,
        "regime": regime,
        "side": side,
        "trail_atr_mult": TRAIL_ATR_MULT if USE_TRAILING else 0.0,
    }
    return txt, sl_price, tp2_price, rrr2, meta

def _rsi_state_key(symbol: str, side: str) -> Tuple[str, str]:
    return (normalize_symbol(symbol), side.lower())

def _should_reemit(symbol: str, side: str, price: float, atr: float, adx: float) -> bool:
    k = _rsi_state_key(symbol, side)
    last_price = _last_price_emit.get(k)
    last_atr = _last_atr_emit.get(k)
    if last_price is None or last_atr is None:
        return True
    if atr <= 0:
        return False
    move = abs(price - last_price)
    atr_move = move / atr
    threshold = REEMIT_MIN_ATR_STRONG if adx >= ADX_STRONG else REEMIT_MIN_ATR
    return atr_move >= threshold

def _update_emit_trackers(symbol: str, side: str, price: float, atr: float):
    k = _rsi_state_key(symbol, side)
    _last_price_emit[k] = price
    _last_atr_emit[k] = atr

def _open_corr_cluster_count(st: Dict[str, Any], symbol: str, side_up: str) -> int:
    cluster = USD_CLUSTER_MAP.get((normalize_symbol(symbol), str(side_up).upper()))
    if not cluster:
        return 0

    count = 0
    for _, existing in st.items():
        try:
            if not isinstance(existing, dict):
                continue

            ex_status = str(existing.get("status", "PENDING")).upper()
            ex_signal_state = str(existing.get("signal_state", ex_status)).upper()

            if ex_status not in ("PENDING", "OPEN"):
                continue
            if ex_signal_state in ("REJECTED", "NOT_FILLED", "EXPIRED_ENTRY"):
                continue

            ex_sym = normalize_symbol(existing.get("symbol", ""))
            ex_side = str(existing.get("side", "")).upper()
            ex_cluster = USD_CLUSTER_MAP.get((ex_sym, ex_side))

            if ex_cluster == cluster:
                count += 1
        except Exception:
            continue

    return count

def log_alert(
    chat_id: int,
    symbol: str,
    tf: str,
    reason: str,
    entry,
    sl,
    tp,
    adx,
    near,
    *,
    notes: str = "",
    ai: float | None = None,
    msg_type: str = "alert",
    rrr_val: float | None = None,
    regime: str = "",
    rsi_val: float | None = None,
    atr_val: float | None = None,
    weak_pullback: bool = False,
    htf_conf: bool = False,
):
    try:
        with open(ALERTS_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    dt.datetime.utcnow().isoformat() + "Z",
                    chat_id,
                    symbol,
                    tf,
                    reason,
                    f"{(entry or 0.0):.8f}",
                    f"{(sl or 0.0):.8f}",
                    f"{(tp or 0.0):.8f}",
                    f"{(rrr_val or 0.0):.2f}",
                    f"{(adx or 0.0):.2f}",
                    near,
                    notes,
                    "",
                    ai,
                    msg_type,
                    regime,
                    f"{(rsi_val or 0.0):.2f}",
                    f"{(atr_val or 0.0):.8f}",
                    int(bool(weak_pullback)),
                    int(bool(htf_conf)),
                ]
            )
    except Exception as e:
        log.warning("log_alert CSV write failed: %s", e)
    if DREAM_ON:
        try:
            dream_log(
                msg_type,
                {
                    "symbol": symbol,
                    "tf": tf,
                    "side": str(notes or "").strip().upper() if notes else "",
                    "ai": ai,
                    "adx": adx,
                    "rrr": rrr_val,
                    "reason": reason,
                    "near": near,
                    "regime": regime,
                    "rsi": rsi_val,
                    "atr": atr_val,
                    "weak_pullback": bool(weak_pullback),
                    "htf_conf": bool(htf_conf),
                },
            )
        except Exception as e:
            log.warning("log_alert dream_log failed: %s", e)

async def _autoexec_if_enabled(
    symbol: str,
    side_lc: str,
    entry: float,
    sl: float,
    tp: float,
    tp1: float | None = None,
    *,
    tf: str | None = None,
    brain_feat: Dict[str, Any] | None = None,
    audit: Dict[str, Any] | None = None,
):
    try:
        now_ts = pd.Timestamp.now("UTC")
        if not in_trading_session(now_ts):
            return None
    except Exception:
        return None

    side_uc = (side_lc or "").strip().upper()
    if side_uc not in ("LONG", "SHORT"):
        side_uc = "LONG" if (side_lc or "").lower().startswith("l") else "SHORT"

    rrr_val = None
    try:
        ps = pip_size(symbol)
        if ps > 0:
            risk_pips = abs(entry - sl) / ps
            target_pips = abs(tp - entry) / ps
            if risk_pips > 0:
                rrr_val = round(float(target_pips / risk_pips), 4)
    except Exception:
        rrr_val = None

    trade_id = None

    if PAPER_TRADES_ON:
        try:
            trade_id = trade_engine_fallback(
                symbol,
                side_uc,
                entry,
                sl,
                tp,
                tp1=tp1,
                rrr=rrr_val,
                tf=tf,
                brain_feat=brain_feat,
                audit=audit,
            )
        except Exception as e:
            log.warning("trade_engine_fallback failed: %s", e)
            return None

    if not AUTOEXEC_ON:
        return trade_id

    if trade_id is None:
        log.info(
            "AUTOEXEC skipped for %s %s because fallback trade was not created",
            symbol,
            side_uc,
        )
        return None

    try:
        if not TradeEngine:
            update_trade_state(
                trade_id,
                status="REJECTED",
                signal_state="REJECTED",
                reject_reason="TradeEngine not available",
            )
            log.warning("TradeEngine not available for AUTOEXEC")
            return trade_id

        te = TradeEngine()
        result = None

        if hasattr(te, "open"):
            result = await asyncio.to_thread(
                te.open,
                symbol,
                side_uc,
                entry=entry,
                sl=sl,
                tp=tp,
                volume=compute_lot_size(symbol, entry, sl),
            )
        elif hasattr(te, "place_order"):
            result = await asyncio.to_thread(
                te.place_order,
                symbol=symbol,
                side=side_uc,
                entry=entry,
                sl=sl,
                tp=tp,
            )
        else:
            update_trade_state(
                trade_id,
                status="REJECTED",
                signal_state="REJECTED",
                reject_reason="TradeEngine has no open/place_order method",
            )
            log.warning("TradeEngine has no supported execution method")
            return trade_id

        update_trade_state(
            trade_id,
            execution_result=str(result)[:500] if result is not None else "submitted",
        )
        return trade_id

    except Exception as e:
        log.warning("TradeEngine execution failed: %s", e)
        update_trade_state(
            trade_id,
            status="REJECTED",
            signal_state="REJECTED",
            reject_reason=str(e)[:500],
        )
        return trade_id

async def analyze_symbol(
    symbol: str,
    tf: str,
    *,
    use_cache=True,
    mark_bar=True,
    affect_emit_state=True,
    manual_scan=False,
    prefetched_raw: pd.DataFrame | None = None,
):
    try:
        raw = prefetched_raw.copy() if prefetched_raw is not None else await fetch_ohlc(
            symbol,
            tf,
            260,
            use_cache=use_cache,
        )
        if raw is None or raw.empty or len(raw) < 3:
            return None, None

        if not data_is_fresh(raw, tf, max_lag_bars=2):
            return None, None

        df = add_indicators(raw)
    except Exception as e:
        log.warning("analyze_symbol fetch/add_indicators error %s %s: %s", symbol, tf, e)
        return None, None

    if df is None or df.empty or len(df) < 3:
        return None, None

    ts_bar = pd.Timestamp(df.iloc[-2]["datetime"])
    k_base = (normalize_symbol(symbol), tf.upper())

    if is_daily_guard_active():
        return None, None
    if cooldown_active():
        return None, None

    last = df.iloc[-2]
    ts = pd.Timestamp(last["datetime"])
    if not in_trading_session(ts):
        return None, None

    atr = float(last.atr)
    adx = float(last.adx)
    rsi = float(last.rsi)
    ema50 = float(last.ema50)
    ema200 = float(last.ema200)
    close = float(last.close)

    if atr <= 0:
        return None, None
    if not is_cost_structure_valid():
        return None, None

    htf_valid = True
    try:
        raw_htf = await fetch_ohlc(symbol, HTF_TF, 260, use_cache=True)
        if raw_htf is None or raw_htf.empty or len(raw_htf) < 2:
            row_htf = None
            htf_valid = False
        else:
            if not data_is_fresh(raw_htf, HTF_TF, max_lag_bars=3):
                row_htf = None
                htf_valid = False
            else:
                htf = add_indicators(raw_htf)
                row_htf = htf.iloc[-2] if len(htf) >= 2 else None
                htf_valid = row_htf is not None
    except Exception:
        row_htf = None
        htf_valid = False

    brain_feat = {}
    try:
        if extract_last_features:
            df_closed = df.iloc[:-1].copy() if len(df) >= 2 else df.copy()
            feat_raw = extract_last_features(
                df_closed,
                symbol=normalize_symbol(symbol),
                tf=tf,
            )
            if isinstance(feat_raw, dict):
                brain_feat = feat_raw
    except Exception as e:
        log.warning("brain_feat extract failed %s %s: %s", symbol, tf, e)
        brain_feat = {}

    df_closed = df.iloc[:-1].copy() if len(df) >= 2 else df.copy()

    ema_gap = abs(ema50 - ema200)
    regime = "trend" if ema_gap > (0.15 * atr) else "chop"
    rar = range_atr_ratio_from_ohlc(df_closed.tail(20))
    is_chop = rar >= ATR_CHOP_RATIO_MAX

    flat_ema = ema_flatness(df_closed, bars=8)
    flat_ema_atr = (flat_ema / atr) if atr > 0 else 999.0
    overlap = candle_overlap_ratio(df_closed, bars=6)

    extra_chop = (flat_ema_atr <= 0.18 and overlap >= 0.60)
    is_chop = is_chop or extra_chop

    rsi_lo, rsi_hi = adaptive_bands(adx, RSI_LO_BASE, RSI_HI_BASE, ADX_STRONG)

    ai_shift, adx_shift, sr_shift = perf_adjustments()

    if os.getenv("VALIDATION_MODE", "1") == "1":
        ai_shift = 0.0
        adx_shift = 0.0
        sr_shift = 0.0

    ai_min_eff = max(40.0, AI_SCORE_MIN + ai_shift)
    adx_min_eff = max(10.0, ADX_MIN + adx_shift)
    sr_ratio_eff = min(1.50, max(0.40, SR_MAX_DIST_ATR + sr_shift))

    if is_chop:
        sr_ratio_eff = max(0.45, sr_ratio_eff - 0.2)

    try:
        sg = get_streak_adjustments()
        if getattr(sg, "active", False):
            ai_min_eff += float(getattr(sg, "ai_raise", 0.0) or 0.0)
            adx_min_eff += float(getattr(sg, "adx_bonus", 0.0) or 0.0)
            sr_ratio_eff = max(
                0.30,
                sr_ratio_eff - float(getattr(sg, "sr_tighten", 0.0) or 0.0),
            )
    except Exception:
        pass

    trend_up = ema50 > ema200
    trend_down = ema50 < ema200

    ema50_prev = float(df_closed["ema50"].iloc[-6]) if len(df_closed) >= 6 else ema50
    ema_slope_atr = (ema50 - ema50_prev) / atr
    slope_ok_long = ema_slope_atr >= -0.08
    slope_ok_short = ema_slope_atr <= 0.08

    price_ok_long = (close > (ema50 - atr * 0.35)) if PRICE_EMA_FILTER else True
    price_ok_short = (close < (ema50 + atr * 0.35)) if PRICE_EMA_FILTER else True

    ema_dist_atr = abs(close - ema50) / atr if atr > 0 else 999.0
    not_overextended = ema_dist_atr <= 1.65

    recent_slice = df_closed[["close", "ema50"]].tail(6).copy()

    below_count = int((recent_slice["close"] < recent_slice["ema50"]).sum())
    above_count = int((recent_slice["close"] > recent_slice["ema50"]).sum())

    pb_span_high = float(df_closed["high"].tail(6).max())
    pb_span_low = float(df_closed["low"].tail(6).min())
    pb_span_atr = ((pb_span_high - pb_span_low) / atr) if atr > 0 else 999.0

    weak_pullback_long = (below_count >= 4) or (pb_span_atr > 2.0 and below_count >= 3)
    weak_pullback_short = (above_count >= 4) or (pb_span_atr > 2.0 and above_count >= 3)

    gold_setup = is_gold_symbol(symbol)

    base_long_setup = (
        gold_setup
        and trend_up
        and slope_ok_long
        and price_ok_long
        and adx >= adx_min_eff
        and not_overextended
    )

    base_short_setup = (
        gold_setup
        and trend_down
        and slope_ok_short
        and price_ok_short
        and adx >= adx_min_eff
        and not_overextended
    )

    long_setup = base_long_setup
    short_setup = base_short_setup

    prev_bar = df.iloc[-3] if len(df) >= 3 else last

    bar_open = float(last.open)
    bar_high = float(last.high)
    bar_low = float(last.low)
    bar_close = float(last.close)

    prev_high = float(prev_bar.high)
    prev_low = float(prev_bar.low)

    bar_range = max(bar_high - bar_low, 1e-9)
    bar_body = abs(bar_close - bar_open)

    body_ratio = bar_body / bar_range
    close_pos_long = (bar_close - bar_low) / bar_range
    close_pos_short = (bar_high - bar_close) / bar_range

    strong_bull_close = (
        (bar_close > bar_open)
        and (body_ratio >= 0.35)
        and (close_pos_long >= 0.60)
    )

    strong_bear_close = (
        (bar_close < bar_open)
        and (body_ratio >= 0.35)
        and (close_pos_short >= 0.60)
    )

    break_prev_high = bar_close > prev_high
    break_prev_low = bar_close < prev_low

    continuation_ok_long = (
        (bar_close > bar_open)
        and (close_pos_long >= 0.55)
        and (body_ratio >= 0.25)
    )

    continuation_ok_short = (
        (bar_close < bar_open)
        and (close_pos_short >= 0.55)
        and (body_ratio >= 0.25)
    )

    pa_ok_long = strong_bull_close or continuation_ok_long or break_prev_high
    pa_ok_short = strong_bear_close or continuation_ok_short or break_prev_low

    long_key = _rsi_state_key(symbol, "long")
    short_key = _rsi_state_key(symbol, "short")

    prev_long_state = _last_rsi_state.get(long_key, "neutral")
    prev_short_state = _last_rsi_state.get(short_key, "neutral")

    score = ai_score_for_df(symbol, df, tf)
    # GOLD ENTRY QUALITY: pullback k EMA -> potvrzeni; zadne pozdni nahaneni ceny.
    recent_gold = df_closed.tail(5)
    pullback_long = bool(
        (
            (recent_gold["low"] <= recent_gold["ema50"] + atr * 0.35)
            & (recent_gold["low"] >= recent_gold["ema50"] - atr * 0.85)
        ).any()
    ) and bar_close >= ema50

    pullback_short = bool(
        (
            (recent_gold["high"] >= recent_gold["ema50"] - atr * 0.35)
            & (recent_gold["high"] <= recent_gold["ema50"] + atr * 0.85)
        ).any()
    ) and bar_close <= ema50

    late_long = (bar_close - ema50) / atr > 1.00
    late_short = (ema50 - bar_close) / atr > 1.00
    not_spike = bar_range <= atr * 1.90 and bar_body <= atr * 1.30

    # Momentum je platne pouze pri potvrzenem breaku predchozi svicky.
    strong_momentum_long = (
        break_prev_high
        and adx >= ADX_STRONG
        and score >= AI_ALERTPLUS_MIN
    )
    strong_momentum_short = (
        break_prev_low
        and adx >= ADX_STRONG
        and score >= AI_ALERTPLUS_MIN
    )

    long_setup = (
        base_long_setup
        and pullback_long
        and not late_long
        and not_spike
        and (
            pa_ok_long
            or strong_momentum_long
        )
    )


    short_setup = (
        base_short_setup
        and pullback_short
        and not late_short
        and not_spike
        and (
            pa_ok_short
            or strong_momentum_short
        )
    )
    df_pat = df.iloc[:-1] if len(df) >= 3 else df
    pat = detect_patterns(df_pat)

    # RSI je timing filtr, ne skryta podminka zavisla na stavu z predchoziho scanu.
    # Pullback a price action uz potvrzuji navrat; extremni RSI pouze blokuje chase.
    long_reentry_ready = rsi_lo <= rsi <= 68.0
    short_reentry_ready = 32.0 <= rsi <= rsi_hi

    long_c = long_setup and long_reentry_ready
    short_c = short_setup and short_reentry_ready

    if not (long_c or short_c):
        long_zone_now = rsi <= rsi_lo
        short_zone_now = rsi >= rsi_hi

        if DEBUG_SIGNALS:
            dbg.info(
                "NO-SETUP %s %s | long_c=%s short_c=%s | "
                "long_setup=%s short_setup=%s | "
                "long_ready=%s short_ready=%s | "
                "prevL=%s prevS=%s | "
                "score=%.1f ai_min=%.1f alertplus=%.1f | "
                "trend_up=%s trend_down=%s | "
                "priceL=%s priceS=%s | "
                "adx=%.1f min=%.1f strong=%.1f adx_shift=%.1f | "
                "rsi=%.1f lo=%.1f hi=%.1f | "
                "not_overext=%s ema_dist_atr=%.2f | "
                "paL=%s paS=%s body=%.2f closeL=%.2f closeS=%.2f breakH=%s breakL=%s | "
                "regime=%s chop=%s rar=%.2f | "
                "pullbackL=%s pullbackS=%s | "
                "lateL=%s lateS=%s | "
                "strongL=%s strongS=%s | ",
                symbol,
                tf,
                long_c,
                short_c,
                long_setup,
                short_setup,
                long_reentry_ready,
                short_reentry_ready,
                prev_long_state,
                prev_short_state,
                score,
                ai_min_eff,
                AI_ALERTPLUS_MIN,
                trend_up,
                trend_down,
                price_ok_long,
                price_ok_short,
                adx,
                adx_min_eff,
                ADX_STRONG,
                adx_shift,
                rsi,
                rsi_lo,
                rsi_hi,
                not_overextended,
                ema_dist_atr,
                pa_ok_long,
                pa_ok_short,
                body_ratio,
                close_pos_long,
                close_pos_short,
                break_prev_high,
                break_prev_low,
                regime,
                is_chop,
                rar,
                pullback_long,
                pullback_short,
                late_long,
                late_short,
                strong_momentum_long,
                strong_momentum_short,
            )

        if affect_emit_state:
            if long_zone_now:
                _last_rsi_state[long_key] = "armed"
            elif prev_long_state == "armed" and long_setup and rsi > rsi_lo:
                _last_rsi_state[long_key] = "armed"
            else:
                _last_rsi_state[long_key] = "neutral"

            if short_zone_now:
                _last_rsi_state[short_key] = "armed"
            elif prev_short_state == "armed" and short_setup and rsi < rsi_hi:
                _last_rsi_state[short_key] = "armed"
            else:
                _last_rsi_state[short_key] = "neutral"

        if mark_bar:
            LAST_SIG_BAR[(k_base[0], k_base[1], "any")] = ts_bar
        return None, None

    side = "long" if long_c else "short"
    k = (k_base[0], k_base[1], side)
    if mark_bar and LAST_SIG_BAR.get(k) == ts_bar:
        return None, None

    ps = pip_size(symbol)

    # S/R pocitej bez aktualni potvrzovaci svicky. Break nad/pod predchozi
    # strukturu ma volny prostor; protismerna uroven vstup neblokuje.
    structure = df_closed.iloc[:-1].tail(20)
    recent_resistance = float(structure["high"].max())
    recent_support = float(structure["low"].min())

    space_ok_long = True
    space_ok_short = True
    near_tag = "far"
    side_breakout = False

    if ps > 0 and atr > 0:
        min_space_pips = max(MIN_TP_PIPS * 0.50, (atr / ps) * 0.60)

        space_to_res_pips = (recent_resistance - close) / ps
        space_to_sup_pips = (close - recent_support) / ps

        space_ok_long = close >= recent_resistance or space_to_res_pips >= min_space_pips
        space_ok_short = close <= recent_support or space_to_sup_pips >= min_space_pips

        side_space_pips = space_to_res_pips if side == "long" else space_to_sup_pips
        side_breakout = close >= recent_resistance if side == "long" else close <= recent_support
        if side_breakout:
            near_tag = "breakout"
        elif side_space_pips < min_space_pips:
            near_tag = "blocked"
        elif side_space_pips < min_space_pips * 1.5:
            near_tag = "near"

    ok_sr = space_ok_long if side == "long" else space_ok_short

    if side == "long" and (pat["bull_engulf"] or pat["pin_long"]):
        score += 2
    if side == "short" and (pat["bear_engulf"] or pat["pin_short"]):
        score += 2

    weak_pb_pen = 0.0

    if side == "long" and weak_pullback_long:
        weak_pb_pen = 0.5

    if side == "short" and weak_pullback_short:
        weak_pb_pen = 0.5

    try:
        pen_raw = brain_penalty(symbol, side.upper(), {"tf": tf}) if BRAIN_ON else 0.0
    except Exception:
        pen_raw = 0.0
    pen_raw = max(0.0, min(1.0, pen_raw))

    brain_pen = (BRAIN_WEIGHT * min(0.6, pen_raw) * score) if BRAIN_ON else 0.0
    sr_pen = 6.0 if near_tag == "blocked" else (3.0 if near_tag == "near" else 0.0)
    chop_pen = 2.0 if (is_chop and adx < ADX_STRONG) else 0.0

    eff_score = max(
        0.0,
        min(100.0, score - brain_pen - sr_pen - chop_pen - weak_pb_pen),
    )

    long_zone_now = rsi <= rsi_lo
    short_zone_now = rsi >= rsi_hi

    if is_daily_guard_active():
        log.info("BLOCK DAILY_GUARD %s %s", symbol, tf)
        return None, None

    if HTF_EMA_CONFLUENCE and REQUIRE_FRESH_HTF and not htf_valid:
        if DEBUG_SIGNALS:
            dbg.info(
                "NO-SETUP %s %s | HTF_NOT_FRESH htf_valid=%s require_fresh=%s",
                symbol,
                tf,
                htf_valid,
                REQUIRE_FRESH_HTF,
            )
        return None, None

    has_conf = htf_confluence(last, row_htf) if HTF_EMA_CONFLUENCE else True
    conf_ok = has_conf

    if regime == "trend":
        adx_ok = adx >= adx_min_eff
    else:
        adx_ok = adx >= max(adx_min_eff, ADX_STRONG - 2.0)

    pa_ok_side = pa_ok_long if side == "long" else pa_ok_short
    strong_momentum_side = strong_momentum_long if side == "long" else strong_momentum_short

    sr_ok_for_alert = ok_sr or (
        side_breakout
        and pa_ok_side
        and adx >= adx_min_eff
    )

    # EMA pullback strategie neobchoduje chop; vysoke ADX ani AI ho neprepisuji.
    chop_ok_for_alert = not is_chop

    pa_ok_for_alert = pa_ok_side

    space_ok_side = space_ok_long if side == "long" else space_ok_short

    space_ok_for_alert = space_ok_side
    conf_ok_for_alert = conf_ok

    qualifies_alert = (
        adx_ok
        and conf_ok_for_alert
        and sr_ok_for_alert
        and chop_ok_for_alert
        and pa_ok_for_alert
        and space_ok_for_alert
    )

    qualifies_alertplus = (
        qualifies_alert
        and has_conf
        and (
            eff_score >= AI_ALERTPLUS_MIN
            or strong_momentum_side
        )
    )

    reasons = []
    if has_conf:
        reasons.append("HTF✓")
    if near_tag == "near":
        reasons.append("SR near")
    reasons.append("trend" if regime == "trend" else "chop")
    try:
        prev_adx2 = float(df.adx.iloc[-3])
        reasons.append(f"ADXΔ {adx - prev_adx2:+.1f}")
    except Exception:
        pass

    reasons_line = " | " + " · ".join(reasons) if reasons else ""

    momentum_entry = False
    if MARKET_ENTRY_ON:
        if side == "long":
            momentum_entry = (
                adx >= MARKET_ENTRY_ADX_MIN
                and break_prev_high
            )
        else:
            momentum_entry = (
                adx >= MARKET_ENTRY_ADX_MIN
                and break_prev_low
            )

    entry_mode = "market" if momentum_entry else "limit"
    signal_entry = close if momentum_entry else ema50 + (close - ema50) * 0.25
    structure_stop = (
        float(recent_gold["low"].min()) - atr * 0.10
        if side == "long"
        else float(recent_gold["high"].max()) + atr * 0.10
    )

    audit = {
        "score_raw": score,
        "score_eff": eff_score,
        "adx": adx,
        "rsi": rsi,
        "atr": atr,
        "regime": regime,
        "near_tag": near_tag,
        "has_conf": has_conf,
        "conf_ok": conf_ok,
        "htf_valid": htf_valid,
        "weak_pullback": (weak_pullback_long if side == "long" else weak_pullback_short),
        "rar": rar,
        "brain_pen": brain_pen,
        "sr_pen": sr_pen,
        "chop_pen": chop_pen,
        "reasons": reasons,
        "entry_mode": entry_mode,
        "signal_entry": signal_entry,
        "structure_stop": structure_stop,
        "momentum_entry": momentum_entry,
        "space_ok_long": space_ok_long,
        "space_ok_short": space_ok_short,
    }

    if affect_emit_state:
        if long_zone_now:
            _last_rsi_state[long_key] = "armed"
        else:
            _last_rsi_state[long_key] = "neutral"

        if short_zone_now:
            _last_rsi_state[short_key] = "armed"
        else:
            _last_rsi_state[short_key] = "neutral"

    fire_gate = True

    if manual_scan:
        fire_gate = True
        ok_emit = True
    else:
        _ce = can_emit(symbol, side, SOURCE_ANALYZER)
        ok_emit = _ce[0] if isinstance(_ce, tuple) else bool(_ce)

    brain_line = f"AI {score:.0f} → {eff_score:.0f} | BRAINpen {brain_pen:.1f} | ADX {adx:.1f}"
    d = price_decimals(symbol)

    # XAU technicky setup nesmi blokovat model natrenovany na jinych symbolech.
    alert_min_eff = 0.0 if gold_setup else ai_min_eff

    reemit_ok = _should_reemit(symbol, side, close, atr, adx)

    is_alert_candidate = (
        ((side == "long" and long_c) or (side == "short" and short_c))
        and ok_emit
        and reemit_ok
        and fire_gate
        and not BRAIN_ONLY
        and eff_score >= alert_min_eff
    )

    if is_alert_candidate:
        if qualifies_alertplus:
            txt, sl, tp, rrr, meta = mk_plan(
                symbol,
                side,
                signal_entry,
                atr,
                regime,
                structure_stop=structure_stop,
            )
            tp1 = meta.get("tp1") if isinstance(meta, dict) else None
            if txt:
                if is_gold_symbol(symbol):
                    final_msg = (
                        f"\u26a1 \U0001f7e1 GOLD ALERT+ | {symbol} {tf} | {side.upper()}"
                        f"\nPrice now: {close:.{d}f}\nEntry mode: {entry_mode.upper()}"
                        f"\n\nPLAN\n{txt}\n\nQUALITY\n{brain_line}{reasons_line}"
                    )
                else:
                    final_msg = (
                        f"\u26a1\ufe0f ALERT+ {symbol} {tf} ? {side.upper()} "
                        f"| {close:.{d}f}\nEntry mode: {entry_mode.upper()}\n{txt}\n{brain_line}{reasons_line}"
                    )
                final_kind = "alert_plus"
                if affect_emit_state:
                    created_trade_id = await _autoexec_if_enabled(
                        symbol,
                        side,
                        signal_entry,
                        sl,
                        tp,
                        tp1=tp1,
                        tf=tf,
                        brain_feat=brain_feat,
                        audit=audit,
                    )

                    if PAPER_TRADES_ON and created_trade_id is None:
                        log.info(
                            "ALERT+ paper tracking skipped/blocked; Telegram alert still sent %s %s %s",
                            symbol,
                            tf,
                            side,
                        )
                        final_msg += "\n\nTRACKING\n⚠️ Paper tracking not created → no WON/LOSS for this alert."

                    mark_emitted(symbol, side, SOURCE_ANALYZER)
                    _update_emit_trackers(symbol, side, close, atr)
                    log_alert(
                        AUTO_ALERTS_CHAT_ID,
                        symbol,
                        tf,
                        "ALERT_PLUS",
                        signal_entry,
                        sl,
                        tp,
                        adx,
                        near_tag,
                        notes=side.upper(),
                        ai=eff_score,
                        msg_type=final_kind,
                        rrr_val=rrr,
                        regime=regime,
                        rsi_val=rsi,
                        atr_val=atr,
                        weak_pullback=(weak_pullback_long if side == "long" else weak_pullback_short),
                        htf_conf=has_conf,
                    )

                    if mark_bar:
                        LAST_SIG_BAR[k] = ts_bar

                return final_msg, final_kind

        if qualifies_alert:
            txt, sl, tp, rrr, meta = mk_plan(
                symbol,
                side,
                signal_entry,
                atr,
                regime,
                structure_stop=structure_stop,
            )
            tp1 = meta.get("tp1") if isinstance(meta, dict) else None
            if txt:
                if is_gold_symbol(symbol):
                    final_msg = (
                        f"\U0001f7e1 GOLD ALERT | {symbol} {tf} | {side.upper()}"
                        f"\nPrice now: {close:.{d}f}\nEntry mode: {entry_mode.upper()}"
                        f"\n\nPLAN\n{txt}\n\nQUALITY\n{brain_line}{reasons_line}"
                    )
                else:
                    final_msg = (
                        ("\U0001f7e2" if side == "long" else "\U0001f7e5") + f" {symbol} {tf} ? "
                        f"{side.upper()} | {close:.{d}f}\nEntry mode: {entry_mode.upper()}\n{txt}\n{brain_line}{reasons_line}"
                    )
                final_kind = "alert"
                if affect_emit_state:
                    created_trade_id = await _autoexec_if_enabled(
                        symbol,
                        side,
                        signal_entry,
                        sl,
                        tp,
                        tp1=tp1,
                        tf=tf,
                        brain_feat=brain_feat,
                        audit=audit,
                    )

                    if PAPER_TRADES_ON and created_trade_id is None:
                        log.info(
                            "ALERT paper tracking skipped/blocked; Telegram alert still sent %s %s %s",
                            symbol,
                            tf,
                            side,
                        )
                        final_msg += "\n\nTRACKING\n⚠️ Paper tracking not created → no WON/LOSS for this alert."

                    mark_emitted(symbol, side, SOURCE_ANALYZER)
                    _update_emit_trackers(symbol, side, close, atr)
                    log_alert(
                        AUTO_ALERTS_CHAT_ID,
                        symbol,
                        tf,
                        "ALERT",
                        signal_entry,
                        sl,
                        tp,
                        adx,
                        near_tag,
                        notes=side.upper(),
                        ai=eff_score,
                        msg_type=final_kind,
                        rrr_val=rrr,
                        regime=regime,
                        rsi_val=rsi,
                        atr_val=atr,
                        weak_pullback=(weak_pullback_long if side == "long" else weak_pullback_short),
                        htf_conf=has_conf,
                    )
                    if mark_bar:
                        LAST_SIG_BAR[k] = ts_bar
                return final_msg, final_kind

    if DEBUG_SIGNALS:
        dbg.info(
            "NO-SIGNAL %s %s | rsi=%.1f(lo=%.1f hi=%.1f) adx=%.1f(min=%.1f) ai=%.1f(eff=%.1f al_min=%.1f) sr=%s ok_sr=%s emit=%s fire=%s conf=%s rar=%.2f",
            symbol,
            tf,
            rsi,
            rsi_lo,
            rsi_hi,
            adx,
            adx_min_eff,
            score,
            eff_score,
            alert_min_eff,
            near_tag,
            ok_sr,
            ok_emit,
            fire_gate,
            has_conf,
            rar,
        )

    if mark_bar:
        LAST_SIG_BAR[k] = ts_bar
    return None, None

def _load_trades_master() -> Dict[str, Dict[str, Any]]:
    if TRADES_MASTER.exists():
        try:
            with open(TRADES_MASTER, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}

def _atomic_write_json(path: pathlib.Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

def _save_trades_master(master: Dict[str, Dict[str, Any]]):
    _atomic_write_json(TRADES_MASTER, master)

def _ensure_trades_csv_header_v2():
    if not TRADES_CSV.exists():
        TRADES_CSV.parent.mkdir(parents=True, exist_ok=True)
        with open(TRADES_CSV, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(
                [
                    "trade_id",
                    "opened_utc",
                    "fill_utc",
                    "closed_utc",
                    "symbol",
                    "side",
                    "tf",
                    "intended_entry",
                    "fill_entry",
                    "sl",
                    "tp1",
                    "tp2",
                    "status",
                    "signal_state",
                    "reject_reason",
                    "rrr",
                    "lot_size",
                    "risk_usd",
                    "gross_pips",
                    "net_pips",
                    "gross_pnl_usd",
                    "net_pnl_usd",
                    "cost_pips",
                    "commission_usd",
                    "r",
                ]
            )

def _master_to_csv_snapshot(master: Dict[str, Dict[str, Any]]):
    _ensure_trades_csv_header_v2()
    rows = []
    for tid, t in master.items():
        if not isinstance(t, dict):
            continue
        rows.append(
            [
                tid,
                t.get("opened_utc", ""),
                t.get("fill_utc", ""),
                t.get("closed_utc", ""),
                t.get("symbol", ""),
                t.get("side", ""),
                t.get("tf", ""),
                t.get("intended_entry", t.get("entry", "")),
                t.get("fill_entry", ""),
                t.get("sl", ""),
                t.get("tp1", ""),
                t.get("tp2", t.get("tp", "")),
                t.get("status", ""),
                t.get("signal_state", ""),
                t.get("reject_reason", ""),
                t.get("rrr", ""),
                t.get("lot_size", ""),
                t.get("risk_usd", ""),
                t.get("gross_pips", ""),
                t.get("net_pips", ""),
                t.get("gross_pnl_usd", ""),
                t.get("net_pnl_usd", ""),
                t.get("cost_pips", ""),
                t.get("commission_usd", ""),
                t.get("r", ""),
            ]
        )
    try:
        rows.sort(key=lambda r: r[1] or "")
    except Exception:
        pass
    with open(TRADES_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "trade_id",
                "opened_utc",
                "fill_utc",
                "closed_utc",
                "symbol",
                "side",
                "tf",
                "intended_entry",
                "fill_entry",
                "sl",
                "tp1",
                "tp2",
                "status",
                "signal_state",
                "reject_reason",
                "rrr",
                "lot_size",
                "risk_usd",
                "gross_pips",
                "net_pips",
                "gross_pnl_usd",
                "net_pnl_usd",
                "cost_pips",
                "commission_usd",
                "r",
            ]
        )
        w.writerows(rows)

def master_upsert_open(trade_id: str, t: Dict[str, Any]):
    master = _load_trades_master()
    entry = {
        "trade_id": trade_id,
        "opened_utc": t.get("opened_utc", ""),
        "fill_utc": t.get("fill_utc", ""),
        "closed_utc": "",
        "symbol": t.get("symbol", ""),
        "side": t.get("side", ""),
        "tf": t.get("tf", BASE_TF),
        "entry": t.get("entry", ""),
        "intended_entry": t.get("intended_entry", t.get("entry", "")),
        "fill_entry": t.get("fill_entry", ""),
        "sl": t.get("sl", ""),
        "tp1": t.get("tp1", ""),
        "tp2": t.get("tp2", t.get("tp", "")),
        "status": t.get("status", "PENDING"),
        "signal_state": t.get("signal_state", "PENDING"),
        "reject_reason": t.get("reject_reason", ""),
        "rrr": t.get("rrr", ""),
        "lot_size": t.get("lot_size", ""),
        "risk_usd": t.get("risk_usd", ""),
        "gross_pips": "",
        "net_pips": "",
        "gross_pnl_usd": "",
        "net_pnl_usd": "",
        "cost_pips": t.get("cost_pips", ""),
        "commission_usd": "",
        "r": "",
        "brain_feat": t.get("brain_feat", {}),
        "audit": t.get("audit", {}),
    }
    master[trade_id] = entry
    _save_trades_master(master)
    _master_to_csv_snapshot(master)

def master_mark_closed(
    trade_id: str,
    *,
    closed_utc: str,
    status: str,
    pips: float | None = None,
    pnl_usd: float | None = None,
    r_value: float | None = None,
    rrr: float | None = None,
    lot_size: float | None = None,
    gross_pips: float | None = None,
    net_pips: float | None = None,
    gross_pnl_usd: float | None = None,
    net_pnl_usd: float | None = None,
    cost_pips: float | None = None,
    commission_usd: float | None = None,
):
    master = _load_trades_master()
    existing = master.get(trade_id, None)
    if not isinstance(existing, dict) or not existing:
        try:
            log.warning(
                "master_mark_closed: missing master entry for %s (skipping close write)",
                trade_id,
            )
        except Exception:
            pass
        return
    t = existing
    t["closed_utc"] = closed_utc or (
        dt.datetime.utcnow().replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    )
    t["status"] = (status or "").upper()
    t["signal_state"] = (status or "").upper()
    if rrr is not None:
        try:
            t["rrr"] = float(rrr)
        except Exception:
            pass
    if pips is not None:
        try:
            t["net_pips"] = round(float(pips), 2)
        except Exception:
            pass
    if pnl_usd is not None:
        try:
            t["net_pnl_usd"] = round(float(pnl_usd), 2)
        except Exception:
            pass
    if r_value is not None:
        try:
            t["r"] = round(float(r_value), 2)
        except Exception:
            pass
    if lot_size is not None:
        try:
            t["lot_size"] = round(float(lot_size), 2)
        except Exception:
            pass
    if gross_pips is not None:
        try:
            t["gross_pips"] = round(float(gross_pips), 2)
        except Exception:
            pass
    if net_pips is not None:
        try:
            t["net_pips"] = round(float(net_pips), 2)
        except Exception:
            pass
    if gross_pnl_usd is not None:
        try:
            t["gross_pnl_usd"] = round(float(gross_pnl_usd), 2)
        except Exception:
            pass
    if net_pnl_usd is not None:
        try:
            t["net_pnl_usd"] = round(float(net_pnl_usd), 2)
        except Exception:
            pass
    if cost_pips is not None:
        try:
            t["cost_pips"] = round(float(cost_pips), 2)
        except Exception:
            pass
    if commission_usd is not None:
        try:
            t["commission_usd"] = round(float(commission_usd), 2)
        except Exception:
            pass
    master[trade_id] = t
    _save_trades_master(master)
    _master_to_csv_snapshot(master)
    _daily_cache_bust()
    try:
        feat = t.get("brain_feat") or {}
        sym = (t.get("symbol") or feat.get("symbol") or "").upper()
        side = (t.get("side") or "").upper()
        if sym and side and isinstance(feat, dict) and feat:
            brain_record_result(sym, side, feat, t.get("status"))
    except Exception:
        pass


def _load_trades_state():
    if TRADES_STATE_FILE.exists():
        try:
            with open(TRADES_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return {}
        if isinstance(data, dict):
            return data
        return {}
    return {}

def _save_trades_state(st):
    _atomic_write_json(TRADES_STATE_FILE, st)

def update_trade_state(trade_id: str, **fields):
    st = _load_trades_state()
    if trade_id not in st or not isinstance(st.get(trade_id), dict):
        return
    st[trade_id].update(fields)
    _save_trades_state(st)

    master = _load_trades_master()
    if trade_id in master and isinstance(master.get(trade_id), dict):
        master[trade_id].update(fields)
        _save_trades_master(master)
        _master_to_csv_snapshot(master)

def record_result(symbol: str, side: str, status: str, r_value: float | None = None):
    global _recent_results, _daily_r, _daily_trades, _daily_wins, _daily_losses
    _ensure_daily_rollover()
    s_up = status.upper()
    _recent_results.append(s_up)
    if DREAM_ON:
        dream_log("result", {"symbol": symbol, "side": side, "status": s_up})
    try:
        apply_result(symbol, side, s_up)
    except Exception:
        pass
    try:
        streak_record_result(symbol, side, s_up)
    except Exception:
        pass
    if r_value is not None:
        try:
            r = float(r_value)
        except Exception:
            r = 0.0
    else:
        if s_up == "WIN":
            r = 1.0
        elif s_up == "LOSS":
            r = -1.0
        else:
            r = 0.0
    if s_up in ("WIN", "LOSS"):
        _daily_trades += 1
    if s_up == "WIN":
        _daily_wins += 1
    if s_up == "LOSS":
        _daily_losses += 1
    _daily_r += r

def trade_engine_fallback(
    symbol: str,
    side: str,
    entry: float,
    sl: float,
    tp: float,
    *,
    tp1: float | None = None,
    rrr: float | None = None,
    tf: str | None = None,
    brain_feat: Dict[str, Any] | None = None,
    audit: Dict[str, Any] | None = None,
):
    st = _load_trades_state()
    side_up = str(side).upper()
    if side_up not in ("LONG", "SHORT"):
        side_up = "LONG" if str(side).lower().startswith("l") else "SHORT"
    sym = normalize_symbol(symbol)

    for tid, existing in list(st.items()):
        try:
            if not isinstance(existing, dict):
                continue
            ex_sym = normalize_symbol(existing.get("symbol", ""))
            ex_side = str(existing.get("side", "")).upper()
            ex_status = str(existing.get("status", "PENDING")).upper()
            ex_signal_state = str(existing.get("signal_state", ex_status)).upper()

            if ex_status not in ("PENDING", "OPEN"):
                continue
            if ex_signal_state in ("REJECTED", "NOT_FILLED", "EXPIRED_ENTRY"):
                continue

            if ex_sym == sym:
                ex_opened = str(existing.get("opened_utc", "") or "")
                log.info(
                    "SYMBOL BLOCK %s | existing %s trade_id=%s status=%s/%s opened=%s",
                    sym,
                    ex_side,
                    str(existing.get("trade_id") or tid),
                    ex_status,
                    ex_signal_state,
                    ex_opened,
                )
                return None
        except Exception:
            continue

    if CORRELATION_GUARD:
        corr_count = _open_corr_cluster_count(st, sym, side_up)
        if corr_count >= MAX_OPEN_CORR:
            log.info(
                "CORR BLOCK %s %s | cluster limit reached (%s)",
                sym,
                side_up,
                corr_count,
            )
            return None

    trade_id = f"{sym}_{side_up}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    opened_utc = (
        dt.datetime.utcnow().replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    )
    tf_use = tf or BASE_TF
    risk_usd = ACCOUNT_EQUITY_USD * (RISK_PER_TRADE_PCT / 100.0)
    cost_pips = compute_trade_costs_pips()
    total_cost_pips = compute_total_trade_costs_pips()
    lot_size = None

    entry_mode = str((audit or {}).get("entry_mode", "limit")).lower()
    is_market = entry_mode == "market"

    fill_entry = None
    fill_utc = ""
    status = "PENDING"
    signal_state = "PENDING"

    if is_market:
        ps = pip_size(sym)
        spread_adj = SPREAD_PIPS * ps if APPLY_TRADING_COSTS else 0.0
        slippage_adj = SLIPPAGE_PIPS * ps if APPLY_TRADING_COSTS else 0.0

        if side_up == "LONG":
            fill_entry = float(entry) + spread_adj + slippage_adj
        else:
            fill_entry = float(entry) - spread_adj - slippage_adj

        # SL/TP necháváme přesně podle alertu.
        # Fill entry může být horší kvůli spread/slippage, ale plán z Telegramu se nesmí měnit.
        sl = float(sl)
        tp = float(tp)
        if tp1 is not None:
            tp1 = float(tp1)

        fill_utc = opened_utc
        status = "OPEN"
        signal_state = "FILLED"

    sizing_entry = float(fill_entry) if fill_entry is not None else float(entry)
    lot_size = compute_lot_size(sym, sizing_entry, float(sl))
    actual_risk_usd = estimated_risk_usd(sym, sizing_entry, float(sl), lot_size)
    risk_over_target = bool(actual_risk_usd > risk_usd * 1.05) if risk_usd > 0 else False

    st[trade_id] = {
        "trade_id": trade_id,
        "opened_utc": opened_utc,
        "closed_utc": "",
        "symbol": sym,
        "side": side_up,
        "tf": tf_use,
        "entry": float(entry),
        "intended_entry": float(entry),
        "fill_entry": float(fill_entry) if fill_entry is not None else None,
        "fill_utc": fill_utc,
        "sl": float(sl),
        "tp1": float(tp1) if tp1 is not None else None,
        "tp2": float(tp),
        "status": status,
        "rrr": float(rrr) if rrr is not None else None,
        "lot_size": float(lot_size),
        "risk_usd": float(risk_usd),
        "actual_risk_usd": float(actual_risk_usd),
        "risk_over_target": risk_over_target,
        "cost_pips": float(cost_pips),
        "total_cost_pips": float(total_cost_pips),
        "brain_feat": brain_feat if isinstance(brain_feat, dict) else {},
        "audit": audit if isinstance(audit, dict) else {},
        "entry_mode": entry_mode,
        "signal_state": signal_state,
        "reject_reason": "",
    }

    _save_trades_state(st)
    master_upsert_open(trade_id, st[trade_id])
    return trade_id

async def send_message(
    ctx: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    *,
    html: bool = False,
):
    try:
        await ctx.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML if html else None,
        )
    except Exception as e:
        log.warning("send_message failed %s", e)

async def send_tg_retry(
    bot,
    chat_id: int,
    text: str,
    *,
    retries: int = 3,
    delay: float = 0.7,
    html: bool = False,
):
    last_err = None
    for attempt in range(max(1, retries)):
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.HTML if html else None,
            )
            return
        except Exception as e:
            last_err = e
            await asyncio.sleep(delay * (attempt + 1))
    if last_err:
        log.warning("send_tg_retry failed: %s", last_err)

async def check_trade_results(bot):
    st = _load_trades_state()
    if not st:
        return

    changed = False
    now_ts = time.time()
    m1_touch_bars = int(os.getenv("M1_TOUCH_BARS", "12"))

    for trade_id, t in list(st.items()):
        try:
            if str(t.get("signal_state", "FILLED")).upper() == "REJECTED":
                try:
                    closed_utc = (
                        dt.datetime.utcnow().replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
                    )
                    master_mark_closed(
                        trade_id,
                        closed_utc=closed_utc,
                        status="REJECTED",
                        pips=0.0,
                        pnl_usd=0.0,
                        r_value=0.0,
                        rrr=t.get("rrr", None),
                        lot_size=float(t.get("lot_size", 0.0) or 0.0),
                        gross_pips=0.0,
                        net_pips=0.0,
                        gross_pnl_usd=0.0,
                        net_pnl_usd=0.0,
                        cost_pips=float(t.get("cost_pips", 0.0) or 0.0),
                        commission_usd=0.0,
                    )
                except Exception as e2:
                    log.warning("master_mark_closed REJECTED failed %s: %s", trade_id, e2)

                st.pop(trade_id, None)
                changed = True
                continue

            symbol = t["symbol"]
            side = str(t["side"]).upper()
            trade_tf = str(t.get("tf", BASE_TF))

            intended_entry = float(t.get("intended_entry", t.get("entry")))
            fill_entry_raw = t.get("fill_entry", None)
            fill_entry = float(fill_entry_raw) if fill_entry_raw not in (None, "", "None") else None

            sl = float(t["sl"])
            tp2 = float(t.get("tp2", t.get("tp")))

            trade_status = str(t.get("status", "PENDING")).upper()
            signal_state = str(t.get("signal_state", trade_status)).upper()
        except Exception as e:
            log.warning("Broken trade in state %s: %s", trade_id, e)
            try:
                closed_utc = (
                    dt.datetime.utcnow().replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
                )
                master_mark_closed(
                    trade_id,
                    closed_utc=closed_utc,
                    status="INVALID",
                    pips=0.0,
                    pnl_usd=0.0,
                    r_value=0.0,
                    rrr=t.get("rrr", None) if isinstance(t, dict) else None,
                )
            except Exception as e2:
                log.warning("master_mark_closed INVALID failed %s: %s", trade_id, e2)
            st.pop(trade_id, None)
            changed = True
            continue

        tp1 = t.get("tp1", None)
        tp1_hit = bool(t.get("tp1_hit", False))

        try:
            df = await fetch_ohlc(symbol, "M1", max(30, m1_touch_bars + 10), use_cache=False)
            if df is None or df.empty:
                continue

            if not data_is_fresh(df, "M1", max_lag_bars=3):
                continue

            tail = df.tail(m1_touch_bars + 1).iloc[:-1]
            if tail.empty:
                continue


            if signal_state == "PENDING" or trade_status == "PENDING":
                filled_now = False
                fill_price = intended_entry
                fill_utc = ""

                try:
                    opened_cut = pd.to_datetime(t.get("opened_utc"), utc=True)
                    if "datetime" in tail.columns:
                        tail = tail[tail["datetime"] >= (opened_cut - pd.Timedelta(seconds=2))]
                except Exception:
                    pass

                if tail.empty:
                    continue

                for bar in tail.itertuples(index=False):
                    bh = float(getattr(bar, "high"))
                    bl = float(getattr(bar, "low"))
                    bar_ts = getattr(bar, "datetime", None)

                    ps = pip_size(symbol)
                    spread_adj = SPREAD_PIPS * ps if APPLY_TRADING_COSTS else 0.0

                    if side == "LONG":
                        touched = bl <= (intended_entry + spread_adj) <= bh
                    else:
                        touched = bl <= (intended_entry - spread_adj) <= bh
                    if touched:
                        fill_utc = (
                            pd.Timestamp(bar_ts)
                            .tz_convert("UTC")
                            .isoformat()
                            .replace("+00:00", "Z")
                            if bar_ts is not None
                            else dt.datetime.utcnow().replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
                        )

                        ps = pip_size(symbol)
                        spread_adj = SPREAD_PIPS * ps if APPLY_TRADING_COSTS else 0.0

                        ts_local = (
                            pd.Timestamp(bar_ts).tz_convert(TRADING_TZ)
                            if bar_ts is not None
                            else pd.Timestamp.now("UTC").tz_convert(TRADING_TZ)
                        )
                        hour_local = ts_local.hour

                        slippage_mult = 1.0
                        if hour_local in (8, 9, 14, 15):
                            slippage_mult = 1.5

                        slippage_adj = (SLIPPAGE_PIPS * slippage_mult * ps) if APPLY_TRADING_COSTS else 0.0

                        if side == "LONG":
                            fill_price = intended_entry + spread_adj + slippage_adj
                        else:
                            fill_price = intended_entry - spread_adj - slippage_adj

                        t["status"] = "OPEN"
                        t["signal_state"] = "FILLED"
                        t["fill_entry"] = float(fill_price)
                        t["fill_utc"] = fill_utc

                        update_trade_state(
                            trade_id,
                            status="OPEN",
                            signal_state="FILLED",
                            fill_entry=float(fill_price),
                            fill_utc=fill_utc,
                        )

                        changed = True
                        filled_now = True
                        break

                if filled_now:
                    trade_status = "OPEN"
                    signal_state = "FILLED"
                    fill_entry = float(t.get("fill_entry", intended_entry))
                else:
                    try:
                        signal_opened_utc = pd.to_datetime(t.get("opened_utc"), utc=True)
                        pending_age_min = (pd.Timestamp.now("UTC") - signal_opened_utc).total_seconds() / 60.0
                    except Exception:
                        pending_age_min = 0.0

                    if pending_age_min >= ENTRY_TIMEOUT_MINUTES:
                        closed_utc = (
                            dt.datetime.utcnow().replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
                        )

                        update_trade_state(
                            trade_id,
                            status="NOT_FILLED",
                            signal_state="NOT_FILLED",
                            closed_utc=closed_utc,
                        )

                        master_mark_closed(
                            trade_id,
                            closed_utc=closed_utc,
                            status="NOT_FILLED",
                            pips=0.0,
                            pnl_usd=0.0,
                            r_value=0.0,
                            rrr=t.get("rrr", None),
                            lot_size=float(t.get("lot_size", 0.0) or 0.0),
                            gross_pips=0.0,
                            net_pips=0.0,
                            gross_pnl_usd=0.0,
                            net_pnl_usd=0.0,
                            cost_pips=0.0,
                            commission_usd=0.0,
                        )

                        if AUTO_ALERTS_CHAT_ID:
                            d = price_decimals(symbol)
                            await send_tg_retry(
                                bot,
                                AUTO_ALERTS_CHAT_ID,
                                (
                                    f"⚪ {symbol} {trade_tf} {side} -> NOT FILLED\n"
                                    f"Entry {intended_entry:.{d}f} nebyla zasažena do {ENTRY_TIMEOUT_MINUTES} min"
                                ),
                            )

                        st.pop(trade_id, None)
                        changed = True
                        continue                              

            trade_status = str(t.get("status", "PENDING")).upper()
            signal_state = str(t.get("signal_state", trade_status)).upper()

            if signal_state != "FILLED" or trade_status != "OPEN":
                continue

            if "datetime" in tail.columns:
                tail = tail.sort_values("datetime")
            else:
                tail = tail.sort_index()

            entry_cut = None
            try:
                fill_cut_src = t.get("fill_utc") or t.get("opened_utc")
                if fill_cut_src:
                    entry_cut = pd.to_datetime(fill_cut_src, utc=True)
            except Exception:
                entry_cut = None

            if entry_cut is None:
                try:
                    entry_cut = pd.to_datetime(float(t.get("opened", now_ts)), unit="s", utc=True)
                except Exception:
                    entry_cut = None

            if entry_cut is not None and "datetime" in tail.columns:
                tail = tail[tail["datetime"] >= (entry_cut - pd.Timedelta(seconds=2))]

            if tail.empty:
                continue

            last_bar = tail.iloc[-1]
            new_hi = float(last_bar["high"])
            new_lo = float(last_bar["low"])
            prev_hi = t.get("last_m1_high", None)
            prev_lo = t.get("last_m1_low", None)
            prev_eval = float(t.get("last_eval", 0.0) or 0.0)

            t["last_eval"] = now_ts
            t["last_m1_high"] = new_hi
            t["last_m1_low"] = new_lo

            if prev_hi != new_hi or prev_lo != new_lo or (now_ts - prev_eval) >= 60.0:
                changed = True
        except Exception as e:
            log.warning("check_trade_results fetch M1 failed %s: %s", symbol, e)
            continue

        hit = None
        exit_price_override = None
        exit_reason = "SL/TP"

        for bar in tail.itertuples(index=False):
            bh = float(getattr(bar, "high"))
            bl = float(getattr(bar, "low"))

            if tp1 is not None and not tp1_hit:
                try:
                    tp1f = float(tp1)
                    tp1_touch = (side == "LONG" and bh >= tp1f) or (side == "SHORT" and bl <= tp1f)
                    if tp1_touch:
                        d = price_decimals(symbol)
                        msg_tp1 = (
                            f"🟡 TP1 HIT! {symbol} {trade_tf} {side}\n"
                            f"🎯 TP1 {tp1f:.{d}f}\n"
                            f"⏳ Další cíl: TP2"
                        )
                        if AUTO_ALERTS_CHAT_ID:
                            await send_tg_retry(bot, AUTO_ALERTS_CHAT_ID, msg_tp1)
                        t["tp1_hit"] = True
                        tp1_hit = True
                        update_trade_state(trade_id, tp1_hit=True)
                        changed = True
                except Exception as e:
                    log.warning("TP1 HIT notify failed: %s", e)

            bc = float(getattr(bar, "close"))

            if EXIT_ON_TOUCH:
                tp_touch = (side == "LONG" and bh >= tp2) or (side == "SHORT" and bl <= tp2)
                sl_touch = (side == "LONG" and bl <= sl) or (side == "SHORT" and bh >= sl)
            else:
                tp_touch = (side == "LONG" and bc >= tp2) or (side == "SHORT" and bc <= tp2)
                sl_touch = (side == "LONG" and bc <= sl) or (side == "SHORT" and bc >= sl)

            if tp_touch and sl_touch:
                if TP_SL_TIE_MODE == "win":
                    hit = "WIN"
                elif TP_SL_TIE_MODE == "nearest_open":
                    bo = float(getattr(bar, "open"))
                    dist_tp = abs(tp2 - bo)
                    dist_sl = abs(sl - bo)
                    hit = "WIN" if dist_tp < dist_sl else "LOSS"
                else:
                    hit = "LOSS"
                break
            if tp_touch:
                hit = "WIN"
                break
            if sl_touch:
                hit = "LOSS"
                break

        try:
            life_start_utc = t.get("fill_utc") or t.get("opened_utc")
            opened_ts = pd.to_datetime(life_start_utc, utc=True).timestamp()
        except Exception:
            opened_ts = now_ts

        age_min = (now_ts - opened_ts) / 60.0

        if hit is None:
            if age_min >= MAX_TRADE_MINUTES:
                exit_price_override = float(last_bar["close"])
                shown_entry = fill_entry if fill_entry is not None else intended_entry
                raw_move = (
                    exit_price_override - shown_entry
                    if side == "LONG"
                    else shown_entry - exit_price_override
                )
                ps = pip_size(symbol)
                raw_pips = raw_move / ps if ps > 0 else 0.0
                exit_cost = float(t.get("cost_pips", 0.0) or 0.0)
                lots = float(t.get("lot_size", MIN_LOT_SIZE) or MIN_LOT_SIZE)
                usd_pppl = usd_per_pip_per_lot(symbol, exit_price_override)
                commission_pips = (
                    COMMISSION_PER_LOT * lots / max(usd_pppl * lots, 1e-9)
                    if APPLY_TRADING_COSTS
                    else 0.0
                )
                hit = "WIN" if raw_pips - exit_cost - commission_pips > 0 else "LOSS"
                exit_reason = "TIME"

            last_ping = float(t.get("last_watchdog_ping", 0.0))
            if age_min >= WATCHDOG_MIN_AGE_MIN and (now_ts - last_ping) >= WATCHDOG_PING_SEC:
                m1_hi = t.get("last_m1_high", None)
                m1_lo = t.get("last_m1_low", None)
                d = price_decimals(symbol)
                if m1_hi is not None and m1_lo is not None:
                    hi_lo_txt = f"{float(m1_hi):.{d}f} / {float(m1_lo):.{d}f}"
                else:
                    hi_lo_txt = "n/a"

                msg = (
                    f"🛰️ WATCHDOG {symbol} {trade_tf} {side}\n"
                    f"Age: {age_min:.0f} min | SL {sl:.{d}f} | TP2 {tp2:.{d}f}\n"
                    f"M1 hi/lo(last_closed): {hi_lo_txt}"
                )
                if AUTO_ALERTS_CHAT_ID:
                    await send_tg_retry(bot, AUTO_ALERTS_CHAT_ID, msg)
                t["last_watchdog_ping"] = now_ts
                changed = True

            continue

        rrr_state = t.get("rrr", None)

        try:
            closed_utc = (
                dt.datetime.utcnow().replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
            )
            ps = pip_size(symbol)
            exit_price = exit_price_override if exit_price_override is not None else (tp2 if hit == "WIN" else sl)

            lots = float(t.get("lot_size", MIN_LOT_SIZE) or MIN_LOT_SIZE)
            risk_usd = float(t.get("risk_usd", 0.0) or 0.0)
            exit_cost_pips = float(t.get("cost_pips", 0.0) or 0.0)
            total_cost_pips = float(t.get("total_cost_pips", exit_cost_pips) or 0.0)

            calc_entry = fill_entry if fill_entry is not None else intended_entry

            if ps > 0:
                if side == "LONG":
                    gross_pips = (exit_price - calc_entry) / ps
                else:
                    gross_pips = (calc_entry - exit_price) / ps
            else:
                gross_pips = 0.0

            if APPLY_TRADING_COSTS:
                net_pips = gross_pips - exit_cost_pips
            else:
                net_pips = gross_pips

            usd_pppl = usd_per_pip_per_lot(symbol, exit_price)
            gross_pnl_usd_val = gross_pips * usd_pppl * lots
            commission_usd_val = COMMISSION_PER_LOT * lots if APPLY_TRADING_COSTS else 0.0
            net_pnl_usd_val = (net_pips * usd_pppl * lots) - commission_usd_val

            if risk_usd > 0:
                r_value = net_pnl_usd_val / risk_usd
            else:
                if hit == "WIN":
                    try:
                        r_value = float(rrr_state) if rrr_state is not None else 1.0
                    except Exception:
                        r_value = 1.0
                elif hit == "LOSS":
                    r_value = -1.0
                else:
                    r_value = 0.0

            record_result(symbol, side, hit, r_value=r_value)

            try:
                rrr_val = float(rrr_state) if rrr_state is not None else None
            except Exception:
                rrr_val = None

            master_mark_closed(
                trade_id,
                closed_utc=closed_utc,
                status=hit,
                pips=net_pips,
                pnl_usd=net_pnl_usd_val,
                r_value=r_value,
                rrr=rrr_val,
                lot_size=lots,
                gross_pips=gross_pips,
                net_pips=net_pips,
                gross_pnl_usd=gross_pnl_usd_val,
                net_pnl_usd=net_pnl_usd_val,
                cost_pips=total_cost_pips,
                commission_usd=commission_usd_val,
            )
        except Exception as e:
            log.warning("master_mark_closed failed: %s", e)

        try:
            d = price_decimals(symbol)
            ps = pip_size(symbol)

            try:
                rrr_msg = float(rrr_state) if rrr_state is not None else None
            except Exception:
                rrr_msg = None

            if rrr_msg is None:
                shown_entry = fill_entry if fill_entry is not None else intended_entry
                risk_pips = abs(shown_entry - sl) / ps if ps > 0 else 0.0
                target_pips = abs(tp2 - shown_entry) / ps if ps > 0 else 0.0
                rrr_msg = (target_pips / risk_pips) if risk_pips > 0 else 0.0

            lots = float(t.get("lot_size", MIN_LOT_SIZE) or MIN_LOT_SIZE)
            exit_cost_pips = float(t.get("cost_pips", 0.0) or 0.0)
            total_cost_pips = float(t.get("total_cost_pips", exit_cost_pips) or 0.0)

            exit_price = exit_price_override if exit_price_override is not None else (tp2 if hit == "WIN" else sl)
            shown_entry = fill_entry if fill_entry is not None else intended_entry
            if ps > 0:
                if side == "LONG":
                    gross_pips = (exit_price - shown_entry) / ps
                else:
                    gross_pips = (shown_entry - exit_price) / ps
            else:
                gross_pips = 0.0

            net_pips = gross_pips - exit_cost_pips if APPLY_TRADING_COSTS else gross_pips
            usd_pppl = usd_per_pip_per_lot(symbol, exit_price)
            net_pnl_usd_val = (net_pips * usd_pppl * lots) - (COMMISSION_PER_LOT * lots if APPLY_TRADING_COSTS else 0.0)

            emoji = "✅" if hit == "WIN" else "❌"
            status_txt = "WON" if hit == "WIN" else "LOST"

            shown_entry = fill_entry if fill_entry is not None else intended_entry

            msg = (
                f"{emoji} {symbol} {trade_tf} {side} CLOSED → {status_txt} ({exit_reason})\n"
                f"Entry {shown_entry:.{d}f} | SL {sl:.{d}f} | TP {tp2:.{d}f}\n"
                f"RRR 1:{rrr_msg:.2f} | Lots {lots:.2f}\n"
                f"Gross {gross_pips:+.1f} pips | Net {net_pips:+.1f} pips\n"
                f"Net PnL ~{net_pnl_usd_val:+.2f} USD | Costs {total_cost_pips:.1f} pips"
            )

            if AUTO_ALERTS_CHAT_ID:
                await send_tg_retry(bot, AUTO_ALERTS_CHAT_ID, msg)
        except Exception as e:
            log.warning("send WIN/LOSS failed: %s", e)

        st.pop(trade_id, None)
        changed = True

    if changed:
        _save_trades_state(st)

def render_trades_today_summary(stats: Dict[str, Any]) -> str:
    date = stats.get("date", "")
    total = stats.get("total", 0)
    wins = stats.get("wins", 0)
    losses = stats.get("losses", 0)
    expired = stats.get("expired", 0)
    wr = stats.get("wr", 0.0)
    pnl_r = stats.get("pnl_r", 0.0)
    by_symbol = stats.get("by_symbol", {})

    lines = [
        f"📊 Trades TODAY ({date})",
        f"• Celkem: {total} | ✅ WIN: {wins} | ❌ LOSS: {losses} | 🕒 EXPIRED: {expired}",
        f"• Winrate: {wr:.1f} %",
        f"• PnL (R): {pnl_r:+.1f}R",
    ]

    if by_symbol:
        lines.append("— podle symbolů —")
        for sym, s in sorted(by_symbol.items()):
            t = s.get("total", 0) or 0
            if t <= 0:
                continue
            s_closed_for_wr = (s.get("wins", 0) or 0) + (s.get("losses", 0) or 0)
            s_wr = (s.get("wins", 0) / s_closed_for_wr * 100.0) if s_closed_for_wr else 0.0
            lines.append(
                f"{sym}: WIN {s.get('wins',0)} | LOSS {s.get('losses',0)} | EXP {s.get('expired',0)} | WR {s_wr:.1f} %"
            )

    return "\n".join(lines)

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await send_message(
        ctx,
        update.effective_chat.id,
        "👋 Nazdar! Jsem FX Sniper Copilot.\n"
        "Příkazy: /help /env /alerts /report /stats /performance /dream "
        "/daily /risk /health /trades /open /id",
    )

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await send_message(
        ctx,
        update.effective_chat.id,
        (
            "🧭 <b>Help</b>\n"
            "/alerts – okamžitý scan\n"
            "/report – přehled trhu\n"
            "/stats – winrate a tuning\n"
            "/performance – WR z Dream modu\n"
            "/dream – týdenní souhrn\n"
            "/daily – denní souhrn (trades / WR / R / guard)\n"
            "/risk – stav denního risk limitu\n"
            "/env – runtime konfigurace\n"
            "/health – heartbeat\n"
            "/trades today – přehled dnešních uzavřených obchodů\n"
            "/open – aktuálně otevřené obchody\n"
            "/id – vypíše tvoje chat_id\n"
        ),
        html=True,
    )

async def cmd_ping(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await send_message(ctx, update.effective_chat.id, "pong ✅")

async def cmd_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await send_message(
        ctx,
        update.effective_chat.id,
        f"<code>{update.effective_chat.id}</code>",
        html=True,
    )

async def cmd_alerts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await send_message(ctx, chat_id, "🧠 Scanning…")
    count = 0
    for sym in WATCHLIST:
        try:
            txt, kind = await analyze_symbol(
                sym,
                BASE_TF,
                use_cache=False,
                mark_bar=False,
                affect_emit_state=False,
                manual_scan=True,
            )
            if txt:
                await send_message(ctx, chat_id, txt)
                count += 1
        except Exception as e:
            await send_message(ctx, chat_id, f"{sym}: {e}")
    if not count:
        await send_message(ctx, chat_id, "No signals.")

async def cmd_dream(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    stats = dream_summary(DREAM_SUMMARY_DAYS)
    txt = (
        f"🌙 <b>Dream Summary ({DREAM_SUMMARY_DAYS} days)</b>\n"
        f"Alerts: {stats['alert']} | Plus: {stats['alert_plus']} | HS: {stats['headsup']}\n"
        f"Wins: {stats['wins']} | Loss: {stats['losses']}\n"
        f"WR: {stats['winrate'] or 0:.1f}% (Target {DREAM_TARGET_WINRATE}%)"
    )
    await send_message(ctx, update.effective_chat.id, txt, html=True)

async def cmd_env(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = (
        f"⚙️ <b>Runtime</b>\n"
        f"Watchlist: {', '.join(WATCHLIST)} | TF {BASE_TF} | HTF {HTF_TF}\n"
        f"REALTIME={REALTIME_MODE} | POLL={REALTIME_POLL_SEC}s | DREAM={DREAM_ON}\n"
        f"AI_MIN={AI_SCORE_MIN} | ADX_MIN={ADX_MIN} | SR_ATR={SR_MAX_DIST_ATR}\n"
        f"BRAIN={BRAIN_ON} (w={BRAIN_WEIGHT}) | TARGET_WR={TARGET_WINRATE}%\n"
        f"DYNAMIC_RRR={int(DYNAMIC_RRR)} | FIXED_RRR={FIXED_RRR}\n"
        f"CORR_GUARD={int(CORRELATION_GUARD)} | MAX_OPEN_CORR={MAX_OPEN_CORR}"
    )
    await send_message(ctx, update.effective_chat.id, txt, html=True)

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    wr = recent_winrate() or 0.0
    ai_shift, adx_shift, sr_shift = perf_adjustments()
    txt = (
        f"📊 <b>Stats</b>\n"
        f"Recent WR: {wr:.1f}% / target {TARGET_WINRATE}%\n"
        f"Shifts: AI {ai_shift:+.2f} | ADX {adx_shift:+.2f} | SR {sr_shift:+.2f}\n"
        f"Watchlist: {', '.join(WATCHLIST)}"
    )
    await send_message(ctx, update.effective_chat.id, txt, html=True)

async def cmd_performance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    stats = dream_summary(DREAM_SUMMARY_DAYS)
    wr = stats.get("winrate") or 0.0
    emoji = "💚" if wr >= DREAM_TARGET_WINRATE else "❤️"
    await send_message(
        ctx,
        update.effective_chat.id,
        f"{emoji} Winrate {wr:.1f}% vs {DREAM_TARGET_WINRATE}%",
    )

async def cmd_daily(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    stats = daily_summary()
    trades = stats["trades"]
    closed_for_wr = stats.get("closed_for_wr", stats["wins"] + stats["losses"])
    wr = (stats["wins"] / closed_for_wr * 100.0) if closed_for_wr else 0.0
    guard = "🔴 ON" if stats["guard_active"] else "🟢 OFF"
    txt = (
        f"📅 <b>Daily summary {stats['date']}</b>\n"
        f"Trades: {trades} | Wins: {stats['wins']} | Losses: {stats['losses']}\n"
        f"WR: {wr:.1f}% | P/L: {stats['r']:+.1f}R\n"
        f"Limits: max {stats['max_trades']} trades, {stats['max_losses']} losses, "
        f"{stats['max_risk_r']:+.1f}R\n"
        f"Guard: {guard}"
    )
    await send_message(ctx, update.effective_chat.id, txt, html=True)

async def cmd_risk(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    stats = daily_summary()
    trades = stats["trades"]
    closed_for_wr = stats.get("closed_for_wr", stats["wins"] + stats["losses"])
    wr = (stats["wins"] / closed_for_wr * 100.0) if closed_for_wr else 0.0
    guard = "ACTIVE 🔴" if stats["guard_active"] else "OK 🟢"
    txt = (
        f"🛡 <b>Risk status</b>\n"
        f"Dnes: {stats['date']} | Guard: {guard}\n"
        f"Trades: {trades}/{stats['max_trades']} | Losses: {stats['losses']}/{stats['max_losses']}\n"
        f"P/L: {stats['r']:+.1f}R (limit {stats['max_risk_r']:+.1f}R)\n"
        f"WR: {wr:.1f}%"
    )
    await send_message(ctx, update.effective_chat.id, txt, html=True)

async def cmd_health(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    wr = recent_winrate() or 0.0
    stats = daily_summary()
    guard = "ON" if stats["guard_active"] else "OFF"
    scan_line = "• scan: n/a"
    if WATCHLIST:
        scan_line = await _build_report_line(WATCHLIST[0], BASE_TF, use_cache=False)
    txt = (
        f"🩺 HEALTH\n"
        f"Mode: {'RT' if REALTIME_MODE else 'INT'} | POLL {REALTIME_POLL_SEC}s\n"
        f"WR: {wr:.1f}% | Watchlist: {len(WATCHLIST)} | Cache: {len(_cache)}\n"
        f"Daily: {stats['trades']}/{stats['max_trades']} trades, "
        f"{stats['losses']}/{stats['max_losses']} losses, Guard {guard}\n"
        f"{scan_line}"
    )
    await send_message(ctx, update.effective_chat.id, txt)

async def cmd_benatky(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    msg = (
        "🟥 BENÁTKY NAD JIZEROU SHORT CONFIRMED\n"
        "📉 M5 EXECUTION MODE // NO MERCY\n\n"
        "🧠 AI hallucination trading mode\n"
        "📊 ADX pretending to be useful\n"
        "💣 liquidity sink detected\n"
    )

    with open("assets/benatky.jpg", "rb") as img:
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=img,
            caption=msg
        )

async def _build_report_line(sym: str, tf: str, *, use_cache: bool) -> str:
    try:
        df_raw = await fetch_ohlc(sym, tf, 260, use_cache=use_cache)
        if df_raw is None or df_raw.empty or len(df_raw) < 3:
            return f"• {sym}: err"

        txt, kind = await analyze_symbol(
            sym,
            tf,
            use_cache=use_cache,
            mark_bar=False,
            affect_emit_state=False,
            manual_scan=True,
            prefetched_raw=df_raw,
        )

        df = add_indicators(df_raw)
        if df is None or df.empty or len(df) < 3:
            return f"• {sym}: err"

        last = df.iloc[-2]
        rsi = float(last.rsi)
        adx = float(last.adx)
        atr = float(last.atr) / pip_size(sym)
        ema50 = float(last.ema50)
        ema200 = float(last.ema200)
        trend = "↑" if ema50 > ema200 else ("↓" if ema50 < ema200 else "→")

        if txt and kind == "alert_plus":
            verdict = "⚡ alert+"
        elif txt and kind == "alert":
            verdict = "🟢/🟥 alert"
        else:
            verdict = "⏳ no setup"

        close = float(last.close)
        d = price_decimals(sym)
        ts = pd.Timestamp(last["datetime"])
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        age_min = max(0.0, (pd.Timestamp.now("UTC") - ts).total_seconds() / 60.0)
        data_txt = f"data {ts.strftime('%H:%MZ')} age {age_min:.0f}m"

        return (
            f"• {sym} {tf} {trend} | {data_txt} | close {close:.{d}f} | "
            f"RSI {int(rsi)} ADX {adx:.1f} ATR {atr:.1f}p | {verdict}"
        )
    except Exception:
        return f"• {sym}: err"

async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        now_local = pd.Timestamp.now("UTC").tz_convert(TRADING_TZ)
        lines = [f"🕔 Report {now_local.strftime('%H:%M')} ({TRADING_TZ}) – TF {REPORT_TF}"]
        for sym in WATCHLIST[:REPORT_MAX_LINES]:
            lines.append(await _build_report_line(sym, REPORT_TF, use_cache=False))
        await send_tg_retry(ctx.bot, chat_id, "\n".join(lines), retries=5, delay=1.5)
    except Exception:
        log.exception("cmd_report")

async def cmd_trades(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        text = (update.message.text or "").strip()
    except AttributeError:
        text = ""
    parts = text.split()
    arg = parts[1].lower() if len(parts) > 1 else ""
    try:
        if arg == "today":
            stats = trades_today_summary()
            txt = render_trades_today_summary(stats)
            await send_message(ctx, chat_id, txt)
        else:
            await send_message(
                ctx,
                chat_id,
                "Použij: <code>/trades today</code> – přehled dnešních uzavřených obchodů.",
                html=True,
            )
    except Exception as e:
        log.exception("cmd_trades failed: %s", e)
        await send_message(ctx, chat_id, "❌ Něco se pokazilo v /trades – mrkni do logu.")

async def cmd_open(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        st = _load_trades_state()
    except Exception as e:
        log.warning("cmd_open: load state failed: %s", e)
        st = {}
    if not st:
        await send_message(ctx, chat_id, "📂 Žádné otevřené obchody.")
        return
    lines = ["📂 Otevřené obchody:"]
    count = 0
    for _, t in st.items():
        try:
            status = str(t.get("status", "PENDING")).upper()
            sig_state = str(t.get("signal_state", status)).upper()

            if status not in ("PENDING", "OPEN"):
                continue
            if sig_state in ("REJECTED", "NOT_FILLED", "EXPIRED_ENTRY"):
                continue

            symbol = t.get("symbol", "")
            side = t.get("side", "")
            intended_entry = float(t.get("intended_entry", t.get("entry", 0.0)))
            fill_entry_raw = t.get("fill_entry", None)
            fill_entry = float(fill_entry_raw) if fill_entry_raw not in (None, "", "None") else None
            sl = float(t.get("sl", 0.0))
            tp2 = float(t.get("tp2", t.get("tp", 0.0)))
            tp1 = t.get("tp1", None)
            d = price_decimals(symbol)

            shown_entry = fill_entry if fill_entry is not None else intended_entry
            line = f"• {symbol} {side} [{status}/{sig_state}] @ {shown_entry:.{d}f} (SL {sl:.{d}f}, TP2 {tp2:.{d}f}"
            if tp1 is not None:
                line += f", TP1 {float(tp1):.{d}f}"
            line += ")"
            lines.append(line)
            count += 1
        except Exception:
            continue
    if count == 0:
        await send_message(ctx, chat_id, "📂 Žádné otevřené obchody.")
        return
    lines.insert(1, f"Počet: {count}")
    await send_message(ctx, chat_id, "\n".join(lines))

async def alerts_job(ctx: ContextTypes.DEFAULT_TYPE):
    if not AUTO_ALERTS_CHAT_ID or BRAIN_ONLY:
        return
    try:
        for sym in WATCHLIST:
            msg, kind = await analyze_symbol(sym, BASE_TF, use_cache=True)
            if msg:
                await send_tg_retry(ctx.bot, AUTO_ALERTS_CHAT_ID, msg)
    except Exception:
        log.exception("alerts_job")

async def report_job(ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = REPORT_CHAT_ID or AUTO_ALERTS_CHAT_ID
    if not chat_id:
        return
    try:
        now_local = pd.Timestamp.now("UTC").tz_convert(TRADING_TZ)
        lines = [f"🕔 Report {now_local.strftime('%H:%M')} ({TRADING_TZ}) – TF {REPORT_TF}"]
        for sym in WATCHLIST[:REPORT_MAX_LINES]:
            lines.append(await _build_report_line(sym, REPORT_TF, use_cache=True))
        await ctx.bot.send_message(chat_id=chat_id, text="\n".join(lines))
    except Exception:
        log.exception("report_job")

async def health_job(ctx: ContextTypes.DEFAULT_TYPE):
    try:
        wr = recent_winrate() or 0.0
        stats = daily_summary()
        guard = "ON" if stats["guard_active"] else "OFF"
        scan_line = "• scan: n/a"
        if WATCHLIST:
            scan_line = await _build_report_line(WATCHLIST[0], BASE_TF, use_cache=False)
        msg = (
            f"⚙️ Heartbeat | mode {'RT' if REALTIME_MODE else 'INT'} | "
            f"watch {len(WATCHLIST)} | WR {wr:.1f}%\n"
            f"Daily: {stats['trades']}/{stats['max_trades']} trades, "
            f"{stats['losses']}/{stats['max_losses']} losses, Guard {guard}\n"
            f"{scan_line}"
        )
        tgt = HEALTH_CHAT_ID or AUTO_ALERTS_CHAT_ID or REPORT_CHAT_ID
        if tgt:
            await send_tg_retry(ctx.bot, tgt, msg, retries=5, delay=1.5)
    except Exception:
        log.exception("health_job")

_trade_results_running = False

async def trade_results_job(ctx: ContextTypes.DEFAULT_TYPE):
    global _trade_results_running

    if _trade_results_running:
        return

    _trade_results_running = True
    try:
        await check_trade_results(ctx.bot)
    except Exception as e:
        log.warning("trade_results_job error: %s", e)
    finally:
        _trade_results_running = False

async def _rt_analyzer_loop(app: Application, chat_id: int, tf: str):
    log.info(
        "RT analyzer @ %s (poll=%.2fs) → chat %s",
        tf,
        REALTIME_POLL_SEC,
        chat_id,
    )
    last_trade_results_ts = 0.0
    while True:
        try:
            for sym in WATCHLIST:
                msg, kind = await analyze_symbol(sym, tf, use_cache=True)
                if msg:
                    await app.bot.send_message(chat_id=chat_id, text=msg)
        except Exception:
            log.exception("rt_loop")
        if (time.time() - last_trade_results_ts) >= TRADE_RESULTS_INTERVAL_SEC:
            try:
                await trade_results_job(type("C", (), {"bot": app.bot})())
                last_trade_results_ts = time.time()
            except Exception:
                log.exception("rt_loop_check_trade_results")
        await asyncio.sleep(max(0.2, REALTIME_POLL_SEC))

async def _post_shutdown(app_):
    try:
        if HTTP_CLIENT is not None:
            await HTTP_CLIENT.aclose()
    except Exception:
        pass

async def _startup_notify(app_):
    tgt = HEALTH_CHAT_ID or AUTO_ALERTS_CHAT_ID or REPORT_CHAT_ID
    if not tgt:
        return
    auto_state = "ON" if (AUTO_ALERTS_ON and AUTO_ALERTS_CHAT_ID and not BRAIN_ONLY) else "OFF"
    msg = (
        "🟢 FX Sniper online\n"
        f"Runtime: analyzer.py via bot.py | mode {'RT' if REALTIME_MODE else 'INT'}\n"
        f"Auto alerts: {auto_state} | every {ALERT_INTERVAL_SEC}s | first {ALERTS_FIRST}s\n"
        f"Watchlist: {', '.join(WATCHLIST)} | TF {BASE_TF} | HTF {HTF_TF}"
    )
    try:
        await app_.bot.send_message(chat_id=tgt, text=msg)
    except Exception:
        log.exception("startup_notify")

def validate_runtime_secrets():
    if not TELEGRAM_TOKEN or ":" not in TELEGRAM_TOKEN:
        raise ValueError("❌ TELEGRAM_TOKEN chybí nebo je neplatný.")
    if not TWELVE_API_KEY or len(TWELVE_API_KEY.strip()) < 8:
        raise ValueError("❌ TWELVE_API_KEY chybí nebo je neplatný.")

def main():
    global HTTP_CLIENT
    validate_runtime_secrets()

    HTTP_CLIENT = httpx.AsyncClient(timeout=10.0)

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("alerts", cmd_alerts))
    app.add_handler(CommandHandler("dream", cmd_dream))
    app.add_handler(CommandHandler("env", cmd_env))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("performance", cmd_performance))
    app.add_handler(CommandHandler("daily", cmd_daily))
    app.add_handler(CommandHandler("risk", cmd_risk))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CommandHandler("benatky", cmd_benatky))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("trades", cmd_trades))
    app.add_handler(CommandHandler("open", cmd_open))

    if not REALTIME_MODE:
        if AUTO_ALERTS_CHAT_ID and AUTO_ALERTS_ON and not BRAIN_ONLY:
            app.job_queue.run_repeating(
                alerts_job,
                interval=ALERT_INTERVAL_SEC,
                first=ALERTS_FIRST,
                name="alerts_job",
            )

        if AUTO_REPORT_ON and (REPORT_CHAT_ID or AUTO_ALERTS_CHAT_ID):
            app.job_queue.run_repeating(
                report_job,
                interval=REPORT_INTERVAL_SEC,
                first=REPORT_FIRST,
                name="report_job",
            )

        if HEALTH_ON and (HEALTH_CHAT_ID or AUTO_ALERTS_CHAT_ID or REPORT_CHAT_ID):
            app.job_queue.run_repeating(
                health_job,
                interval=HEALTH_INTERVAL_SEC,
                first=HEALTH_FIRST,
                name="health_job",
            )

        app.job_queue.run_repeating(
            trade_results_job,
            interval=TRADE_RESULTS_INTERVAL_SEC,
            first=TRADE_RESULTS_FIRST,
            name="trade_results_job",
            job_kwargs={"misfire_grace_time": 30, "coalesce": True, "max_instances": 1},
        )
        app.post_init = _startup_notify

    else:
        async def _post_init(app_):
            await _startup_notify(app_)
            tasks = []
            if AUTO_ALERTS_CHAT_ID and not BRAIN_ONLY:
                tasks.append(
                    asyncio.create_task(_rt_analyzer_loop(app_, AUTO_ALERTS_CHAT_ID, BASE_TF))
                )

            if HEALTH_ON and (HEALTH_CHAT_ID or AUTO_ALERTS_CHAT_ID or REPORT_CHAT_ID):
                app_.job_queue.run_repeating(
                    health_job,
                    interval=HEALTH_INTERVAL_SEC,
                    first=HEALTH_FIRST,
                    name="health_job_rt",
                )

            log.info("RT watchers spawned: %d", len(tasks))

        app.post_init = _post_init

    log.info("Bot running… mode=%s", "RT" if REALTIME_MODE else "INT")
    app.post_shutdown = _post_shutdown
    app.run_polling()

if __name__ == "__main__":
    main() 
