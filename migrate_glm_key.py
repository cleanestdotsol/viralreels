#!/usr/bin/env python3
"""
Migration: Add glm_api_key column to api_keys table
Run this after updating to add GLM-4.7 Lite support
"""

import sqlite3
import os

def migrate():
    db_path = 'viral_reels.db'

    if not os.path.exists(db_path):
        print("[INFO] No database found. Nothing to migrate.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check if glm_api_key column already exists
    cursor.execute("PRAGMA table_info(api_keys)")
    columns = [col[1] for col in cursor.fetchall()]

    if 'glm_api_key' in columns:
        print("[OK] glm_api_key column already exists. Nothing to do.")
        conn.close()
        return

    # Add the glm_api_key column
    try:
        cursor.execute("ALTER TABLE api_keys ADD COLUMN glm_api_key TEXT")
        conn.commit()
        print("[OK] Successfully added glm_api_key column to api_keys table")
    except sqlite3.OperationalError as e:
        print(f"[ERROR] Migration failed: {e}")
    finally:
        conn.close()

if __name__ == '__main__':
    migrate()
