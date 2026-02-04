import sqlite3
import os

DB_PATH = "/data/signals.db"

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    os.makedirs("/data", exist_ok=True)
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS open_signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pair TEXT,
        ai REAL,
        adx REAL,
        timestamp TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS closed_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pair TEXT,
        ai REAL,
        adx REAL,
        result TEXT,
        timestamp TEXT
    )
    """)

    conn.commit()
    conn.close()
