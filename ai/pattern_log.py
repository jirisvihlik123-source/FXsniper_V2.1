from __future__ import annotations
import csv
import os
import uuid
import pathlib
import datetime as dt
from typing import Optional, List, Dict, Any

# Jednotná hlavička CSV
HEADER = [
    "event_id","ts_iso","symbol","pattern","regime","session",
    "adx","atr","rsi","fvg_present","sweep_present","ai_score_at_event",
    "taken","outcome","tp_pips","sl_pips","entry_ts_iso","close_ts_iso","trade_id"
]

# Povolené outcome hodnoty
_ALLOWED_OUTCOMES = {"", "WIN", "LOSS", "EXIT"}


class PatternLogger:
    """
    CSV logger pro pattern události.
    - Při prvním použití vytvoří složku i soubor s hlavičkou.
    - log_event(...) vrací event_id (UUID4).
    - label_outcome(...) provádí bezpečný in-place update (atomický přepis).
    - mark_taken(...) a link_trade(...) jsou pohodlné helpery.
    """

    def __init__(self, csv_path: str = "logs/pattern_events.csv"):
        self.path = pathlib.Path(csv_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_header()

    # ---------- public API ----------

    def log_event(
        self,
        *,
        symbol: str,
        pattern: str,
        regime: str,
        session: str,
        adx: float,
        atr: float,
        rsi: float,
        fvg_present: int,
        sweep_present: int,
        ai_score_at_event: float,
        entry_ts: Optional[dt.datetime] = None,
        trade_id: Optional[str] = None,
        taken: int = 0
    ) -> str:
        """
        Zapíše nový event do CSV. Vrací event_id (UUID4).
        """
        event_id = str(uuid.uuid4())
        now = _utcnow()
        row = {
            "event_id": event_id,
            "ts_iso": now.isoformat(),
            "symbol": symbol,
            "pattern": pattern,
            "regime": regime,
            "session": session,
            "adx": _fmt_num(adx, 2),
            "atr": _fmt_num(atr, 6),
            "rsi": _fmt_num(rsi, 2),
            "fvg_present": int(bool(fvg_present)),
            "sweep_present": int(bool(sweep_present)),
            "ai_score_at_event": _fmt_num(ai_score_at_event, 2),
            "taken": int(bool(taken)),
            "outcome": "",
            "tp_pips": "",
            "sl_pips": "",
            "entry_ts_iso": entry_ts.isoformat() if entry_ts else "",
            "close_ts_iso": "",
            "trade_id": trade_id or "",
        }
        self._append_row(row)
        return event_id

    def mark_taken(self, *, event_id: str, taken: bool = True) -> bool:
        """Nastaví sloupec 'taken' (0/1)."""
        return self._update_fields(event_id, {"taken": int(bool(taken))})

    def link_trade(self, *, event_id: str, trade_id: str) -> bool:
        """Propojí event s trade_id a nastaví taken=1 (pro pořádek)."""
        return self._update_fields(event_id, {"trade_id": trade_id, "taken": 1})

    def label_outcome(
        self,
        *,
        event_id: str,
        outcome: str,
        tp_pips: Optional[float] = None,
        sl_pips: Optional[float] = None,
        close_ts: Optional[dt.datetime] = None
    ) -> bool:
        """
        Zapíše výsledek (WIN/LOSS/EXIT) a související metriky.
        Vrací True pokud se update povedl (event nalezen), jinak False.
        """
        if outcome not in _ALLOWED_OUTCOMES:
            raise ValueError(f"Invalid outcome '{outcome}'. Allowed: {sorted(_ALLOWED_OUTCOMES - {''})}")

        payload: Dict[str, Any] = {
            "outcome": outcome,
        }
        if tp_pips is not None:
            payload["tp_pips"] = _fmt_num(tp_pips, 1)
        if sl_pips is not None:
            payload["sl_pips"] = _fmt_num(sl_pips, 1)
        if close_ts is not None:
            payload["close_ts_iso"] = close_ts.isoformat()

        return self._update_fields(event_id, payload)

    # ---------- interní utilitky ----------

    def _write_header(self) -> None:
        with self.path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(HEADER)

    def _append_row(self, row: Dict[str, Any]) -> None:
        # Zaručíme správné pořadí sloupců
        ordered = [row.get(col, "") for col in HEADER]
        with self.path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(ordered)

    def _read_all(self) -> List[List[str]]:
        if not self.path.exists():
            self._write_header()
        with self.path.open("r", newline="", encoding="utf-8") as f:
            return list(csv.reader(f))

    def _atomic_write_rows(self, rows: List[List[str]]) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(rows)
        tmp.replace(self.path)

    def _update_fields(self, event_id: str, updates: Dict[str, Any]) -> bool:
        rows = self._read_all()
        if not rows:
            self._write_header()
            rows = [HEADER]

        header = rows[0]
        try:
            id_idx = header.index("event_id")
        except ValueError:
            # Pokud chybí hlavička, doplníme a skončíme
            rows.insert(0, HEADER)
            self._atomic_write_rows(rows)
            return False

        # Mapování názvů na indexy (rychlejší přístup)
        idx_map = {name: i for i, name in enumerate(header)}

        updated = False
        for i in range(1, len(rows)):
            if rows[i][id_idx] == event_id:
                # aplikuj updaty jen pro existující sloupce
                for k, v in updates.items():
                    if k in idx_map:
                        rows[i][idx_map[k]] = str(v)
                updated = True
                break

        if updated:
            self._atomic_write_rows(rows)
        return updated


# ---------- pomocné funkce ----------

def _utcnow() -> dt.datetime:
    return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)

def _fmt_num(x: float, digits: int) -> str:
    try:
        return f"{float(x):.{digits}f}"
    except Exception:
        return ""
