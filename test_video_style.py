#!/usr/bin/env python3
"""
Test script to generate a video with the new styling
"""

import sqlite3
import os
import sys
from datetime import datetime

# Add current directory to path to import app functions
sys.path.insert(0, os.path.dirname(__file__))

# Import the video creation function from app.py
from app import create_video_ffmpeg

def test_video_generation():
    """Generate a test video with new styling"""

    # Connect to database and get a script
    conn = sqlite3.connect('viral_reels.db')
    conn.row_factory = sqlite3.Row
    script = conn.execute('SELECT * FROM scripts LIMIT 1').fetchone()

    if not script:
        print("[ERROR] No scripts found in database. Run the app and generate some first.")
        return False

    print(f"\n{'='*60}")
    print("TEST VIDEO GENERATION - NEW STYLING")
    print(f"{'='*60}")
    print(f"\nScript: {script['topic']}")
    print(f"Hook: {script['hook']}")
    print(f"\nNew styling:")
    print(f"  - Font: Verdana Bold, 14px")
    print(f"  - Colors: White text, Cyan outline, Magenta shadow")
    print(f"  - Layout: Centered in 1080x1080 square")
    print(f"  - Text wrap: 24 chars per line")
    print(f"  - Timing: Dynamic based on word count (4.5 words/sec)")
    print(f"  - Target: 14-22 second videos\n")

    # Create output filename
    test_dir = 'test_videos'
    os.makedirs(test_dir, exist_ok=True)

    output_path = os.path.join(test_dir, f"test_style_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")

    # Convert sqlite3.Row to dict for the function
    script_dict = dict(script)

    # Generate video (no API keys needed for basic test)
    print(f"[RENDER] Generating video...")
    print(f"  Output: {output_path}\n")

    success = create_video_ffmpeg(script_dict, output_path, None)

    if success:
        file_size = os.path.getsize(output_path) / (1024 * 1024)
        print(f"\n{'='*60}")
        print(f"[SUCCESS] Video generated successfully!")
        print(f"  File: {output_path}")
        print(f"  Size: {file_size:.2f} MB")
        print(f"{'='*60}\n")

        # Try to open the video
        print("Opening video for preview...")
        os.startfile(output_path)
        return True
    else:
        print(f"\n[FAILED] Video generation failed. Check console output above.")
        return False

    conn.close()

if __name__ == '__main__':
    test_video_generation()
