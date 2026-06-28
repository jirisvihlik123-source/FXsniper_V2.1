import os
import time
import threading
from typing import Tuple, Optional, Dict, Any

# Zdroj pro analyzer – jen textová konstanta
SOURCE_ANALYZER = "analyzer"

# Nastavení okna z .env (v sekundách)
DEDUP_WINDOW_SEC = float(os.getenv("DEDUP_WINDOW_SEC", "180"))

# In-memory cache posledních alertů:
# klíč: (SYMBOL, SIDE, SOURCE)  →  hodnota: timestamp posledního alertu
_last_emit: Dict[Tuple[str, str, str], float] = {}

# Lock pro jistotu, kdyby někdy běželo z více vláken
_lock = threading.Lock()


def _key(symbol: str, side: str, source: str) -> Tuple[str, str, str]:
    return (
        (symbol or "").strip().upper(),
        (side or "").strip().upper(),
        (source or "").strip(),
    )


def can_emit(symbol: str, side: str, source: str = SOURCE_ANALYZER) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Vrátí (True, None), pokud můžeme poslat nový alert.

    Vrátí (False, info_dict), pokud:
      - poslední alert stejného (symbol, side, source)
      - byl méně než DEDUP_WINDOW_SEC sekund zpátky.

    info_dict může obsahovat info pro debug (kolik času uběhlo, kolik zbývá).
    """
    now = time.time()
    k = _key(symbol, side, source)

    with _lock:
        last = _last_emit.get(k)
        if last is None:
            # ještě nikdy nic nešlo → můžeme emitnout
            return True, None

        dt = now - last
        if dt >= DEDUP_WINDOW_SEC:
            # okno vypršelo → můžeme znovu emitnout
            return True, {"since": dt, "left": 0.0}

        # ještě je moc brzo → zakážeme emit
        return False, {"since": dt, "left": max(0.0, DEDUP_WINDOW_SEC - dt)}


def mark_emitted(symbol: str, side: str, source: str = SOURCE_ANALYZER) -> None:
    """
    Zaznamená, že jsme právě poslali alert pro (symbol, side, source).
    """
    now = time.time()
    k = _key(symbol, side, source)
    with _lock:
        _last_emit[k] = now
