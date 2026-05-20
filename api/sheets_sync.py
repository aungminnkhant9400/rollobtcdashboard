#!/usr/bin/env python3
"""Sync trades to Google Sheets."""

import sqlite3
import json
import os
from pathlib import Path
from datetime import datetime

# Requires: pip install gspread google-auth
try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    gspread = None

DB_PATH = Path(__file__).parent.parent / "data" / "trades.db"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_sheets_client():
    """Initialize Google Sheets client from service account."""
    creds_path = Path(__file__).parent.parent / "config" / "google-service-account.json"
    if not creds_path.exists():
        return None
    if not gspread:
        return None
    creds = Credentials.from_service_account_file(str(creds_path), scopes=SCOPES)
    return gspread.authorize(creds)


def get_or_create_sheet(client, sheet_name="RolloBTC Trades"):
    """Get existing sheet or create new one."""
    if not client:
        return None
    try:
        return client.open(sheet_name).sheet1
    except gspread.SpreadsheetNotFound:
        spreadsheet = client.create(sheet_name)
        sheet = spreadsheet.sheet1
        # Header row
        headers = [
            "ID", "Date", "Time", "Setup", "Direction", "Entry", "Stop",
            "Target", "Margin", "Notes", "Status", "Exit Price", "P&L",
            "Result", "R:R", "Close Notes", "Created At", "Updated At"
        ]
        sheet.append_row(headers)
        # Share with user (optional, configure in config)
        return sheet


def sync_trades():
    """Sync all trades to Google Sheets."""
    client = get_sheets_client()
    sheet = get_or_create_sheet(client)
    if not sheet:
        print("Google Sheets not configured. Skipping sync.")
        return False

    conn = sqlite3.connect(DB_PATH)
    trades = conn.execute("SELECT * FROM trades ORDER BY id").fetchall()
    conn.close()

    if not trades:
        print("No trades to sync.")
        return True

    # Clear existing data (keep header)
    sheet.clear()
    headers = [
        "ID", "Date", "Time", "Setup", "Direction", "Entry", "Stop",
        "Target", "Margin", "Notes", "Status", "Exit Price", "P&L",
        "Result", "R:R", "Close Notes", "Created At", "Updated At"
    ]
    sheet.append_row(headers)

    # Batch append trades
    rows = []
    for t in trades:
        rows.append([
            t[0], t[1], t[2], t[3], t[4], t[5], t[6], t[7], t[8],
            t[9] or "", t[10], t[11] or "", t[12] or "", t[13] or "",
            t[14] or "", t[15] or "", t[16], t[17]
        ])

    sheet.append_rows(rows)
    print(f"Synced {len(trades)} trades to Google Sheets.")
    return True


def sync_new_trade(trade_id):
    """Sync a single new trade to Google Sheets."""
    client = get_sheets_client()
    sheet = get_or_create_sheet(client)
    if not sheet:
        return False

    conn = sqlite3.connect(DB_PATH)
    trade = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    conn.close()

    if not trade:
        return False

    sheet.append_row([
        trade[0], trade[1], trade[2], trade[3], trade[4], trade[5], trade[6],
        trade[7], trade[8], trade[9] or "", trade[10], trade[11] or "",
        trade[12] or "", trade[13] or "", trade[14] or "", trade[15] or "",
        trade[16], trade[17]
    ])
    return True


if __name__ == "__main__":
    sync_trades()
