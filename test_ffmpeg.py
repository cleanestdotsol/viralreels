#!/usr/bin/env python3
"""
Simple Working Video Generator
Creates text-on-black videos using FFmpeg
"""

import subprocess
import json
import os
from pathlib import Path

def create_video_simple(script, output_path):
    """
    Create a text-on-black video with improved styling
    
    Args:
        script: Dict with hook, fact1-4, payoff
        output_path: Where to save the video
    
    Returns:
        True if successful, False otherwise
    """
    
    print(f"\n🎬 Creating video: {script['topic']}")
    
    # Create a subtitle file
    srt_path = output_path.replace('.mp4', '.srt')
    
    # Helper to wrap text so it doesn't clip
    def wrap_text(text, max_chars=35):
        """Wrap text to fit on screen"""
        words = text.split()
        lines = []
        current_line = []
        current_length = 0
        
        for word in words:
            if current_length + len(word) + 1 <= max_chars:
                current_line.append(word)
                current_length += len(word) + 1
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]
                current_length = len(word)
        
        if current_line:
            lines.append(' '.join(current_line))
        
        return '\\N'.join(lines)  # \N = line break in subtitle format
    
    # Build subtitle content with wrapped text
    srt_content = []
    
    # Hook (0-3 seconds)
    srt_content.append("1")
    srt_content.append("00:00:00,000 --> 00:00:03,000")
    srt_content.append(wrap_text(script['hook']))
    srt_content.append("")
    
    # Fact 1 (3-8 seconds)
    srt_content.append("2")
    srt_content.append("00:00:03,000 --> 00:00:08,000")
    srt_content.append(wrap_text(script['fact1']))
    srt_content.append("")
    
    # Fact 2 (8-13 seconds)
    srt_content.append("3")
    srt_content.append("00:00:08,000 --> 00:00:13,000")
    srt_content.append(wrap_text(script['fact2']))
    srt_content.append("")
    
    # Fact 3 (13-18 seconds)
    srt_content.append("4")
    srt_content.append("00:00:13,000 --> 00:00:18,000")
    srt_content.append(wrap_text(script['fact3']))
    srt_content.append("")
    
    # Fact 4 (18-23 seconds)
    srt_content.append("5")
    srt_content.append("00:00:18,000 --> 00:00:23,000")
    srt_content.append(wrap_text(script['fact4']))
    srt_content.append("")
    
    # Payoff (23-30 seconds)
    srt_content.append("6")
    srt_content.append("00:00:23,000 --> 00:00:30,000")
    srt_content.append(wrap_text(script['payoff']))
    srt_content.append("")
    
    # Write subtitle file
    with open(srt_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(srt_content))
    
    print(f"  ✓ Created subtitle file")
    
    # Improved subtitle styling
    subtitle_style = (
        "FontName=Impact,"              # Bold font
        "FontSize=70,"                  # Bigger text
        "PrimaryColour=&H00FFFFFF&,"    # White text
        "OutlineColour=&H00000000&,"    # Black outline
        "BackColour=&H80000000&,"       # Semi-transparent background
        "Outline=4,"                    # Thick outline for readability
        "Shadow=2,"                     # Drop shadow
        "Alignment=10,"                 # Center alignment
        "MarginV=200,"                  # Space from top/bottom
        "MarginL=80,"                   # Space from left edge
        "MarginR=80,"                   # Space from right edge
        "Bold=1"                        # Bold text
    )
    
    # FFmpeg command with improved styling
    cmd = [
        'ffmpeg',
        '-f', 'lavfi',
        '-i', 'color=c=black:s=1080x1920:d=30:r=30',  # Black background, 30 seconds
        '-vf', f"subtitles={srt_path}:force_style='{subtitle_style}'",
        '-c:v', 'libx264',
        '-preset', 'fast',
        '-pix_fmt', 'yuv420p',
        '-y',
        output_path
    ]
    
    try:
        print(f"  🎥 Rendering video...")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120
        )
        
        if result.returncode == 0:
            print(f"  ✅ Video created: {output_path}")
            # Clean up subtitle file
            os.remove(srt_path)
            return True
        else:
            print(f"  ❌ FFmpeg error:")
            print(result.stderr[-500:])  # Last 500 chars of error
            return False
            
    except subprocess.TimeoutExpired:
        print(f"  ❌ Timeout - took too long")
        return False
    except FileNotFoundError:
        print(f"  ❌ FFmpeg not found. Install it first:")
        print(f"     Windows: Download from ffmpeg.org")
        print(f"     Mac: brew install ffmpeg")
        print(f"     Linux: sudo apt-get install ffmpeg")
        return False
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False

def test_video_generator():
    """Test the video generator with a sample script"""
    
    print("\n" + "="*60)
    print("VIDEO GENERATOR TEST")
    print("="*60)
    
    # Test script
    test_script = {
        "topic": "Test Video",
        "hook": "This is a test hook to see if it works",
        "fact1": "First fact goes here in the video",
        "fact2": "Second fact appears after five seconds",
        "fact3": "Third fact builds up the curiosity",
        "fact4": "Fourth fact makes you want more",
        "payoff": "And here's the mind-blowing conclusion!"
    }
    
    # Create output directory
    os.makedirs('test_videos', exist_ok=True)
    output_path = 'test_videos/test_video.mp4'
    
    # Generate video
    success = create_video_simple(test_script, output_path)
    
    if success:
        print("\n✅ SUCCESS!")
        print(f"📁 Video saved to: {output_path}")
        print(f"📊 File size: {os.path.getsize(output_path) / 1024 / 1024:.1f} MB")
        print("\n👀 Open the video to check if it looks good!")
    else:
        print("\n❌ FAILED - Check errors above")

if __name__ == "__main__":
    test_video_generator()
