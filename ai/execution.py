#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ai.execution — TradeEngine „produktová“ verze (safe stub)

Co umí:
- Čte AUTO_EXEC_ON / AUTOEXEC_ON a EXECUTION_MODE z .env
- Připraví objednávku: symbol, side, entry, SL, TP, volume
- Zkontroluje, jestli SL/TP nejsou moc blízko (v pipech)
- Podle .env může SL/TP automaticky posunout dál od ceny (aby nepadalo „Invalid SL/TP“)
- Všechno loguje do execution_log.json
- ZATÍM NEDĚLÁ reálnou exekuci na brokerovi (MT5 apod.) → jen simulace

Env přepínače, se kterými pracuje navíc:
- MIN_STOP_DISTANCE_PIPS  … minimální vzdálenost SL od vstupu (v pipech)
- MIN_TP_PIPS             … minimální vzdálenost TP od vstupu (v pipech)
- AUTO_ADJUST_STOPS       … 1 = SL/TP automaticky upravit; 0 = obchod odmítnout
- BROKER_MIN_STOP_PIPS    … volitelné, známý min. stop level brokera v pipech
"""

from __future__ import annotations

import os
import time
import json
import logging
import pathlib
from typing import Any, Dict, Optional

log = logging.getLogger("execution")

# Základní log dir (stejný jako v analyzeru)
LOG_DIR = pathlib.Path(os.getenv("LOG_DIR", "logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

EXECUTION_LOG_FILE = pathlib.Path(
    os.getenv("EXECUTION_LOG_FILE", str(LOG_DIR / "execution_log.json"))
)


class TradeEngine:
    """
    Jednoduchý „bridge“ mezi analyzerem a reálnou exekucí.

    Aktuálně:
    - pokud AUTO_EXEC_ON / AUTOEXEC_ON = "1" → enabled=True (simulovaná exekuce)
    - pokud = "0" → jen zaloguje payload s enabled=False (AUTO_EXEC_OFF)
    - Kontroluje, jestli SL/TP nejsou moc blízko (min. počet pipů)
    - Podle AUTO_ADJUST_STOPS SL/TP buď:
        - automaticky posune dál (bezpečnější pro MT5)
        - nebo obchod odmítne (ok=False, reason="STOPS_TOO_CLOSE")

    Budoucí MT5 integrace:
    - do metody _send_to_broker(...) se doplní MT5 / jiný broker
    """

    def __init__(self, **kwargs: Any):
        # AUTO_EXEC_ON / AUTOEXEC_ON → jestli se má reálně posílat na bridge
        auto_exec_on = os.getenv("AUTO_EXEC_ON", os.getenv("AUTOEXEC_ON", "0"))
        self.enabled: bool = (auto_exec_on == "1")

        # EXECUTION_MODE z .env (TOUCH, MARKET…) – zatím jen informativní
        self.mode: str = os.getenv("EXECUTION_MODE", "TOUCH").upper()

        # defaulty pro risk / velikost pozice (zatím spíš informativní)
        self.default_capital: float = self._safe_float(
            os.getenv("DEFAULT_CAPITAL", "1000"), 1000.0
        )
        self.default_risk_pct: float = self._safe_float(
            os.getenv("DEFAULT_RISK_PCT", "1.0"), 1.0
        )

        self.slippage_pips: float = self._safe_float(
            os.getenv("SLIPPAGE_PIPS", "0.8"), 0.8
        )
        self.commission_per_lot: float = self._safe_float(
            os.getenv("COMMISSION_PER_LOT", "7"), 7.0
        )

        # Bezpečnostní limity pro SL/TP
        self.min_stop_distance_pips: float = self._safe_float(
            os.getenv("MIN_STOP_DISTANCE_PIPS", "0.0"), 0.0
        )
        self.min_tp_pips: float = self._safe_float(
            os.getenv("MIN_TP_PIPS", "0.0"), 0.0
        )

        # Volitelný broker stop level v pipech (když víš, že tvůj broker má např. min 3 pips)
        self.broker_min_stop_pips: float = self._safe_float(
            os.getenv("BROKER_MIN_STOP_PIPS", "0.0"), 0.0
        )

        # Jestli má engine SL/TP sám upravit, nebo obchod radši odmítnout
        self.auto_adjust_stops: bool = os.getenv("AUTO_ADJUST_STOPS", "1") == "1"

        log.info(
            "TradeEngine init | enabled=%s | mode=%s | capital=%.2f | risk=%.2f%% | "
            "min_stop_pips=%.2f | min_tp_pips=%.2f | broker_min_stop_pips=%.2f | auto_adjust_stops=%s",
            self.enabled,
            self.mode,
            self.default_capital,
            self.default_risk_pct,
            self.min_stop_distance_pips,
            self.min_tp_pips,
            self.broker_min_stop_pips,
            self.auto_adjust_stops,
        )

    # ---------------------------------------------------------
    # HELPERY
    # ---------------------------------------------------------

    @staticmethod
    def _safe_float(raw: str, default: float) -> float:
        try:
            return float(raw)
        except Exception:
            return default

    @staticmethod
    def _pip_value(symbol: str, price: Optional[float] = None) -> float:
        """
        Hrubý odhad pip value pro FX páry:
        - XJPY → pip ≈ 0.01
        - ostatní majory (EURUSD, GBPUSD...) → pip ≈ 0.0001

        Je to jen pro přepočet vzdálenosti na pipy, ne pro P/L.
        """
        sym = symbol.upper()
        if sym.startswith("XAU") or sym in ("GOLD", "XAU/USD"):
            return 0.01
        if sym.endswith("JPY"):
            return 0.01
        return 0.0001

    def _calc_position_size(
        self,
        symbol: str,
        entry: float,
        sl: float,
        *,
        risk_pct: Optional[float] = None,
    ) -> float:
        """
        Hodně zjednodušený výpočet velikosti pozice (lotů).
        NIC neřeší přesně, je to jen info pro log.
        """
        rpct = risk_pct if risk_pct is not None else self.default_risk_pct
        if rpct <= 0:
            return 0.01  # minilot jako default

        risk_money = self.default_capital * (rpct / 100.0)
        sl_dist = abs(entry - sl)

        if sl_dist <= 0:
            return 0.01

        pip_size = self._pip_value(symbol, entry)
        stop_pips = sl_dist / max(pip_size, 1e-9)
        usd_per_pip = 1.0 if symbol.upper().startswith("XAU") else 10.0
        size = max(0.01, min(1.00, risk_money / max(stop_pips * usd_per_pip, 1e-9)))
        return round(size, 2)

    def _append_log(self, payload: Dict[str, Any]) -> None:
        """
        Uloží objednávku do execution_log.json (append JSON list).
        Bezpečné – když se něco rozbije, jen zaloguje warning.
        """
        try:
            if EXECUTION_LOG_FILE.exists():
                try:
                    with open(EXECUTION_LOG_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    data = []
            else:
                data = []

            if not isinstance(data, list):
                data = []

            data.append(payload)

            EXECUTION_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(EXECUTION_LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            log.warning("TradeEngine _append_log failed: %s", e)

    def _check_and_adjust_stops(
        self,
        symbol: str,
        side: str,
        entry: float,
        sl: float,
        tp: float,
    ) -> Dict[str, Any]:
        """
        Zkontroluje SL/TP v pipech a případně je upraví, aby:
        - SL byl dostatečně daleko od entry (min_stop_pips / broker_min_stop_pips)
        - TP byl alespoň MIN_TP_PIPS od entry

        Vrací dict:
        {
            "entry": ...,
            "sl": ...,
            "tp": ...,
            "sl_pips": ...,
            "tp_pips": ...,
            "adjusted": True/False,
            "reject": True/False,
            "reason": "...",
        }
        """
        pip_val = self._pip_value(symbol, entry)
        min_stop = max(self.min_stop_distance_pips, self.broker_min_stop_pips, 0.0)
        min_tp = max(self.min_tp_pips, 0.0)

        side_uc = side.upper()
        is_long = side_uc == "LONG"

        sl_dist_pips = abs(entry - sl) / pip_val if pip_val > 0 else 0.0
        tp_dist_pips = abs(entry - tp) / pip_val if pip_val > 0 else 0.0

        adjusted = False
        reject = False
        reason = ""

        # 1) SL příliš blízko? (typický zdroj "Invalid SL/TP" u brokera)
        if min_stop > 0 and sl_dist_pips < min_stop:
            if not self.auto_adjust_stops:
                reject = True
                reason = f"SL too close ({sl_dist_pips:.2f} < {min_stop:.2f} pips)"
            else:
                # Posunout SL dál od entry podle směru obchodu
                if is_long:
                    sl = entry - min_stop * pip_val
                else:
                    sl = entry + min_stop * pip_val
                sl_dist_pips = min_stop
                adjusted = True
                reason = f"SL auto-adjusted to {min_stop:.2f} pips"

        # 2) TP moc blízko? (ať TP není hned vedle entry)
        if not reject and min_tp > 0 and tp_dist_pips < min_tp:
            if not self.auto_adjust_stops:
                reject = True
                if reason:
                    reason += "; "
                reason += f"TP too close ({tp_dist_pips:.2f} < {min_tp:.2f} pips)"
            else:
                # TP posuneme dál od entry podle směru
                if is_long:
                    tp = entry + min_tp * pip_val
                else:
                    tp = entry - min_tp * pip_val
                tp_dist_pips = min_tp
                adjusted = True
                if reason:
                    reason += "; "
                reason += f"TP auto-adjusted to {min_tp:.2f} pips"

        return {
            "entry": float(entry),
            "sl": float(sl),
            "tp": float(tp),
            "sl_pips": float(sl_dist_pips),
            "tp_pips": float(tp_dist_pips),
            "adjusted": adjusted,
            "reject": reject,
            "reason": reason,
        }

    def _send_to_broker(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Místo, kde bude v budoucnu MT5 / broker bridge.

        Teď:
        - pouze zaloguje, že by posílal objednávku
        - vrátí ok=True (simulovaná exekuce)

        Později:
        - tady se udělá volání MetaTrader5.order_send nebo vlastního API
        - zpracuje se odpověď brokera (ticket, error code...)
        """
        log.info("TradeEngine.open (SIMULATED SEND) %s", payload)
        return {
            "ok": True,
            "order_id": payload.get("order_id"),
            "details": payload,
        }

    # ---------------------------------------------------------
    # HLAVNÍ API – používá ho analyzer.py
    # ---------------------------------------------------------

    def open(
        self,
        symbol: str,
        side: str,
        *,
        entry: float,
        sl: float,
        tp: float,
        volume: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Hlavní metoda volaná z analyzeru:

        te = TradeEngine()
        te.open(symbol, side_uc, entry=entry, sl=sl, tp=tp)

        - pokud je AUTO_EXEC_OFF → objednávku jen zaloguje jako „disabled“
        - pokud je ON → zkontroluje SL/TP vzdálenost, případně upraví
        - v budoucnu tady bude reálné volání na MT5 / brokera
        """
        ts = time.time()
        side_uc = side.upper().strip()
        order_id = f"{symbol}_{side_uc}_{int(ts)}"

        # Vypočet velikosti pozice (informativně)
        if volume is None:
            volume = self._calc_position_size(symbol, entry, sl)

        # Zkontrolovat a případně upravit SL/TP (aby broker neřval)
        stops_info = self._check_and_adjust_stops(symbol, side_uc, entry, sl, tp)
        sl_adj = stops_info["sl"]
        tp_adj = stops_info["tp"]

        payload: Dict[str, Any] = {
            "ts": ts,
            "order_id": order_id,
            "symbol": symbol,
            "side": side_uc,
            "entry": float(entry),
            "sl": float(sl_adj),
            "tp": float(tp_adj),
            "volume": float(volume),
            "mode": self.mode,
            "enabled": self.enabled,
            "risk_pct": self.default_risk_pct,
            "capital": self.default_capital,
            "slippage_pips": self.slippage_pips,
            "commission_per_lot": self.commission_per_lot,
            "min_stop_distance_pips": self.min_stop_distance_pips,
            "min_tp_pips": self.min_tp_pips,
            "broker_min_stop_pips": self.broker_min_stop_pips,
            "stops_info": stops_info,
        }

        # Pokud jsou stopky moc blízko a auto_adjust_stops=0 → obchod odmítneme
        if stops_info["reject"]:
            payload["enabled"] = False
            payload["reject_reason"] = stops_info["reason"]
            self._append_log(payload)
            log.info("TradeEngine.open REJECTED (stops too close) %s", payload)
            return {
                "ok": False,
                "reason": "STOPS_TOO_CLOSE",
                "order_id": order_id,
                "details": payload,
            }

        # log do souboru (co by se posílalo na brokera)
        self._append_log(payload)

        if not self.enabled:
            # AUTO_EXEC_OFF → nic reálně neposílat, jen log
            log.info("TradeEngine.open (AUTO_EXEC_OFF) %s", payload)
            return {
                "ok": False,
                "reason": "AUTO_EXEC_OFF",
                "order_id": order_id,
                "details": payload,
            }

        # Tady (v budoucnu) proběhne reálná exekuce přes brokera
        result = self._send_to_broker(payload)
        return result
