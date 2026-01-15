#!/usr/bin/env python3
"""
Database Migration Script
Adds missing columns to existing database
"""

import sqlite3
import os

DATABASE = 'viral_reels.db'

def migrate_database():
    """Add new columns to existing tables"""
    
    if not os.path.exists(DATABASE):
        print("❌ Database not found. Run the main app first to create it.")
        return
    
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    
    print("🔄 Migrating database...")
    
    try:
        # Add ai_provider column to api_keys table
        print("  Adding ai_provider column...")
        c.execute("ALTER TABLE api_keys ADD COLUMN ai_provider TEXT DEFAULT 'manual'")
        print("  ✓ Added ai_provider")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            print("  ℹ ai_provider already exists")
        else:
            print(f"  ⚠ Error: {e}")
    
    try:
        # Add openrouter_api_key column
        print("  Adding openrouter_api_key column...")
        c.execute("ALTER TABLE api_keys ADD COLUMN openrouter_api_key TEXT")
        print("  ✓ Added openrouter_api_key")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            print("  ℹ openrouter_api_key already exists")
        else:
            print(f"  ⚠ Error: {e}")
    
    try:
        # Add auto_share_to_story column
        print("  Adding auto_share_to_story column...")
        c.execute("ALTER TABLE api_keys ADD COLUMN auto_share_to_story BOOLEAN DEFAULT 1")
        print("  ✓ Added auto_share_to_story")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            print("  ℹ auto_share_to_story already exists")
        else:
            print(f"  ⚠ Error: {e}")
    
    # Set all existing users to manual mode
    print("  Setting all users to manual mode...")
    c.execute("UPDATE api_keys SET ai_provider = 'manual'")
    print("  ✓ Updated existing users")
    
    # Create prompts table if it doesn't exist
    try:
        print("  Creating prompts table...")
        c.execute('''
            CREATE TABLE IF NOT EXISTS prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                system_prompt TEXT NOT NULL,
                topics TEXT,
                num_scripts INTEGER DEFAULT 10,
                is_active BOOLEAN DEFAULT 0,
                is_default BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMP,
                times_used INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        print("  ✓ Created prompts table")
    except sqlite3.OperationalError as e:
        if "already exists" in str(e).lower():
            print("  ℹ prompts table already exists")
        else:
            print(f"  ⚠ Error: {e}")
    
    conn.commit()
    conn.close()
    
    print("\n✅ Migration complete!")
    print("\nℹ️  Restart your app now: python app.py")

if __name__ == "__main__":
    print("\n" + "="*60)
    print("DATABASE MIGRATION")
    print("="*60 + "\n")
    
    migrate_database()
    
    print("\n" + "="*60)
