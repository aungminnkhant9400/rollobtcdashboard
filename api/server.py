#!/usr/bin/env python3
"""RolloBTC Dashboard API - SQLite backend with Google Sheets sync."""

import json
import sqlite3
import os
from datetime import datetime, timedelta
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DB_PATH = Path(__file__).parent.parent / "data" / "trades.db"
DB_PATH.parent.mkdir(exist_ok=True)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            setup TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry REAL NOT NULL,
            stop REAL NOT NULL,
            target REAL NOT NULL,
            margin REAL NOT NULL,
            notes TEXT,
            status TEXT DEFAULT 'open',
            exit_price REAL,
            pnl REAL,
            result TEXT,
            rr REAL,
            close_notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS limits (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            daily_loss REAL DEFAULT 0,
            weekly_loss REAL DEFAULT 0,
            last_reset_date TEXT,
            last_reset_week TEXT
        )
    """)
    conn.execute("""
        INSERT OR IGNORE INTO limits (id, daily_loss, weekly_loss, last_reset_date, last_reset_week)
        VALUES (1, 0, 0, ?, ?)
    """, (datetime.now().strftime("%Y-%m-%d"), datetime.now().strftime("%Y-%W")))
    conn.commit()
    conn.close()


def get_db():
    return sqlite3.connect(DB_PATH)


def check_reset():
    """Reset daily/weekly limits if needed."""
    conn = get_db()
    row = conn.execute("SELECT * FROM limits WHERE id = 1").fetchone()
    today = datetime.now().strftime("%Y-%m-%d")
    this_week = datetime.now().strftime("%Y-%W")

    updates = {}
    if row[3] != today:
        updates["daily_loss"] = 0
        updates["last_reset_date"] = today
    if row[4] != this_week:
        updates["weekly_loss"] = 0
        updates["last_reset_week"] = this_week

    if updates:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(f"UPDATE limits SET {set_clause} WHERE id = 1", list(updates.values()))
        conn.commit()
    conn.close()


class APIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/trades":
            check_reset()
            conn = get_db()
            trades = conn.execute(
                "SELECT * FROM trades ORDER BY date DESC, time DESC"
            ).fetchall()
            cols = [d[0] for d in conn.execute("SELECT * FROM trades").description]
            conn.close()
            self._send_json({"trades": [dict(zip(cols, t)) for t in trades]})

        elif path == "/api/stats":
            check_reset()
            conn = get_db()
            today = datetime.now().strftime("%Y-%m-%d")
            week_start = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%Y-%m-%d")

            total = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
            closed = conn.execute("SELECT COUNT(*) FROM trades WHERE status = 'closed'").fetchone()[0]
            wins = conn.execute("SELECT COUNT(*) FROM trades WHERE result = 'win'").fetchone()[0]
            losses = conn.execute("SELECT COUNT(*) FROM trades WHERE result = 'loss'").fetchone()[0]
            today_pnl = conn.execute(
                "SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE date = ? AND status = 'closed'",
                (today,)
            ).fetchone()[0]
            total_pnl = conn.execute(
                "SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE status = 'closed'"
            ).fetchone()[0]
            open_count = conn.execute(
                "SELECT COUNT(*) FROM trades WHERE status = 'open'"
            ).fetchone()[0]
            volume = conn.execute(
                "SELECT COALESCE(SUM(margin * 50), 0) FROM trades"
            ).fetchone()[0]

            limits = conn.execute("SELECT * FROM limits WHERE id = 1").fetchone()
            conn.close()

            self._send_json({
                "total_trades": total,
                "closed_trades": closed,
                "wins": wins,
                "losses": losses,
                "win_rate": round(wins / closed * 100, 1) if closed > 0 else 0,
                "today_pnl": round(today_pnl, 2),
                "total_pnl": round(total_pnl, 2),
                "open_positions": open_count,
                "volume": round(volume, 0),
                "balance": round(1000 + total_pnl, 2),
                "daily_loss": round(limits[1], 2),
                "weekly_loss": round(limits[2], 2),
            })

        elif path == "/api/limits":
            check_reset()
            conn = get_db()
            limits = conn.execute("SELECT * FROM limits WHERE id = 1").fetchone()
            conn.close()
            self._send_json({
                "daily_loss": limits[1],
                "weekly_loss": limits[2],
                "daily_limit": 60,
                "weekly_limit": 150,
                "max_positions": 3,
            })
        else:
            self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        content_len = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_len)) if content_len > 0 else {}

        if path == "/api/trades":
            check_reset()
            conn = get_db()
            cursor = conn.execute("""
                INSERT INTO trades (date, time, setup, direction, entry, stop, target, margin, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                body.get("date", datetime.now().strftime("%Y-%m-%d")),
                body.get("time", datetime.now().strftime("%H:%M")),
                body.get("setup", "reversal"),
                body.get("direction", "long"),
                body["entry"],
                body["stop"],
                body["target"],
                body["margin"],
                body.get("notes", ""),
            ))
            trade_id = cursor.lastrowid
            conn.commit()
            conn.close()
            self._send_json({"id": trade_id, "status": "created"})

        elif path == "/api/trades/close":
            check_reset()
            trade_id = body["id"]
            exit_price = body["exit_price"]
            result = body.get("result", "loss")
            close_notes = body.get("close_notes", "")

            conn = get_db()
            trade = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
            if not trade:
                conn.close()
                self._send_json({"error": "Trade not found"}, 404)
                return

            direction = 1 if trade[4] == "long" else -1
            price_diff = (exit_price - trade[5]) * direction
            pnl = price_diff / trade[5] * trade[8] * 50

            risk = abs(trade[5] - trade[6])
            reward = abs(exit_price - trade[5])
            rr = round(reward / risk, 1) if risk > 0 else 0

            conn.execute("""
                UPDATE trades SET
                    status = 'closed',
                    exit_price = ?,
                    pnl = ?,
                    result = ?,
                    rr = ?,
                    close_notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (exit_price, pnl, result, rr, close_notes, trade_id))

            if pnl < 0:
                conn.execute("UPDATE limits SET daily_loss = daily_loss + ?, weekly_loss = weekly_loss + ? WHERE id = 1",
                           (abs(pnl), abs(pnl)))

            conn.commit()
            conn.close()
            self._send_json({"id": trade_id, "pnl": round(pnl, 2), "result": result})

        else:
            self._send_json({"error": "Not found"}, 404)


def run_server(port=8081):
    init_db()
    server = HTTPServer(("127.0.0.1", port), APIHandler)
    print(f"RolloBTC API running on http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
