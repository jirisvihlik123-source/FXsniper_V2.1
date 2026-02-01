import sqlite3

DB_NAME = "trades.db"


def get_connection():
    return sqlite3.connect(DB_NAME)


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pair TEXT,
        timeframe TEXT,
        side TEXT,
        entry REAL,
        sl_pips REAL,
        rrr REAL,
        ai REAL,
        adx REAL,
        adx_delta REAL,
        status TEXT,        -- OPEN / CLOSED
        result TEXT,        -- WIN / LOSS / NULL
        opened_at TEXT,
        closed_at TEXT
    )
    """)

    conn.commit()
    conn.close()
