from __future__ import annotations
from pathlib import Path
from typing import List, Optional, Dict, Any
import json, time, shutil

MODELS_DIR   = Path("ai/models")
ONLINE_DIR   = MODELS_DIR / "current_online"
GLOBAL_PATH  = MODELS_DIR / "current_global.pkl"
GLOBAL_META  = GLOBAL_PATH.with_suffix(".json")
HISTORY_DIR  = MODELS_DIR / "history"

def _ensure_dirs():
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    ONLINE_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

def list_online_models() -> List[str]:
    """Seznam dostupných online modelů per-symbol (souborů .pkl)."""
    _ensure_dirs()
    return sorted([p.stem for p in ONLINE_DIR.glob("*.pkl")])

def get_global_meta() -> Dict[str, Any]:
    """Načti metadata globálního modelu (pokud existují)."""
    _ensure_dirs()
    if GLOBAL_META.exists():
        try:
            return json.loads(GLOBAL_META.read_text())
        except Exception:
            pass
    return {"exists": GLOBAL_PATH.exists(), "path": str(GLOBAL_PATH)}

def promote_global(src_model_path: str, extra_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    „Povýší“ zadaný model (soubor .pkl) na current_global.pkl a vytvoří snapshot do history/.
    """
    _ensure_dirs()
    src = Path(src_model_path)
    if not src.exists():
        raise FileNotFoundError(f"Model nenalezen: {src}")

    # zkopíruj jako current_global
    shutil.copy2(src, GLOBAL_PATH)

    # ulož snapshot do history
    stamp = time.strftime("%Y%m%d-%H%M%S")
    hist_path = HISTORY_DIR / f"global_{stamp}.pkl"
    shutil.copy2(src, hist_path)

    meta = {
        "saved_at": stamp,
        "source": str(src.resolve()),
        "path": str(GLOBAL_PATH.resolve()),
        "history": str(hist_path.resolve())
    }
    if extra_meta:
        meta.update(extra_meta)

    GLOBAL_META.write_text(json.dumps(meta, indent=2))
    return meta

def rollback_global_to(history_model_path: str) -> Dict[str, Any]:
    """
    Vrátí current_global na konkrétní soubor z history/.
    """
    _ensure_dirs()
    src = Path(history_model_path)
    if not src.exists():
        raise FileNotFoundError(f"History model nenalezen: {src}")

    shutil.copy2(src, GLOBAL_PATH)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    meta = {
        "rolled_back_at": stamp,
        "path": str(GLOBAL_PATH.resolve()),
        "from_history": str(src.resolve())
    }
    GLOBAL_META.write_text(json.dumps(meta, indent=2))
    return meta

def prune_history(keep: int = 10) -> int:
    """
    Udržovací funkce: nechá posledních `keep` globálních snapshotů, starší smaže.
    Vrací počet smazaných souborů.
    """
    _ensure_dirs()
    snaps = sorted(HISTORY_DIR.glob("global_*.pkl"), key=lambda p: p.stat().st_mtime, reverse=True)
    trash = snaps[keep:]
    for p in trash:
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass
    return len(trash)
