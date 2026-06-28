from __future__ import annotations
import sqlite3, json, time, hashlib, os, shutil
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
import datetime as dt
import pandas as pd

DB_PATH = Path("ai") / "memory.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

SCHEMA = r"""
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    k TEXT PRIMARY KEY,
    v TEXT
);

CREATE TABLE IF NOT EXISTS features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    symbol TEXT,
    timeframe TEXT,
    feature_json TEXT,
    pattern_tag TEXT,
    ai_score REAL,
    fingerprint TEXT,
    embedding_json TEXT,
    provenance_json TEXT,
    note TEXT
);
CREATE INDEX IF NOT EXISTS ix_features_symbol_ts ON features(symbol, ts_utc);
CREATE INDEX IF NOT EXISTS ix_features_fp ON features(fingerprint);

CREATE TABLE IF NOT EXISTS patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_tag TEXT UNIQUE,
    description TEXT,
    created_at TEXT,
    last_seen TEXT
);

CREATE TABLE IF NOT EXISTS pattern_occurrence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feature_id INTEGER,
    pattern_id INTEGER,
    ts_utc TEXT,
    symbol TEXT,
    timeframe TEXT,
    side TEXT,
    notes TEXT,
    FOREIGN KEY(feature_id) REFERENCES features(id) ON DELETE CASCADE,
    FOREIGN KEY(pattern_id) REFERENCES patterns(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_pattern_occ_symbol ON pattern_occurrence(symbol, pattern_id);

CREATE TABLE IF NOT EXISTS trade_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feature_id INTEGER,
    pattern_id INTEGER,
    ts_open TEXT,
    ts_close TEXT,
    symbol TEXT,
    timeframe TEXT,
    side TEXT,
    entry REAL,
    sl REAL,
    tp REAL,
    status TEXT,
    pnl_pips REAL,
    pnl_usd REAL,
    bars_alive INTEGER,
    meta_json TEXT,
    FOREIGN KEY(feature_id) REFERENCES features(id) ON DELETE SET NULL,
    FOREIGN KEY(pattern_id) REFERENCES patterns(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_trade_sym_close ON trade_results(symbol, ts_close);
CREATE INDEX IF NOT EXISTS ix_trade_feat ON trade_results(feature_id);

CREATE TABLE IF NOT EXISTS pattern_stats (
    pattern_id INTEGER PRIMARY KEY,
    seen_count INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    avg_pnl_pips REAL,
    last_updated TEXT,
    FOREIGN KEY(pattern_id) REFERENCES patterns(id) ON DELETE CASCADE
);
"""

def _conn():
    return sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)

def init_db():
    conn = _conn(); cur = conn.cursor()
    cur.executescript(SCHEMA)
    cur.execute("INSERT OR REPLACE INTO meta (k,v) VALUES (?,?)", ("schema_version","1"))
    conn.commit(); conn.close()

def _canonical_fingerprint(obj: Dict[str,Any]) -> str:
    keys = sorted([k for k in obj.keys() if isinstance(obj[k], (int,float,str,bool))])
    build = {k: obj[k] for k in keys}
    s = json.dumps(build, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(s.encode("utf8")).hexdigest()

def _now_iso():
    return dt.datetime.utcnow().replace(microsecond=0).isoformat()+"Z"

def save_feature(ts_utc: str, symbol: str, timeframe: str,
                 features: Dict[str,Any], pattern_tag: Optional[str]=None,
                 ai_score: Optional[float]=None,
                 provenance: Optional[Dict[str,Any]]=None,
                 embedding: Optional[List[float]]=None,
                 note: str="") -> int:
    fp = _canonical_fingerprint(features)
    conn = _conn(); cur = conn.cursor()
    emb_json = json.dumps(embedding) if embedding is not None else None
    prov_json = json.dumps(provenance) if provenance is not None else None
    cur.execute("""
        INSERT INTO features (ts_utc,symbol,timeframe,feature_json,pattern_tag,ai_score,fingerprint,embedding_json,provenance_json,note)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (ts_utc, symbol, timeframe, json.dumps(features, ensure_ascii=False), pattern_tag, ai_score, fp, emb_json, prov_json, note))
    fid = cur.lastrowid
    if pattern_tag:
        cur.execute("INSERT OR IGNORE INTO patterns (pattern_tag, description, created_at, last_seen) VALUES (?,?,?,?)",
                    (pattern_tag, "", _now_iso(), ts_utc))
        cur.execute("UPDATE patterns SET last_seen=? WHERE pattern_tag=?", (ts_utc, pattern_tag))
    conn.commit(); conn.close()
    return fid

def ensure_pattern(pattern_tag: str, description: str="") -> int:
    conn=_conn(); cur=conn.cursor()
    cur.execute("INSERT OR IGNORE INTO patterns (pattern_tag, description, created_at, last_seen) VALUES (?,?,?,?)",
                (pattern_tag, description, _now_iso(), _now_iso()))
    cur.execute("SELECT id FROM patterns WHERE pattern_tag=?", (pattern_tag,))
    row = cur.fetchone(); conn.commit(); conn.close()
    return int(row[0])

def record_pattern(feature_id: int, pattern_tag: str, ts_utc: str, symbol: str, timeframe: str, side: Optional[str]=None, notes: str="") -> int:
    pid = ensure_pattern(pattern_tag)
    conn=_conn(); cur=conn.cursor()
    cur.execute("""
        INSERT INTO pattern_occurrence (feature_id, pattern_id, ts_utc, symbol, timeframe, side, notes)
        VALUES (?,?,?,?,?,?,?)
    """, (feature_id, pid, ts_utc, symbol, timeframe, side, notes))
    occ_id = cur.lastrowid
    cur.execute("UPDATE patterns SET last_seen=? WHERE id=?", (ts_utc, pid))
    cur.execute("INSERT OR IGNORE INTO pattern_stats (pattern_id,seen_count,wins,losses,avg_pnl_pips,last_updated) VALUES (?,?,?,?,?,?)",
                (pid,0,0,0,None,_now_iso()))
    cur.execute("UPDATE pattern_stats SET seen_count = seen_count + 1, last_updated = ? WHERE pattern_id = ?",
                (_now_iso(), pid))
    conn.commit(); conn.close()
    return occ_id

def link_trade_result(feature_id: Optional[int],
                      ts_open: str, ts_close: str, symbol: str, timeframe: str,
                      side: str, entry: float, sl: float, tp: float,
                      status: str, pnl_pips: float, pnl_usd: Optional[float]=None,
                      bars_alive: Optional[int]=None, meta: Optional[Dict[str,Any]]=None) -> int:
    meta_json = json.dumps(meta or {}, ensure_ascii=False)
    conn=_conn(); cur=conn.cursor()
    pattern_id = None
    if feature_id is not None:
        cur.execute("SELECT pattern_tag FROM features WHERE id=?", (feature_id,))
        row = cur.fetchone()
        if row and row[0]:
            cur.execute("SELECT id FROM patterns WHERE pattern_tag=?", (row[0],))
            r2 = cur.fetchone()
            if r2: pattern_id = int(r2[0])
    cur.execute("""
        INSERT INTO trade_results (feature_id, pattern_id, ts_open, ts_close, symbol, timeframe, side, entry, sl, tp, status, pnl_pips, pnl_usd, bars_alive, meta_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (feature_id, pattern_id, ts_open, ts_close, symbol, timeframe, side, entry, sl, tp, status, pnl_pips, pnl_usd, bars_alive or 0, meta_json))
    tid = cur.lastrowid
    if pattern_id:
        cur.execute("INSERT OR IGNORE INTO pattern_stats (pattern_id,seen_count,wins,losses,avg_pnl_pips,last_updated) VALUES (?,?,?,?,?,?)",
                    (pattern_id,0,0,0,None,_now_iso()))
        if status == "WON":
            cur.execute("UPDATE pattern_stats SET wins = wins + 1 WHERE pattern_id=?", (pattern_id,))
        elif status == "LOST":
            cur.execute("UPDATE pattern_stats SET losses = losses + 1 WHERE pattern_id=?", (pattern_id,))
        cur.execute("SELECT AVG(pnl_pips) FROM trade_results WHERE pattern_id=?", (pattern_id,))
        avg = cur.fetchone()[0]
        cur.execute("UPDATE pattern_stats SET avg_pnl_pips=?, last_updated=? WHERE pattern_id=?", (avg, _now_iso(), pattern_id))
    conn.commit(); conn.close()
    return tid

def stats_for_pattern(pattern_tag: str, since_iso: Optional[str]=None) -> Dict[str,Any]:
    conn=_conn(); cur=conn.cursor()
    cur.execute("SELECT id FROM patterns WHERE pattern_tag=?", (pattern_tag,))
    r=cur.fetchone()
    if not r:
        conn.close()
        return {"total":0,"wins":0,"losses":0,"winrate":None,"avg_pnl_pips":None}
    pid = int(r[0])
    q_params = [pid]
    q = """
    SELECT COUNT(tr.id) as total,
           SUM(CASE WHEN tr.status='WON' THEN 1 ELSE 0 END) as wins,
           SUM(CASE WHEN tr.status='LOST' THEN 1 ELSE 0 END) as losses,
           AVG(tr.pnl_pips) as avg_pnl
    FROM trade_results tr
    WHERE tr.pattern_id = ?
    """
    if since_iso:
        q += " AND tr.ts_close >= ?"
        q_params.append(since_iso)
    cur.execute(q, q_params)
    row = cur.fetchone(); conn.close()
    total,wins,losses,avg = row if row else (0,0,0,None)
    wins=int(wins or 0); losses=int(losses or 0)
    winrate = (wins/(wins+losses)*100.0) if (wins+losses)>0 else None
    return {"total":int(total or 0),"wins":wins,"losses":losses,"winrate":winrate,"avg_pnl_pips":float(avg) if avg is not None else None}

# --- Přidaná funkce pro KROK 3 (banování slabých patternů) ---
def pattern_stats(patt: str, symbol: str, tf: str) -> dict:
    """Vrátí čistý winrate daného patternu pro symbol a timeframe"""
    conn = sqlite3.connect("ai/memory.db")
    try:
        q = """
        SELECT status FROM trade_results
        WHERE symbol = ? AND timeframe = ? AND pattern_id IN (
            SELECT id FROM patterns WHERE pattern_tag = ?
        )
        """
        df = pd.read_sql_query(q, conn, params=[symbol, tf, patt])
        if df.empty:
            return {"count": 0, "winrate": 50}
        wr = 100 * (df["status"].str.upper() == "WON").sum() / len(df)
        return {"count": len(df), "winrate": wr}
    except Exception:
        return {"count": 0, "winrate": 50}
    finally:
        conn.close()

def recent_features(symbol: str, limit: int = 200) -> List[Dict[str,Any]]:
    conn=_conn(); cur=conn.cursor()
    cur.execute("SELECT id, ts_utc, feature_json, pattern_tag, ai_score, fingerprint FROM features WHERE symbol=? ORDER BY ts_utc DESC LIMIT ?", (symbol, limit))
    rows = cur.fetchall(); conn.close()
    out=[]
    for r in rows:
        out.append({"id":r[0],"ts_utc":r[1],"features":json.loads(r[2]),"pattern_tag":r[3],"ai_score":r[4],"fingerprint":r[5]})
    return out

def query_weighted_winrate(pattern_tag: str, half_life_days: float = 90.0) -> Dict[str,Any]:
    conn=_conn(); cur=conn.cursor()
    cur.execute("SELECT id FROM patterns WHERE pattern_tag=?", (pattern_tag,))
    r=cur.fetchone()
    if not r:
        conn.close(); return {"weighted_winrate": None, "weight_sum": 0.0}
    pid=int(r[0])
    cur.execute("SELECT status, pnl_pips, ts_close FROM trade_results WHERE pattern_id=? AND status IN ('WON','LOST')", (pid,))
    rows = cur.fetchall(); conn.close()
    if not rows:
        return {"weighted_winrate": None, "weight_sum": 0.0}
    now = dt.datetime.utcnow()
    win_w = 0.0; total_w = 0.0
    for status,_,ts in rows:
        t = dt.datetime.fromisoformat(ts.replace("Z","+00:00"))
        days = max(0.0, (now - t).total_seconds() / 86400.0)
        w = 0.5 ** (days / half_life_days)
        total_w += w
        if status == "WON":
            win_w += w
    weighted_winrate = (win_w / total_w * 100.0) if total_w>0 else None
    return {"weighted_winrate": weighted_winrate, "weight_sum": total_w, "n": len(rows)}

def prune_older_than(days: int = 365):
    cutoff = (dt.datetime.utcnow() - dt.timedelta(days=days)).isoformat()+"Z"
    conn=_conn(); cur=conn.cursor()
    cur.execute("DELETE FROM trade_results WHERE ts_close < ?", (cutoff,))
    cur.execute("DELETE FROM features WHERE ts_utc < ?", (cutoff,))
    conn.commit(); conn.close()
    return True

def backup_db(dst: Optional[str]=None) -> str:
    dst = dst or f"ai/memory_backup_{dt.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copyfile(str(DB_PATH), dst)
    return dst

def export_pattern_csv(pattern_tag: str, out_path: str):
    s = stats_for_pattern(pattern_tag)
    conn=_conn(); cur=conn.cursor()
    cur.execute("SELECT tr.ts_open,tr.ts_close,tr.symbol,tr.timeframe,tr.side,tr.status,tr.pnl_pips,tr.pnl_usd,f.feature_json FROM trade_results tr LEFT JOIN features f ON tr.feature_id=f.id WHERE tr.pattern_id = (SELECT id FROM patterns WHERE pattern_tag=?)", (pattern_tag,))
    rows = cur.fetchall(); conn.close()
    with open(out_path,"w",encoding="utf8") as f:
        f.write("ts_open,ts_close,symbol,tf,side,status,pnl_pips,pnl_usd,feature_json\n")
        for r in rows:
            f.write(",".join([str(x) if x is not None else "" for x in r[:8]]) + "," + json.dumps(r[8], ensure_ascii=False) + "\n")
    return out_path
