#!/usr/bin/env python3
"""
Viral Reels Generator - Full Application
Flask web app with user accounts, API key management, and video automation
"""

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_session import Session
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os
import json
import re
import tempfile
from datetime import datetime, timedelta
from functools import wraps
import anthropic
import requests
import subprocess
import secrets
import psycopg2
from psycopg2.extras import RealDictCursor
import urllib.parse
import time
import hmac
import hashlib
import base64
import threading
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

# ============================================================================
# APP CONFIGURATION
# ============================================================================

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, will use environment variables directly

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)  # Random secret key for sessions
app.config['UPLOAD_FOLDER'] = 'videos'

# ============================================================================
# DATABASE CONFIGURATION - Support both SQLite and PostgreSQL
# ============================================================================
DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL:
    # Railway PostgreSQL database
    app.config['DATABASE_TYPE'] = 'postgresql'
    app.config['DATABASE_URL'] = DATABASE_URL
    print("[OK] Using PostgreSQL database (Railway)")
else:
    # Local SQLite database
    app.config['DATABASE_TYPE'] = 'sqlite'
    app.config['DATABASE'] = 'viral_reels.db'
    print("[OK] Using SQLite database (local)")


# ============================================================================
# INITIALIZATION FOR RAILWAY/PRODUCTION
# ============================================================================
# Create necessary directories (runs when app imports)
directories = [
    'videos',
    os.path.join('videos', '1'),
    'temp_slides',
    'flask_session'
]

for directory in directories:
    try:
        os.makedirs(directory, exist_ok=True)
    except Exception as e:
        print(f"[WARNING] Could not create directory {directory}: {e}")

app.config['TEMPLATES_AUTO_RELOAD'] = True  # Disable template caching

# File-based sessions that persist across app reloads
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = 'flask_session'
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=365)

# Initialize Flask-Session
Session(app)

# Your admin email (gets lifetime free access)
ADMIN_EMAIL = "your-email@example.com"  # CHANGE THIS TO YOUR EMAIL

# ============================================================================
# SCHEDULER SETUP
# ============================================================================

scheduler = BackgroundScheduler()
scheduler_running = False

def start_scheduler():
    """Start the background scheduler if not already running"""
    global scheduler_running
    if not scheduler_running:
        scheduler.start()
        scheduler_running = True
        print("[OK] Scheduler started:")
        print("  - Scheduled posts: checks every 60 seconds")
        print("  - Video queue: processes every 3 hours")
        print("  - Script generation: processes every 30 seconds")

def post_scheduled_videos():
    """
    Background job that checks for and posts scheduled videos
    This runs automatically every 60 seconds
    """
    try:
        conn = get_db()

        # Find all scheduled posts that are due
        scheduled = conn.execute('''
            SELECT sp.*, v.file_path, s.hook, s.payoff, s.topic,
                   ak.facebook_page_token, ak.facebook_page_id, ak.auto_share_to_story,
                   u.email
            FROM scheduled_posts sp
            JOIN videos v ON sp.video_id = v.id
            JOIN scripts s ON v.script_id = s.id
            JOIN api_keys ak ON sp.user_id = ak.user_id
            JOIN users u ON sp.user_id = u.id
            WHERE sp.status = 'pending'
            AND sp.scheduled_time <= CURRENT_TIMESTAMP
            ORDER BY sp.scheduled_time ASC
        ''').fetchall()

        for post in scheduled:
            print(f"[SCHEDULER] Processing scheduled post #{post['id']}: {post['topic']}")

            try:
                # Check if video file exists
                if not os.path.exists(post['file_path']):
                    error_msg = "Video file not found"
                    conn.execute('''
                        UPDATE scheduled_posts
                        SET status = 'failed', error_message = ?, retry_count = retry_count + 1
                        WHERE id = ?
                    ''', (error_msg, post['id']))
                    print(f"  [ERROR] {error_msg}: {post['file_path']}")
                    continue

                # Check if Facebook credentials are available
                if not post['facebook_page_token'] or not post['facebook_page_id']:
                    error_msg = "Facebook credentials not configured"
                    conn.execute('''
                        UPDATE scheduled_posts
                        SET status = 'failed', error_message = ?, retry_count = retry_count + 1
                        WHERE id = ?
                    ''', (error_msg, post['id']))
                    print(f"  [ERROR] {error_msg}")
                    continue

                # Post video to Facebook
                facebook_video_id = post_video_to_facebook(
                    post['file_path'],
                    post['hook'],
                    post['payoff'],
                    post['facebook_page_token'],
                    post['facebook_page_id']
                )

                if facebook_video_id:
                    # Successfully posted
                    story_id = None

                    # Auto-share to Story if enabled
                    if post['auto_share_to_story']:
                        print(f"  [STORY] Sharing to Story...")
                        story_id = share_reel_to_story(
                            facebook_video_id,
                            post['facebook_page_token'],
                            post['facebook_page_id']
                        )
                        if story_id:
                            print(f"  [OK] Shared to Story: {story_id}")
                        else:
                            print(f"  [WARN] Story share failed")

                    # Update scheduled post as successful
                    conn.execute('''
                        UPDATE scheduled_posts
                        SET status = 'posted',
                            posted_at = CURRENT_TIMESTAMP,
                            facebook_video_id = ?,
                            story_id = ?
                        WHERE id = ?
                    ''', (facebook_video_id, story_id, post['id']))

                    print(f"  [OK] Posted successfully: {facebook_video_id}")

                    # Update video record
                    conn.execute('''
                        UPDATE videos
                        SET facebook_video_id = ?, posted_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    ''', (facebook_video_id, post['video_id']))

                else:
                    # Posting failed
                    error_msg = "Facebook upload failed"
                    conn.execute('''
                        UPDATE scheduled_posts
                        SET status = 'failed', error_message = ?, retry_count = retry_count + 1
                        WHERE id = ?
                    ''', (error_msg, post['id']))
                    print(f"  [ERROR] {error_msg}")

            except Exception as e:
                error_msg = str(e)
                conn.execute('''
                    UPDATE scheduled_posts
                    SET status = 'failed', error_message = ?, retry_count = retry_count + 1
                    WHERE id = ?
                ''', (error_msg, post['id']))
                print(f"  [ERROR] Exception: {error_msg}")

        conn.commit()
        conn.close()

    except Exception as e:
        print(f"[SCHEDULER ERROR] {str(e)}")
        import traceback
        traceback.print_exc()

def process_video_queue():
    """
    Background job that posts one video from the queue
    This runs automatically every 3 hours
    """
    try:
        print("\n[QUEUE] Processing video queue...")
        conn = get_db()

        # Get the first queued video
        queue_item = conn.execute('''
            SELECT q.*, v.file_path, s.hook, s.payoff, s.topic,
                   ak.facebook_page_token, ak.facebook_page_id, ak.auto_share_to_story,
                   u.email
            FROM video_queue q
            JOIN videos v ON q.video_id = v.id
            JOIN scripts s ON v.script_id = s.id
            JOIN api_keys ak ON q.user_id = ak.user_id
            JOIN users u ON q.user_id = u.id
            WHERE q.status = 'queued'
            ORDER BY q.queued_at ASC
            LIMIT 1
        ''').fetchone()

        if not queue_item:
            print("[QUEUE] No videos in queue")
            conn.close()
            return

        print(f"[QUEUE] Processing: {queue_item['topic']}")

        # Check if video file exists
        if not os.path.exists(queue_item['file_path']):
            error_msg = "Video file not found"
            conn.execute('''
                UPDATE video_queue
                SET status = 'failed', error_message = ?, retry_count = retry_count + 1
                WHERE id = ?
            ''', (error_msg, queue_item['id']))
            conn.commit()
            print(f"  [ERROR] {error_msg}: {queue_item['file_path']}")
            conn.close()
            return

        # Check if Facebook credentials are available
        if not queue_item['facebook_page_token'] or not queue_item['facebook_page_id']:
            error_msg = "Facebook credentials not configured"
            conn.execute('''
                UPDATE video_queue
                SET status = 'failed', error_message = ?, retry_count = retry_count + 1
                WHERE id = ?
            ''', (error_msg, queue_item['id']))
            conn.commit()
            print(f"  [ERROR] {error_msg}")
            conn.close()
            return

        # Post video to Facebook
        facebook_video_id = post_video_to_facebook(
            queue_item['file_path'],
            queue_item['hook'],
            queue_item['payoff'],
            queue_item['facebook_page_token'],
            queue_item['facebook_page_id']
        )

        if facebook_video_id:
            # Successfully posted
            story_id = None

            # Auto-share to Story if enabled
            if queue_item['auto_share_to_story']:
                print(f"  [STORY] Sharing to Story...")
                story_id = share_reel_to_story(
                    facebook_video_id,
                    queue_item['facebook_page_token'],
                    queue_item['facebook_page_id']
                )
                if story_id:
                    print(f"  [OK] Shared to Story: {story_id}")
                else:
                    print(f"  [WARN] Story share failed")

            # Update queue item as successful
            conn.execute('''
                UPDATE video_queue
                SET status = 'posted',
                    posted_at = CURRENT_TIMESTAMP,
                    facebook_video_id = ?,
                    story_id = ?
                WHERE id = ?
            ''', (facebook_video_id, story_id, queue_item['id']))

            print(f"  [OK] Posted successfully: {facebook_video_id}")

            # Update video record
            conn.execute('''
                UPDATE videos
                SET facebook_video_id = ?, posted_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (facebook_video_id, queue_item['video_id']))

            # Check how many items remain in queue
            remaining = conn.execute('''
                SELECT COUNT(*) as count FROM video_queue WHERE status = 'queued'
            ''').fetchone()['count']
            print(f"[QUEUE] {remaining} video(s) remaining in queue")

        else:
            # Posting failed
            error_msg = "Facebook upload failed"
            conn.execute('''
                UPDATE video_queue
                SET status = 'failed', error_message = ?, retry_count = retry_count + 1
                WHERE id = ?
            ''', (error_msg, queue_item['id']))
            print(f"  [ERROR] {error_msg}")

        conn.commit()
        conn.close()

    except Exception as e:
        print(f"[QUEUE ERROR] {str(e)}")
        import traceback
        traceback.print_exc()

def generate_hashtags(topic, hook, payoff):
    """Generate 5 relevant hashtags based on the content"""
    # Combine all text for analysis
    text = f"{topic} {hook} {payoff}".lower()

    # Common viral hashtags across categories
    common_hashtags = [
        '#fyp', '#foryou', '#viral', '#trending', '#explore',
        '#didyouknow', '#facts', '#mindblown', '#interesting',
        '#learnontiktok', '#educational', '#amazing', '#wow',
        '#reels', '#fbreels', '#facebookreels'
    ]

    # Topic-based hashtag mappings
    topic_keywords = {
        'science': ['#science', '#scientists', '#research', '#discovery', '#biology'],
        'animal': ['#animals', '#wildlife', '#nature', '#animalfacts', '#pets'],
        'space': ['#space', '#universe', '#astronomy', '#galaxy', '#nasa'],
        'ocean': ['#ocean', '#marine', '#sealife', '#underwater', '#fish'],
        'psychology': ['#psychology', '#mentalhealth', '#brain', '#mindset', '#therapy'],
        'food': ['#food', '#foodscience', '#cooking', '#chef', '#nutrition'],
        'nature': ['#nature', '#environment', '#earth', '#wild', '#outdoors'],
        'history': ['#history', '#historical', '#past', '#civilization', '#ancient'],
        'technology': ['#technology', '#tech', '#innovation', '#future', '#gadgets'],
        'health': ['#health', '#wellness', '#fitness', '#medical', '#body'],
        'human body': ['#humanbody', '#anatomy', '#health', '#biology', '#science'],
    }

    # Extract keywords from text
    words = re.findall(r'\b[a-z]{4,}\b', text)
    word_freq = {}
    for word in words:
        if word not in ['this', 'that', 'with', 'from', 'have', 'been', 'were', 'they']:
            word_freq[word] = word_freq.get(word, 0) + 1

    # Get top words from content
    top_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:5]
    content_hashtags = [f"#{word}" for word, _ in top_words]

    # Find matching topic category
    category_hashtags = []
    for category, tags in topic_keywords.items():
        if category in text:
            category_hashtags = tags[:3]
            break

    # Combine and select 5 hashtags
    all_hashtags = content_hashtags + category_hashtags + common_hashtags[:3]

    # Remove duplicates and return first 5
    seen = set()
    unique_hashtags = []
    for tag in all_hashtags:
        if tag not in seen:
            seen.add(tag)
            unique_hashtags.append(tag)
            if len(unique_hashtags) >= 5:
                break

    return ' '.join(unique_hashtags)

def post_video_to_facebook(video_path, hook, payoff, page_token, page_id):
    """Post video to Facebook Page"""
    url = f"https://graph.facebook.com/v18.0/{page_id}/videos"

    # Generate relevant hashtags (pass empty topic for now, will extract from hook/payoff)
    hashtags = generate_hashtags('', hook, payoff)
    caption = f"{hook} 🤯\n\n{payoff}\n\n{hashtags}"

    try:
        with open(video_path, 'rb') as video_file:
            files = {'source': video_file}
            data = {
                'access_token': page_token,
                'description': caption
            }

            response = requests.post(url, files=files, data=data, timeout=120)

            if response.status_code == 200:
                return response.json().get('id')
            else:
                # Safe encoding for error logging
                try:
                    error_text = response.text[:200].encode('ascii', 'ignore').decode('ascii')
                    print(f"    Facebook error: {response.status_code} - {error_text}")
                except:
                    print(f"    Facebook error: {response.status_code}")
                return None
    except Exception as e:
        # Safe encoding for error logging
        try:
            error_msg = str(e).encode('ascii', 'ignore').decode('ascii')
            print(f"    Upload error: {error_msg}")
        except:
            print(f"    Upload error")
        return None

def share_reel_to_story(facebook_video_id, page_token, page_id):
    """Share a posted Reel to Facebook Story"""
    try:
        # First, get the video ID from the Reel
        url = f"https://graph.facebook.com/v18.0/{facebook_video_id}"
        params = {
            'fields': 'id',
            'access_token': page_token
        }

        response = requests.get(url, params=params, timeout=30)

        if response.status_code == 200:
            # Share to Story using the Sharing API
            share_url = f"https://graph.facebook.com/v18.0/{page_id}/video_stories"
            data = {
                'source_video_id': facebook_video_id,
                'access_token': page_token
            }

            share_response = requests.post(share_url, data=data, timeout=30)

            if share_response.status_code == 200:
                return share_response.json().get('id')
            else:
                print(f"      Story share error: {share_response.status_code}")
                return None
        else:
            print(f"      Could not fetch Reel info: {response.status_code}")
            return None

    except Exception as e:
        print(f"      Story share exception: {e}")
        return None

# Add the scheduled job
scheduler.add_job(
    func=post_scheduled_videos,
    trigger=IntervalTrigger(minutes=1),
    id='check_scheduled_posts',
    name='Check and post scheduled videos',
    replace_existing=True
)

# Add the queue processing job (runs every 3 hours)
scheduler.add_job(
    func=process_video_queue,
    trigger=IntervalTrigger(hours=3),
    id='process_video_queue',
    name='Process video queue (post one video every 3 hours)',
    replace_existing=True
)

# ============================================================================
# ASYNC SCRIPT GENERATION (Background Jobs)
# ============================================================================

def process_script_generation_job(job_id):
    """
    Background job that processes a single script generation request
    Runs in APScheduler thread, safe from Railway HTTP timeouts
    """
    try:
        conn = get_db()

        # Get job details
        job = conn.execute('''
            SELECT j.*, u.email, ak.ai_provider, ak.glm_api_key,
                   ak.claude_api_key, ak.openrouter_api_key,
                   p.system_prompt, p.topics, p.num_scripts
            FROM script_generation_jobs j
            JOIN users u ON j.user_id = u.id
            JOIN api_keys ak ON j.user_id = ak.user_id
            LEFT JOIN prompts p ON j.prompt_id = p.id
            WHERE j.id = ?
        ''', (job_id,)).fetchone()

        if not job:
            print(f"[SCRIPT_JOB] Job #{job_id} not found")
            conn.close()
            return

        # Update status to processing
        conn.execute('''
            UPDATE script_generation_jobs
            SET status = 'processing', started_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (job_id,))
        conn.commit()

        print(f"[SCRIPT_JOB] Processing job #{job_id} for user {job['email']}")

        # Get recent content to avoid duplication
        recent_content = conn.execute('''
            SELECT DISTINCT s.topic, s.hook, v.created_at
            FROM videos v
            JOIN scripts s ON v.script_id = s.id
            WHERE v.user_id = ? AND v.status = 'completed'
            ORDER BY v.created_at DESC
            LIMIT 20
        ''', (job['user_id'],)).fetchall()

        # Build prompt
        if job['system_prompt']:
            prompt_text = job['system_prompt']
            num_scripts = job['num_scripts'] or 10
            topics = job['topics'] or "animals, space, ocean, psychology, human body, food science, nature"

            # Replace placeholders
            prompt_text = prompt_text.replace('{num_scripts}', str(num_scripts))
            prompt_text = prompt_text.replace('{topics}', topics)

            # Add recent content exclusion
            if recent_content:
                exclusion_text = "\n\n**IMPORTANT - Avoid these recent topics/hooks:**\n"
                exclusion_text += "The following topics and hooks have been used recently. DO NOT repeat them:\n\n"
                for i, row in enumerate(recent_content, 1):
                    exclusion_text += f"{i}. Topic: {row['topic']}\n   Hook: {row['hook']}\n"
                exclusion_text += "\nChoose completely DIFFERENT topics and angles.\n"
                prompt_text = prompt_text.replace('{topics}', topics) + exclusion_text
        else:
            # Fallback default prompt
            num_scripts = 15
            prompt_text = f"""Generate {num_scripts} viral Facebook Reels scripts in valid JSON format..."""

        # Call appropriate AI provider
        scripts = []
        ai_provider = job['ai_provider'] or 'manual'

        if ai_provider == 'glm' and job['glm_api_key']:
            scripts = generate_scripts_glm(job['glm_api_key'], prompt_text)
        elif ai_provider == 'claude' and job['claude_api_key']:
            scripts = generate_scripts_claude(job['claude_api_key'], prompt_text)
        elif ai_provider == 'openrouter' and job['openrouter_api_key']:
            scripts = generate_scripts_openrouter(job['openrouter_api_key'], prompt_text)

        # Save scripts to database
        if scripts:
            print(f"[INFO] Saving {len(scripts)} scripts to database...")
            saved_count = 0
            for i, script in enumerate(scripts):
                try:
                    # Validate before saving (defensive check)
                    required = ['topic', 'hook', 'fact1', 'fact2', 'fact3', 'fact4', 'payoff']
                    missing = [f for f in required if f not in script]

                    if missing:
                        print(f"[WARNING] Script {i+1} missing fields: {missing}. Skipping.")
                        continue

                    conn.execute('''
                        INSERT INTO scripts (user_id, topic, hook, fact1, fact2, fact3, fact4, payoff, viral_score)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (job['user_id'], script['topic'], script['hook'],
                          script['fact1'], script['fact2'], script['fact3'],
                          script['fact4'], script['payoff'], script.get('viral_score', 0.5)))
                    saved_count += 1
                except Exception as e:
                    print(f"[ERROR] Failed to save script {i+1}: {e}")
                    import traceback
                    traceback.print_exc()
                    continue

            print(f"[INFO] Successfully saved {saved_count}/{len(scripts)} scripts")

            # Update prompt usage stats
            if job['prompt_id']:
                conn.execute('''
                    UPDATE prompts
                    SET times_used = times_used + 1, last_used = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (job['prompt_id'],))

            # Mark job complete
            conn.execute('''
                UPDATE script_generation_jobs
                SET status = 'completed', num_scripts = ?, completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (len(scripts), job_id))

            print(f"[SCRIPT_JOB] Job #{job_id} completed: {len(scripts)} scripts generated")
        else:
            # No scripts generated - mark as failed
            conn.execute('''
                UPDATE script_generation_jobs
                SET status = 'failed', error_message = 'AI provider returned no scripts', completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (job_id,))
            print(f"[SCRIPT_JOB] Job #{job_id} failed: No scripts generated")

        conn.commit()
        conn.close()

    except Exception as e:
        print(f"[SCRIPT_JOB ERROR] Job #{job_id}: {str(e)}")
        import traceback
        traceback.print_exc()

        # Mark job as failed
        try:
            conn = get_db()
            conn.execute('''
                UPDATE script_generation_jobs
                SET status = 'failed', error_message = ?, completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (str(e)[:1000], job_id))  # Truncate error to fit in column
            conn.commit()
            conn.close()
        except:
            pass

def process_script_generation_queue():
    """
    Background job that checks for pending script generation jobs
    This runs automatically every 30 seconds via APScheduler
    """
    try:
        print("\n[SCRIPT_QUEUE] Checking for pending jobs...")
        conn = get_db()

        # Find all pending jobs (process up to 3 at a time to avoid overload)
        pending_jobs = conn.execute('''
            SELECT id FROM script_generation_jobs
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT 3
        ''').fetchall()

        if not pending_jobs:
            conn.close()
            return

        print(f"[SCRIPT_QUEUE] Found {len(pending_jobs)} pending job(s)")

        # Process each job in a separate thread
        import threading
        for job in pending_jobs:
            print(f"[SCRIPT_QUEUE] Starting job #{job['id']}")
            # Run in background thread to avoid blocking the scheduler
            threading.Thread(
                target=process_script_generation_job,
                args=(job['id'],),
                daemon=True
            ).start()

        conn.close()

    except Exception as e:
        print(f"[SCRIPT_QUEUE ERROR] {str(e)}")
        import traceback
        traceback.print_exc()

# Add script generation job processor to scheduler (runs every 30 seconds)
scheduler.add_job(
    func=process_script_generation_queue,
    trigger=IntervalTrigger(seconds=30),
    id='process_script_generation_queue',
    name='Process script generation queue',
    replace_existing=True
)

# ============================================================================
# DATABASE SETUP
# ============================================================================

def init_db():
    """Initialize database with tables"""
    is_postgres = app.config['DATABASE_TYPE'] == 'postgresql'

    if is_postgres:
        conn = psycopg2.connect(app.config['DATABASE_URL'])
        cursor = conn.cursor()
        # PostgreSQL syntax
        users_sql = '''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_admin BOOLEAN DEFAULT FALSE,
                is_premium BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                videos_generated INTEGER DEFAULT 0,
                videos_limit INTEGER DEFAULT 30
            )
        '''
        api_keys_sql = '''
            CREATE TABLE IF NOT EXISTS api_keys (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                ai_provider TEXT DEFAULT 'manual',
                claude_api_key TEXT,
                openrouter_api_key TEXT,
                glm_api_key TEXT,
                facebook_page_token TEXT,
                facebook_page_id TEXT,
                elevenlabs_api_key TEXT,
                auto_share_to_story BOOLEAN DEFAULT TRUE,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        '''
        scripts_sql = '''
            CREATE TABLE IF NOT EXISTS scripts (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                topic TEXT NOT NULL,
                hook TEXT NOT NULL,
                fact1 TEXT NOT NULL,
                fact2 TEXT NOT NULL,
                fact3 TEXT NOT NULL,
                fact4 TEXT NOT NULL,
                payoff TEXT NOT NULL,
                viral_score REAL,
                selected BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        '''
    else:
        conn = sqlite3.connect(app.config['DATABASE'])
        cursor = conn.cursor()
        # SQLite syntax
        users_sql = '''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_admin BOOLEAN DEFAULT 0,
                is_premium BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                videos_generated INTEGER DEFAULT 0,
                videos_limit INTEGER DEFAULT 30
            )
        '''
        api_keys_sql = '''
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                ai_provider TEXT DEFAULT 'manual',
                claude_api_key TEXT,
                openrouter_api_key TEXT,
                glm_api_key TEXT,
                facebook_page_token TEXT,
                facebook_page_id TEXT,
                elevenlabs_api_key TEXT,
                auto_share_to_story BOOLEAN DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        '''
        scripts_sql = '''
            CREATE TABLE IF NOT EXISTS scripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                topic TEXT NOT NULL,
                hook TEXT NOT NULL,
                fact1 TEXT NOT NULL,
                fact2 TEXT NOT NULL,
                fact3 TEXT NOT NULL,
                fact4 TEXT NOT NULL,
                payoff TEXT NOT NULL,
                viral_score REAL,
                selected BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        '''

    # Create tables
    cursor.execute(users_sql)
    cursor.execute(api_keys_sql)
    cursor.execute(scripts_sql)

    # Videos table
    if is_postgres:
        videos_sql = '''
            CREATE TABLE IF NOT EXISTS videos (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                script_id INTEGER NOT NULL,
                file_path TEXT,
                facebook_video_id TEXT,
                views INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                posted_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (script_id) REFERENCES scripts(id)
            )
        '''
    else:
        videos_sql = '''
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                script_id INTEGER NOT NULL,
                file_path TEXT,
                facebook_video_id TEXT,
                views INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                posted_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (script_id) REFERENCES scripts(id)
            )
        '''
    cursor.execute(videos_sql)

    # Prompts table
    if is_postgres:
        prompts_sql = '''
            CREATE TABLE IF NOT EXISTS prompts (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                system_prompt TEXT NOT NULL,
                topics TEXT,
                num_scripts INTEGER DEFAULT 10,
                is_active BOOLEAN DEFAULT FALSE,
                is_default BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMP,
                times_used INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        '''
    else:
        prompts_sql = '''
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
        '''
    cursor.execute(prompts_sql)

    # Scheduled posts table
    if is_postgres:
        scheduled_sql = '''
            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                video_id INTEGER NOT NULL,
                scheduled_time TIMESTAMP NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                posted_at TIMESTAMP,
                facebook_video_id TEXT,
                story_id TEXT,
                error_message TEXT,
                retry_count INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (video_id) REFERENCES videos(id)
            )
        '''
    else:
        scheduled_sql = '''
            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                video_id INTEGER NOT NULL,
                scheduled_time TIMESTAMP NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                posted_at TIMESTAMP,
                facebook_video_id TEXT,
                story_id TEXT,
                error_message TEXT,
                retry_count INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (video_id) REFERENCES videos(id)
            )
        '''
    cursor.execute(scheduled_sql)

    # Video queue table
    if is_postgres:
        queue_sql = '''
            CREATE TABLE IF NOT EXISTS video_queue (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                video_id INTEGER NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                queued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'queued',
                posted_at TIMESTAMP,
                facebook_video_id TEXT,
                story_id TEXT,
                error_message TEXT,
                retry_count INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (video_id) REFERENCES videos(id)
            )
        '''
    else:
        queue_sql = '''
            CREATE TABLE IF NOT EXISTS video_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                video_id INTEGER NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                queued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'queued',
                posted_at TIMESTAMP,
                facebook_video_id TEXT,
                story_id TEXT,
                error_message TEXT,
                retry_count INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (video_id) REFERENCES videos(id)
            )
        '''
    cursor.execute(queue_sql)

    # Script generation jobs table (for async AI script generation)
    if is_postgres:
        script_jobs_sql = '''
            CREATE TABLE IF NOT EXISTS script_generation_jobs (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                num_scripts INTEGER DEFAULT 0,
                prompt_id INTEGER,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (prompt_id) REFERENCES prompts(id)
            )
        '''
    else:
        script_jobs_sql = '''
            CREATE TABLE IF NOT EXISTS script_generation_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                num_scripts INTEGER DEFAULT 0,
                prompt_id INTEGER,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (prompt_id) REFERENCES prompts(id)
            )
        '''
    cursor.execute(script_jobs_sql)

    conn.commit()
    conn.close()
    print("[OK] Database initialized")

# ============================================================================
# INITIALIZATION FOR RAILWAY/PRODUCTION
# ============================================================================
# Initialize database on module load (after init_db function is defined)
if app.config['DATABASE_TYPE'] == 'sqlite':
    if not os.path.exists(app.config['DATABASE']):
        print("[OK] Database not found, initializing...")
        init_db()
        print("[OK] Database initialized successfully!")
    else:
        print("[OK] Database exists, ready to run")
else:
    # PostgreSQL - initialize tables (won't hurt if they exist)
    print("[OK] PostgreSQL detected, ensuring tables exist...")
    try:
        init_db()
        print("[OK] PostgreSQL tables ready")
    except Exception as e:
        print(f"[INFO] Tables may already exist: {e}")

# ============================================================================

class DatabaseConnection:
    """Wrapper class to handle both SQLite and PostgreSQL differences"""

    def __init__(self, conn):
        self.conn = conn
        self.is_postgres = app.config['DATABASE_TYPE'] == 'postgresql'

        if self.is_postgres:
            self.cursor = conn.cursor()
        else:
            self.cursor = conn.cursor()

    def execute(self, query, params=None):
        """Execute query with proper parameter substitution"""
        if params is None:
            params = ()

        # Convert ? to %s for PostgreSQL
        if self.is_postgres:
            query = query.replace('?', '%s')

        self.cursor.execute(query, params)
        return self.cursor

    def fetchone(self):
        """Fetch one row"""
        if self.is_postgres:
            row = self.cursor.fetchone()
            if row:
                # Convert RealDictRow to dict-like object
                return dict(row)
            return None
        else:
            return self.cursor.fetchone()

    def fetchall(self):
        """Fetch all rows"""
        if self.is_postgres:
            rows = self.cursor.fetchall()
            return [dict(row) for row in rows] if rows else []
        else:
            return self.cursor.fetchall()

    @property
    def lastrowid(self):
        """Get last inserted row ID"""
        if self.is_postgres:
            # For PostgreSQL, we need to return the ID from INSERT ... RETURNING
            # But for backward compat, we'll use cursor.lastrowid if available
            # Otherwise return None (caller should use RETURNING clause)
            return getattr(self.cursor, 'lastrowid', None)
        else:
            return self.cursor.lastrowid

    def commit(self):
        """Commit transaction"""
        self.conn.commit()

    def close(self):
        """Close connection"""
        if self.is_postgres:
            self.cursor.close()
        self.conn.close()

def get_db():
    """Get database connection wrapper (SQLite or PostgreSQL)"""
    if app.config['DATABASE_TYPE'] == 'postgresql':
        conn = psycopg2.connect(app.config['DATABASE_URL'], cursor_factory=RealDictCursor)
    else:
        conn = sqlite3.connect(app.config['DATABASE'])
        conn.row_factory = sqlite3.Row

    return DatabaseConnection(conn)

# ============================================================================
# AUTHENTICATION DECORATORS
# ============================================================================

def login_required(f):
    """Decorator to require login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def check_video_limit(f):
    """Decorator to check if user is within video limit"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        conn.close()
        
        if user['is_admin'] or user['is_premium']:
            # Admin and premium users have unlimited
            return f(*args, **kwargs)
        
        if user['videos_generated'] >= user['videos_limit']:
            flash(f'You have reached your monthly limit of {user["videos_limit"]} videos.', 'danger')
            return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function

# ============================================================================
# ROUTES - AUTHENTICATION
# ============================================================================

@app.route('/')
def index():
    """Landing page"""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')


@app.route('/privacy')
def privacy():
    """Privacy Policy page"""
    return render_template('privacy.html')


@app.route('/terms')
def terms():
    """Terms of Service page"""
    return render_template('terms.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    """User signup"""
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        
        # Check if email exists
        conn = get_db()
        existing = conn.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
        
        if existing:
            flash('Email already registered.', 'danger')
            return redirect(url_for('signup'))
        
        # Create user
        is_admin = (email == ADMIN_EMAIL)
        is_premium = is_admin  # Admin gets premium
        videos_limit = 999999 if is_admin else 30
        
        password_hash = generate_password_hash(password)
        
        # Create user
        if app.config['DATABASE_TYPE'] == 'postgresql':
            # PostgreSQL - use RETURNING to get the inserted ID
            cursor = conn.execute('''
                INSERT INTO users (email, password_hash, is_admin, is_premium, videos_limit)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            ''', (email, password_hash, is_admin, is_premium, videos_limit))
            result = cursor.fetchone()
            user_id = result['id'] if result else None
        else:
            # SQLite - use lastrowid
            cursor = conn.execute('''
                INSERT INTO users (email, password_hash, is_admin, is_premium, videos_limit)
                VALUES (?, ?, ?, ?, ?)
            ''', (email, password_hash, is_admin, is_premium, videos_limit))
            user_id = cursor.lastrowid

        # Create empty API keys entry
        conn.execute('INSERT INTO api_keys (user_id) VALUES (?)', (user_id,))
        
        conn.commit()
        conn.close()
        
        flash('Account created! Please log in.', 'success')
        return redirect(url_for('login'))
    
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login"""
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['email'] = user['email']
            session['is_admin'] = bool(user['is_admin'])
            session.permanent = True  # Make session permanent
            flash(f'Welcome back, {email}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password.', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """User logout"""
    session.clear()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('index'))

# ============================================================================
# ROUTES - MAIN APP
# ============================================================================

@app.route('/dashboard')
@login_required
def dashboard():
    """Main dashboard"""
    conn = get_db()
    
    # Get user info
    user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    
    # Get recent videos
    videos = conn.execute('''
        SELECT v.*, s.topic, s.hook
        FROM videos v
        JOIN scripts s ON v.script_id = s.id
        WHERE v.user_id = ?
        ORDER BY v.created_at DESC
        LIMIT 10
    ''', (session['user_id'],)).fetchall()
    
    # Get recent scripts (last 100 to avoid timezone issues)
    scripts = conn.execute('''
        SELECT * FROM scripts
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 100
    ''', (session['user_id'],)).fetchall()
    
    conn.close()
    
    return render_template('dashboard.html', 
                          user=user, 
                          videos=videos, 
                          scripts=scripts)

@app.route('/facebook/auth')
@login_required
def facebook_auth():
    """Start Facebook OAuth flow"""
    # Facebook App credentials - you need to create a Facebook app
    fb_app_id = os.environ.get('FACEBOOK_APP_ID', '2370511290077574')
    redirect_uri = url_for('facebook_callback', _external=True)

    # Required permissions for posting to Facebook Pages
    scope = 'pages_show_list,pages_read_engagement,pages_manage_posts,pages_manage_engagement,pages_read_user_content'

    auth_url = f"https://www.facebook.com/v18.0/dialog/oauth?client_id={fb_app_id}&redirect_uri={redirect_uri}&scope={scope}&response_type=code"

    return redirect(auth_url)


@app.route('/facebook/callback')
@login_required
def facebook_callback():
    """Handle Facebook OAuth callback and exchange for Page Access Token"""
    conn = get_db()

    try:
        # Get the authorization code from Facebook
        code = request.args.get('code')
        error = request.args.get('error')
        error_reason = request.args.get('error_reason')

        if error:
            flash(f'Facebook authorization failed: {error_reason or error}. Please try again.', 'danger')
            return redirect(url_for('settings'))

        if not code:
            flash('Authorization code missing. Please try again.', 'danger')
            return redirect(url_for('settings'))

        # Exchange code for user access token
        fb_app_id = os.environ.get('FACEBOOK_APP_ID', '2370511290077574')
        fb_app_secret = os.environ.get('FACEBOOK_APP_SECRET', '')
        redirect_uri = url_for('facebook_callback', _external=True)

        token_url = f"https://graph.facebook.com/v18.0/oauth/access_token"
        params = {
            'client_id': fb_app_id,
            'client_secret': fb_app_secret,
            'redirect_uri': redirect_uri,
            'code': code
        }

        response = requests.get(token_url, params=params, timeout=30)
        data = response.json()

        if 'access_token' not in data:
            flash('Failed to get access token from Facebook. Please try again.', 'danger')
            return redirect(url_for('settings'))

        user_access_token = data['access_token']

        # Get user's pages
        pages_url = "https://graph.facebook.com/v18.0/me/accounts"
        pages_params = {
            'access_token': user_access_token,
            'fields': 'id,name,access_token,category'
        }

        pages_response = requests.get(pages_url, params=pages_params, timeout=30)
        pages_data = pages_response.json()

        if 'data' not in pages_data or not pages_data['data']:
            flash('No Facebook Pages found. Please create a Facebook Page first.', 'warning')
            return redirect(url_for('settings'))

        # Get the first page (or you could let user choose)
        page = pages_data['data'][0]
        page_access_token = page.get('access_token')
        page_id = page.get('id')
        page_name = page.get('name')

        # Verify the page token has required permissions
        debug_url = "https://graph.facebook.com/v18.0/debug_token"
        debug_params = {
            'input_token': page_access_token,
            'access_token': page_access_token
        }

        debug_response = requests.get(debug_url, params=debug_params, timeout=30)
        debug_data = debug_response.json()

        # Check if token has required scopes
        scopes = debug_data.get('data', {}).get('scopes', [])
        required_scopes = ['pages_manage_posts']
        has_permission = any(scope in scopes for scope in required_scopes)

        if not has_permission:
            flash(f'Page access token missing required permissions. Current scopes: {", ".join(scopes)}', 'danger')
            return redirect(url_for('settings'))

        # Store the PAGE access token (not user token)
        # Calculate expiry (60 days from now for long-lived tokens)
        expires_at = int(time.time()) + (60 * 24 * 60 * 60)

        conn.execute('''
            UPDATE api_keys
            SET facebook_page_token = ?,
                facebook_page_id = ?,
                facebook_token_expires = ?,
                facebook_page_name = ?
            WHERE user_id = ?
        ''', (page_access_token, page_id, expires_at, page_name, session['user_id']))

        conn.commit()
        conn.close()

        flash(f'✅ Successfully connected to Facebook Page: "{page_name}"! Your access token is valid for 60 days.', 'success')
        return redirect(url_for('settings'))

    except Exception as e:
        conn.close()
        error_msg = str(e).encode('ascii', 'ignore').decode('ascii')
        print(f'[ERROR] Facebook OAuth failed: {error_msg}')
        flash(f'Facebook connection failed: {error_msg}', 'danger')
        return redirect(url_for('settings'))


@app.route('/facebook/refresh-token', methods=['POST'])
@login_required
def refresh_facebook_token():
    """Refresh Facebook Page Access Token (extends 60-day token)"""
    conn = get_db()

    try:
        api_keys = conn.execute('SELECT facebook_page_token, facebook_page_id FROM api_keys WHERE user_id = ?',
                                (session['user_id'],)).fetchone()

        if not api_keys or not api_keys['facebook_page_token']:
            return jsonify({'success': False, 'error': 'No Facebook token found'}), 400

        current_token = api_keys['facebook_page_token']
        page_id = api_keys['facebook_page_id']

        # Debug current token to check expiry
        debug_url = "https://graph.facebook.com/v18.0/debug_token"
        debug_params = {
            'input_token': current_token,
            'access_token': current_token
        }

        response = requests.get(debug_url, params=debug_params, timeout=30)
        debug_data = response.json()

        if not debug_data.get('data', {}).get('is_valid'):
            return jsonify({'success': False, 'error': 'Token has expired. Please re-connect with Facebook.'}), 400

        # Token is valid, calculate new expiry (60 days from now)
        expires_at = int(time.time()) + (60 * 24 * 60 * 60)

        conn.execute('UPDATE api_keys SET facebook_token_expires = ? WHERE user_id = ?',
                    (expires_at, session['user_id']))
        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'message': 'Token extended successfully',
            'expires_at': expires_at
        })

    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': 'Failed to refresh token'}), 500


@app.route('/facebook/check-token')
@login_required
def check_facebook_token():
    """Check if Facebook token is valid and show permissions"""
    conn = get_db()

    try:
        api_keys = conn.execute('SELECT facebook_page_token, facebook_page_id, facebook_token_expires, facebook_page_name FROM api_keys WHERE user_id = ?',
                                (session['user_id'],)).fetchone()

        if not api_keys or not api_keys['facebook_page_token']:
            return jsonify({'valid': False, 'error': 'No token found'})

        token = api_keys['facebook_page_token']
        page_id = api_keys['facebook_page_id']

        # Check token validity
        debug_url = "https://graph.facebook.com/v18.0/debug_token"
        debug_params = {
            'input_token': token,
            'access_token': token
        }

        response = requests.get(debug_url, params=debug_params, timeout=30)
        debug_data = response.json()

        token_data = debug_data.get('data', {})
        is_valid = token_data.get('is_valid', False)
        scopes = token_data.get('scopes', [])
        expires_at = api_keys['facebook_token_expires']

        # Calculate days until expiry
        days_left = 0
        if expires_at:
            seconds_left = expires_at - int(time.time())
            days_left = max(0, seconds_left // (24 * 60 * 60))

        return jsonify({
            'valid': is_valid,
            'page_name': api_keys['facebook_page_name'],
            'page_id': page_id,
            'scopes': scopes,
            'expires_at': expires_at,
            'days_left': days_left,
            'type': token_data.get('type', 'UNKNOWN')
        })

    except Exception as e:
        conn.close()
        return jsonify({'valid': False, 'error': str(e)}), 500


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    """User settings and API keys"""
    conn = get_db()
    
    if request.method == 'POST':
        # Update API keys
        ai_provider = request.form.get('ai_provider', 'manual')
        claude_key = request.form.get('claude_api_key', '').strip()
        openrouter_key = request.form.get('openrouter_api_key', '').strip()
        glm_key = request.form.get('glm_api_key', '').strip()
        fb_token = request.form.get('facebook_page_token', '').strip()
        fb_page_id = request.form.get('facebook_page_id', '').strip()
        elevenlabs_key = request.form.get('elevenlabs_api_key', '').strip()
        auto_share = True if request.form.get('auto_share_to_story') == 'on' else False

        conn.execute('''
            UPDATE api_keys
            SET ai_provider = ?,
                claude_api_key = ?,
                openrouter_api_key = ?,
                glm_api_key = ?,
                facebook_page_token = ?,
                facebook_page_id = ?,
                elevenlabs_api_key = ?,
                auto_share_to_story = ?
            WHERE user_id = ?
        ''', (ai_provider, claude_key, openrouter_key, glm_key, fb_token, fb_page_id, elevenlabs_key, auto_share, session['user_id']))
        
        conn.commit()
        flash('Settings saved successfully!', 'success')
    
    # Get current settings
    api_keys = conn.execute('SELECT * FROM api_keys WHERE user_id = ?', 
                            (session['user_id'],)).fetchone()
    user = conn.execute('SELECT * FROM users WHERE id = ?', 
                       (session['user_id'],)).fetchone()
    
    conn.close()
    
    return render_template('settings.html', api_keys=api_keys, user=user)

# ============================================================================
# ROUTES - VIDEO GENERATION
# ============================================================================

@app.route('/generate-scripts', methods=['POST'])
@login_required
def generate_scripts():
    """Generate scripts using configured AI provider"""

    conn = get_db()
    api_keys = conn.execute('SELECT * FROM api_keys WHERE user_id = ?',
                           (session['user_id'],)).fetchone()

    # Debug output (using stderr so it shows in logs)
    import sys as _sys
    _sys.stderr.write(f"[DEBUG] api_keys: {api_keys is not None}\n")
    if api_keys:
        _sys.stderr.write(f"[DEBUG] ai_provider: {api_keys['ai_provider']}\n")
        _sys.stderr.write(f"[DEBUG] glm_api_key set: {bool(api_keys['glm_api_key'])}\n")

    # Check which AI provider to use - default to manual if not set
    ai_provider = api_keys['ai_provider'] if api_keys and api_keys['ai_provider'] else 'manual'
    _sys.stderr.write(f"[DEBUG] Using ai_provider: {ai_provider}\n")

    if ai_provider == 'manual':
        # Manual mode - redirect to manual input page
        conn.close()
        return redirect(url_for('manual_scripts'))

    # Get recent published videos to avoid similar content
    recent_content = conn.execute('''
        SELECT DISTINCT s.topic, s.hook, v.created_at
        FROM videos v
        JOIN scripts s ON v.script_id = s.id
        WHERE v.user_id = ? AND v.status = 'completed'
        ORDER BY v.created_at DESC
        LIMIT 20
    ''', (session['user_id'],)).fetchall()

    # Build exclusion list from recent content
    recent_topics = [row['topic'] for row in recent_content]
    recent_hooks = [row['hook'] for row in recent_content]

    print(f"[INFO] Found {len(recent_content)} recent videos to avoid duplicating")

    # Get active prompt or default
    active_prompt = conn.execute('''
        SELECT * FROM prompts
        WHERE user_id = ? AND (is_active = True OR is_default = True)
        ORDER BY is_active DESC, is_default DESC
        LIMIT 1
    ''', (session['user_id'],)).fetchone()

    # Build prompt from template
    if active_prompt:
        prompt_text = active_prompt['system_prompt']
        num_scripts = active_prompt['num_scripts']
        topics = active_prompt['topics'] or "animals, space, ocean, psychology, human body, food science, nature"

        # Replace placeholders
        prompt_text = prompt_text.replace('{num_scripts}', str(num_scripts))
        prompt_text = prompt_text.replace('{topics}', topics)

        # Add recent content to avoid duplication
        if recent_content:
            exclusion_text = "\n\n**IMPORTANT - Avoid these recent topics/hooks:**\n"
            exclusion_text += "The following topics and hooks have been used recently. DO NOT repeat them or make very similar versions:\n\n"
            for i, row in enumerate(recent_content, 1):
                exclusion_text += f"{i}. Topic: {row['topic']}\n   Hook: {row['hook']}\n"
            exclusion_text += "\nChoose completely DIFFERENT topics and angles from the list above.\n"
            prompt_text = prompt_text.replace('{topics}', topics) + exclusion_text
    else:
        # Fallback to default prompt - intelligent but relatable to Gen Z
        num_scripts = 15
        topics = "animals, space facts, ocean life, psychology, human body, food science, nature"
        prompt_text = f"""Generate {num_scripts} viral Facebook Reels scripts in valid JSON format.

**WRITING STYLE:**
Write like a knowledgeable, intelligent person explaining something fascinating to a Gen Z audience. Think: smart science communicator or educator who's genuinely excited about sharing knowledge.

Style guidelines:
- Clear, direct language that grabs attention immediately
- Conversational but intelligent tone - like a smart friend sharing mind-blowing facts
- Emotional words: "mind-blowing", "unbelievable", "insane", "wild", "unreal"
- Build curiosity and wonder
- Keep facts punchy and memorable
- Use natural modern phrasing without being overly slangy
- Each line should feel like a revelation

Each script needs:
- topic: The subject
- hook: The opening hook (target 10 words, max 18 for clarity) - Something that makes you stop scrolling
- fact1-4: Four fascinating facts building on each other (target 10 words, max 18 for clarity)
- payoff: The mind-blowing conclusion with emoji (target 10 words, max 18 for clarity)
- viral_score: 0-1 rating of how shareable this is

Topics: {topics}

Return ONLY this JSON structure:
[
  {{
    "topic": "Topic Name",
    "hook": "Your brain actually shrinks when you're sleep deprived",
    "fact1": "Brain volume decreases by 1-2% after just one sleepless night",
    "fact2": "Your cognitive abilities drop equivalent to being legally drunk",
    "fact3": "Even six hours of sleep for a week causes similar effects",
    "fact4": "The damage is reversible but takes consistent good sleep to fix",
    "payoff": "Your eight hours aren't optional, they're essential maintenance 🧠",
    "viral_score": 0.92
  }}
]

Topics should be: animals, space facts, ocean life, psychology, human body, food science, nature

IMPORTANT: Return ONLY the JSON array. No explanations, no markdown formatting, no code blocks."""

        # Add recent content to avoid duplication
        if recent_content:
            prompt_text += "\n\n**IMPORTANT - Avoid these recent topics/hooks:**\n"
            prompt_text += "The following topics and hooks have been used recently. DO NOT repeat them or make very similar versions:\n\n"
            for i, row in enumerate(recent_content, 1):
                prompt_text += f"{i}. Topic: {row['topic']}\n   Hook: {row['hook']}\n"
            prompt_text += "\nChoose completely DIFFERENT topics and angles from the list above.\n"

    # Validate API key exists before creating job
    if ai_provider == 'claude':
        if not api_keys or not api_keys['claude_api_key']:
            flash('Please add your Claude API key in Settings first.', 'warning')
            conn.close()
            return redirect(url_for('settings'))
    elif ai_provider == 'openrouter':
        if not api_keys or not api_keys['openrouter_api_key']:
            flash('Please add your OpenRouter API key in Settings first.', 'warning')
            conn.close()
            return redirect(url_for('settings'))
    elif ai_provider == 'glm':
        if not api_keys or not api_keys['glm_api_key']:
            flash('Please add your GLM API key in Settings first.', 'warning')
            conn.close()
            return redirect(url_for('settings'))
    else:
        flash('Please select an AI provider in Settings.', 'warning')
        conn.close()
        return redirect(url_for('settings'))

    # Create async job and return immediately (avoids Railway timeout)
    if app.config['DATABASE_TYPE'] == 'postgresql':
        cursor = conn.execute('''
            INSERT INTO script_generation_jobs (user_id, prompt_id, status)
            VALUES (%s, %s, 'pending')
            RETURNING id
        ''', (session['user_id'], active_prompt['id'] if active_prompt else None))
        result = cursor.fetchone()
        job_id = result['id']
    else:
        cursor = conn.execute('''
            INSERT INTO script_generation_jobs (user_id, prompt_id, status)
            VALUES (?, ?, 'pending')
        ''', (session['user_id'], active_prompt['id'] if active_prompt else None))
        job_id = cursor.lastrowid

    conn.commit()
    conn.close()

    print(f"[INFO] Created script generation job #{job_id} for user {session['user_id']} (provider: {ai_provider})")

    # Redirect to status page immediately (<1 second, well under Railway's 30s timeout)
    return redirect(url_for('script_generation_status', job_id=job_id))

@app.route('/script-generation-status/<int:job_id>')
@login_required
def script_generation_status(job_id):
    """Status page for script generation jobs"""
    conn = get_db()
    job = conn.execute('''
        SELECT * FROM script_generation_jobs
        WHERE id = ? AND user_id = ?
    ''', (job_id, session['user_id'])).fetchone()
    conn.close()

    if not job:
        flash('Job not found.', 'danger')
        return redirect(url_for('dashboard'))

    return render_template('script_generation_status.html', job=job)

@app.route('/api/check-generation-status/<int:job_id>')
@login_required
def check_generation_status(job_id):
    """API endpoint for polling job status"""
    conn = get_db()
    job = conn.execute('''
        SELECT * FROM script_generation_jobs
        WHERE id = ? AND user_id = ?
    ''', (job_id, session['user_id'])).fetchone()
    conn.close()

    if not job:
        return jsonify({'error': 'Job not found'}), 404

    return jsonify({
        'id': job['id'],
        'status': job['status'],
        'num_scripts': job['num_scripts'],
        'error_message': job['error_message'],
        'created_at': job['created_at'].isoformat() if job['created_at'] else None,
        'started_at': job['started_at'].isoformat() if job['started_at'] else None,
        'completed_at': job['completed_at'].isoformat() if job['completed_at'] else None
    })

def generate_scripts_claude(api_key, prompt_text):
    """Generate scripts using Claude API"""
    try:
        client = anthropic.Anthropic(api_key=api_key)
        
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt_text}]
        )

        response_text = message.content[0].text
        return extract_json_safely(response_text)

    except Exception as e:
        print(f"Claude error: {e}")
        return []

def generate_scripts_openrouter(api_key, prompt_text):
    """Generate scripts using OpenRouter (access to free models)"""
    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "google/gemini-2.0-flash-001:free",  # FREE model
                "messages": [
                    {"role": "user", "content": prompt_text}
                ]
            }
        )

        if response.status_code == 200:
            result = response.json()
            response_text = result['choices'][0]['message']['content']
            return extract_json_safely(response_text)

        return []
    except Exception as e:
        print(f"OpenRouter error: {e}")
        return []

def generate_glm_token(api_key):
    """
    Generate JWT token for Zhipu AI GLM API
    API key format: id.secret
    """
    try:
        if '.' not in api_key:
            print("[ERROR] Invalid GLM API key format (should be id.secret)")
            return None

        api_id, api_secret = api_key.split('.')

        # Create JWT header
        header = {
            "alg": "HS256",
            "sign_type": "SIGN"
        }

        # Create JWT payload
        timestamp = int(time.time())
        payload = {
            "api_key": api_id,
            "exp": timestamp + 3600,  # 1 hour expiration
            "timestamp": timestamp
        }

        # Encode header and payload
        header_encoded = base64.urlsafe_b64encode(
            json.dumps(header, separators=(',', ':')).encode()
        ).rstrip(b'=').decode()

        payload_encoded = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(',', ':')).encode()
        ).rstrip(b'=').decode()

        # Create signature
        message = f"{header_encoded}.{payload_encoded}"
        signature = hmac.new(
            api_secret.encode(),
            message.encode(),
            hashlib.sha256
        ).digest()

        signature_encoded = base64.urlsafe_b64encode(signature).rstrip(b'=').decode()

        # Return full JWT token
        return f"{message}.{signature_encoded}"

    except Exception as e:
        print(f"[ERROR] Token generation failed: {e}")
        return None

def validate_script_fields(script):
    """
    Validate that a script object has all required fields.
    Returns the script with defaults for missing optional fields.
    Returns None if required fields are missing.
    """
    required_fields = ['topic', 'hook', 'fact1', 'fact2', 'fact3', 'fact4', 'payoff']

    # Check all required fields exist
    for field in required_fields:
        if field not in script:
            print(f"[WARNING] Script missing required field: {field}")
            return None

    # Add default for viral_score if missing
    if 'viral_score' not in script:
        script['viral_score'] = 0.5

    return script

def extract_json_safely(response_text):
    """
    Extract JSON array from API response with multiple fallback strategies.
    Handles GLM API's malformed responses with unescaped quotes.
    Validates all returned scripts have required fields.
    """
    import re
    import json

    # Strategy 1: Try direct JSON parse (clean response)
    try:
        scripts = json.loads(response_text)
        if isinstance(scripts, list):
            validated = [s for s in (validate_script_fields(s) for s in scripts) if s is not None]
            if validated:
                print(f"[INFO] Strategy 1 extracted {len(validated)} valid scripts")
                return validated
    except json.JSONDecodeError:
        pass

    # Strategy 2: Extract using bracket markers (original method)
    start = response_text.find('[')
    end = response_text.rfind(']') + 1
    if start != -1 and end > start:
        try:
            scripts = json.loads(response_text[start:end])
            if isinstance(scripts, list):
                validated = [s for s in (validate_script_fields(s) for s in scripts) if s is not None]
                if validated:
                    print(f"[INFO] Strategy 2 extracted {len(validated)} valid scripts")
                    return validated
        except json.JSONDecodeError:
            pass

    # Strategy 3: Use regex to find JSON array
    json_match = re.search(r'\[\s*\{.*?\}\s*\]', response_text, re.DOTALL)
    if json_match:
        try:
            scripts = json.loads(json_match.group())
            if isinstance(scripts, list):
                validated = [s for s in (validate_script_fields(s) for s in scripts) if s is not None]
                if validated:
                    print(f"[INFO] Strategy 3 extracted {len(validated)} valid scripts")
                    return validated
        except json.JSONDecodeError:
            pass

    # Strategy 4: Try to fix common JSON issues (unescaped quotes)
    try:
        # Find JSON boundaries
        start = response_text.find('[')
        end = response_text.rfind(']') + 1

        if start != -1 and end > start:
            json_str = response_text[start:end]

            # Fix common unescaped quote issues in string values
            # This pattern fixes quotes that should be escaped in JSON strings
            # by looking for patterns like "field": "value with "quote" in it"
            fixed_json = re.sub(
                r':\s*\"([^\"]*?)\"(?=\s*[,}])',
                lambda m: ': "' + m.group(1).replace('"', '\\"') + '"',
                json_str
            )

            scripts = json.loads(fixed_json)
            if isinstance(scripts, list):
                validated = [s for s in (validate_script_fields(s) for s in scripts) if s is not None]
                if validated:
                    print(f"[INFO] Strategy 4 extracted {len(validated)} valid scripts")
                    return validated
    except Exception:
        pass

    # Strategy 5: Try to find and parse individual JSON objects
    try:
        # Find all {...} blocks that might be script objects
        objects = re.findall(r'\{[^{}]*"topic"[^{}]*\}', response_text, re.DOTALL)
        if objects:
            scripts = []
            required_fields = ['topic', 'hook', 'fact1', 'fact2', 'fact3', 'fact4', 'payoff']
            for obj_str in objects:
                try:
                    obj = json.loads(obj_str)
                    # Validate ALL required fields exist
                    if all(field in obj for field in required_fields):
                        # Ensure viral_score has a default
                        if 'viral_score' not in obj:
                            obj['viral_score'] = 0.5
                        scripts.append(obj)
                except json.JSONDecodeError:
                    continue
            if scripts:
                print(f"[INFO] Strategy 5 extracted {len(scripts)} valid script objects")
                return scripts
    except Exception:
        pass

    # All strategies failed
    print("[WARNING] Could not extract valid JSON from response")
    return []

def safe_print(text):
    """Safely print text that might contain non-ASCII characters"""
    try:
        print(text)
    except (UnicodeEncodeError, TypeError):
        # Write to debug file instead
        try:
            with open('debug.log', 'a', encoding='utf-8') as f:
                f.write(str(text) + '\n')
            print('[DEBUG: See debug.log for details]')
        except:
            print('[DEBUG: Could not output]')

def generate_scripts_glm(api_key, prompt_text):
    """Generate scripts using GLM-4.7 (Zhipu AI) - ORIGINAL WORKING VERSION"""
    try:
        print("[DEBUG] GLM API call starting...")

        # Use the original coding endpoint that was working
        url = "https://api.z.ai/api/coding/paas/v4/chat/completions"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        # Use GLM-4.7 model (what was working before)
        json_data = {
            "model": "GLM-4.7",
            "messages": [
                {"role": "user", "content": prompt_text}
            ]
        }

        print(f"[DEBUG] Requesting model: {json_data['model']}")
        print(f"[DEBUG] Using endpoint: {url}")

        # Increased timeout to 5 minutes for 15 scripts generation
        response = requests.post(url, headers=headers, json=json_data, timeout=300)

        print(f"[DEBUG] Response status: {response.status_code}")

        # Write full response to debug file
        with open('debug.log', 'w', encoding='utf-8') as f:
            f.write(f"URL: {url}\n")
            f.write(f"Model: {json_data['model']}\n")
            f.write(f"Status: {response.status_code}\n")
            f.write(f"Headers: {response.headers}\n")
            f.write(f"Response: {response.text}\n")

        if response.status_code == 200:
            result = response.json()
            response_text = result['choices'][0]['message']['content']

            print(f"[DEBUG] Response length: {len(response_text)} chars")

            # Extract JSON using robust multi-strategy parser
            return extract_json_safely(response_text)
        else:
            print(f"[ERROR] GLM API error {response.status_code} - See debug.log")

        return []
    except requests.exceptions.Timeout:
        print("[ERROR] GLM API timeout after 300 seconds")
        return []
    except Exception as e:
        print(f"[ERROR] GLM error: {str(e)}")
        import traceback
        traceback.print_exc()
        return []

@app.route('/manual-scripts', methods=['GET', 'POST'])
@login_required
def manual_scripts():
    """Manually paste scripts from Grok/Claude"""
    
    if request.method == 'POST':
        scripts_text = request.form.get('scripts_json', '').strip()
        
        try:
            # Try to parse JSON
            scripts = json.loads(scripts_text)
            
            if not isinstance(scripts, list):
                flash('Invalid format. Please paste a JSON array.', 'danger')
                return redirect(url_for('manual_scripts'))
            
            # Save to database
            conn = get_db()
            for script in scripts:
                conn.execute('''
                    INSERT INTO scripts (user_id, topic, hook, fact1, fact2, fact3, fact4, payoff, viral_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (session['user_id'], 
                      script.get('topic', 'Unknown'), 
                      script['hook'], 
                      script['fact1'], 
                      script['fact2'], 
                      script['fact3'], 
                      script['fact4'], 
                      script['payoff'], 
                      script.get('viral_score', 0.5)))
            
            conn.commit()
            conn.close()
            
            flash(f'Added {len(scripts)} scripts successfully!', 'success')
            return redirect(url_for('dashboard'))
            
        except json.JSONDecodeError:
            flash('Invalid JSON format. Please check your paste.', 'danger')
        except KeyError as e:
            flash(f'Missing required field: {e}', 'danger')
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')
    
    return render_template('manual_scripts.html')

@app.route('/prompts')
@login_required
def prompts():
    """Manage custom prompts"""
    conn = get_db()
    
    # Get user's prompts
    user_prompts = conn.execute('''
        SELECT * FROM prompts 
        WHERE user_id = ?
        ORDER BY is_default DESC, is_active DESC, last_used DESC
    ''', (session['user_id'],)).fetchall()
    
    conn.close()
    
    return render_template('prompts.html', prompts=user_prompts)

@app.route('/prompts/create', methods=['GET', 'POST'])
@login_required
def create_prompt():
    """Create a new custom prompt"""
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        system_prompt = request.form.get('system_prompt', '').strip()
        topics = request.form.get('topics', '').strip()
        num_scripts = int(request.form.get('num_scripts', 10))
        is_default = True if request.form.get('is_default') == 'on' else False
        
        if not name or not system_prompt:
            flash('Name and prompt text are required.', 'danger')
            return redirect(url_for('create_prompt'))
        
        conn = get_db()
        
        # If setting as default, unset other defaults
        if is_default:
            conn.execute('''
                UPDATE prompts SET is_default = False, is_active = False
                WHERE user_id = ?
            ''', (session['user_id'],))
        
        # Create prompt
        conn.execute('''
            INSERT INTO prompts (user_id, name, description, system_prompt, topics, num_scripts, is_active, is_default)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (session['user_id'], name, description, system_prompt, topics, num_scripts, is_default, is_default))
        
        conn.commit()
        conn.close()
        
        flash(f'Prompt "{name}" created successfully!', 'success')
        return redirect(url_for('prompts'))
    
    # Show default template for new prompts - intelligent but relatable
    default_prompt = """Generate {num_scripts} viral Facebook Reels scripts in valid JSON format.

**WRITING STYLE:**
Write like a knowledgeable, intelligent person explaining something fascinating to a Gen Z audience. Think: smart science communicator or educator who's genuinely excited about sharing knowledge.

Style guidelines:
- Clear, direct language that grabs attention immediately
- Conversational but intelligent tone - like a smart friend sharing mind-blowing facts
- Emotional words: "mind-blowing", "unbelievable", "insane", "wild", "unreal"
- Build curiosity and wonder
- Keep facts punchy and memorable
- Use natural modern phrasing without being overly slangy
- Each line should feel like a revelation

Each script needs:
- topic: The subject
- hook: The opening hook (target 10 words, max 18 for clarity) - Something that makes you stop scrolling
- fact1-4: Four fascinating facts building on each other (target 10 words, max 18 for clarity)
- payoff: The mind-blowing conclusion with emoji (target 10 words, max 18 for clarity)
- viral_score: 0-1 rating of how shareable this is

Topics: {topics}

Return ONLY this JSON structure:
[
  {{
    "topic": "Topic Name",
    "hook": "Your brain actually shrinks when you're sleep deprived",
    "fact1": "Brain volume decreases by 1-2% after just one sleepless night",
    "fact2": "Your cognitive abilities drop equivalent to being legally drunk",
    "fact3": "Even six hours of sleep for a week causes similar effects",
    "fact4": "The damage is reversible but takes consistent good sleep to fix",
    "payoff": "Your eight hours aren't optional, they're essential maintenance 🧠",
    "viral_score": 0.92
  }}
]

Topics should be: animals, space facts, ocean life, psychology, human body, food science, nature

IMPORTANT: Return ONLY the JSON array. No explanations, no markdown formatting, no code blocks."""
    
    return render_template('create_prompt.html', default_prompt=default_prompt)

@app.route('/prompts/<int:prompt_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_prompt(prompt_id):
    """Edit an existing prompt"""
    
    conn = get_db()
    prompt = conn.execute('''
        SELECT * FROM prompts WHERE id = ? AND user_id = ?
    ''', (prompt_id, session['user_id'])).fetchone()
    
    if not prompt:
        flash('Prompt not found.', 'danger')
        conn.close()
        return redirect(url_for('prompts'))
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        system_prompt = request.form.get('system_prompt', '').strip()
        topics = request.form.get('topics', '').strip()
        num_scripts = int(request.form.get('num_scripts', 10))
        is_default = True if request.form.get('is_default') == 'on' else False
        
        # If setting as default, unset other defaults
        if is_default:
            conn.execute('''
                UPDATE prompts SET is_default = False, is_active = False
                WHERE user_id = ? AND id != ?
            ''', (session['user_id'], prompt_id))
        
        conn.execute('''
            UPDATE prompts 
            SET name = ?, description = ?, system_prompt = ?, topics = ?, 
                num_scripts = ?, is_default = ?, is_active = ?
            WHERE id = ? AND user_id = ?
        ''', (name, description, system_prompt, topics, num_scripts, is_default, is_default, prompt_id, session['user_id']))
        
        conn.commit()
        conn.close()
        
        flash(f'Prompt "{name}" updated successfully!', 'success')
        return redirect(url_for('prompts'))
    
    conn.close()
    return render_template('edit_prompt.html', prompt=prompt)

@app.route('/prompts/<int:prompt_id>/activate', methods=['POST'])
@login_required
def activate_prompt(prompt_id):
    """Set a prompt as active (used for next generation)"""
    
    conn = get_db()
    
    # Verify ownership
    prompt = conn.execute('''
        SELECT * FROM prompts WHERE id = ? AND user_id = ?
    ''', (prompt_id, session['user_id'])).fetchone()
    
    if not prompt:
        flash('Prompt not found.', 'danger')
        conn.close()
        return redirect(url_for('prompts'))
    
    # Deactivate all other prompts
    conn.execute('UPDATE prompts SET is_active = False WHERE user_id = ?', (session['user_id'],))

    # Activate this one
    conn.execute('UPDATE prompts SET is_active = True WHERE id = ?', (prompt_id,))
    
    conn.commit()
    conn.close()
    
    flash(f'Prompt "{prompt["name"]}" is now active!', 'success')
    return redirect(url_for('prompts'))

@app.route('/prompts/<int:prompt_id>/delete', methods=['POST'])
@login_required
def delete_prompt(prompt_id):
    """Delete a prompt"""
    
    conn = get_db()
    
    # Verify ownership
    prompt = conn.execute('''
        SELECT * FROM prompts WHERE id = ? AND user_id = ?
    ''', (prompt_id, session['user_id'])).fetchone()
    
    if not prompt:
        flash('Prompt not found.', 'danger')
        conn.close()
        return redirect(url_for('prompts'))
    
    # Delete
    conn.execute('DELETE FROM prompts WHERE id = ?', (prompt_id,))
    conn.commit()
    conn.close()
    
    flash(f'Prompt "{prompt["name"]}" deleted.', 'info')
    return redirect(url_for('prompts'))

@app.route('/prompts/<int:prompt_id>/duplicate', methods=['POST'])
@login_required
def duplicate_prompt(prompt_id):
    """Duplicate an existing prompt"""
    
    conn = get_db()
    
    prompt = conn.execute('''
        SELECT * FROM prompts WHERE id = ? AND user_id = ?
    ''', (prompt_id, session['user_id'])).fetchone()
    
    if not prompt:
        flash('Prompt not found.', 'danger')
        conn.close()
        return redirect(url_for('prompts'))
    
    # Create duplicate
    conn.execute('''
        INSERT INTO prompts (user_id, name, description, system_prompt, topics, num_scripts, is_active, is_default)
        VALUES (?, ?, ?, ?, ?, ?, False, False)
    ''', (session['user_id'],
          f"{prompt['name']} (Copy)",
          prompt['description'],
          prompt['system_prompt'],
          prompt['topics'],
          prompt['num_scripts']))
    
    conn.commit()
    conn.close()
    
    flash(f'Prompt duplicated!', 'success')
    return redirect(url_for('prompts'))

@app.route('/select-scripts', methods=['POST'])
@login_required
@check_video_limit
def select_scripts():
    """Mark selected scripts for video generation"""
    
    script_ids = request.form.getlist('script_ids')

    if not script_ids:
        flash('Please select at least 1 script.', 'warning')
        return redirect(url_for('dashboard'))

    conn = get_db()
    
    # Mark scripts as selected
    for script_id in script_ids:
        conn.execute('UPDATE scripts SET selected = True WHERE id = ? AND user_id = ?',
                    (script_id, session['user_id']))
    
    conn.commit()
    conn.close()
    
    flash(f'Selected {len(script_ids)} scripts. Ready to generate videos!', 'success')
    return redirect(url_for('create_videos'))

@app.route('/clear-scripts', methods=['POST'])
@login_required
def clear_scripts():
    """Clear all generated scripts for the current user"""

    conn = get_db()

    # Delete all scripts for this user
    result = conn.execute('DELETE FROM scripts WHERE user_id = ?', (session['user_id'],))
    deleted_count = result.rowcount

    conn.commit()
    conn.close()

    flash(f'Cleared {deleted_count} scripts.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/create-videos')
@login_required
@check_video_limit
def create_videos():
    """Show selected scripts and generate videos"""
    
    conn = get_db()
    
    # Get selected scripts
    scripts = conn.execute('''
        SELECT * FROM scripts
        WHERE user_id = ? AND selected = True
        ORDER BY viral_score DESC
    ''', (session['user_id'],)).fetchall()
    
    conn.close()
    
    if not scripts:
        flash('No scripts selected. Please select scripts first.', 'warning')
        return redirect(url_for('dashboard'))
    
    return render_template('create_videos.html', scripts=scripts)

@app.route('/generate-video/<int:script_id>', methods=['POST'])
@login_required
@check_video_limit
def generate_video(script_id):
    """Generate a single video using FFmpeg"""
    
    conn = get_db()
    
    # Get script
    script = conn.execute('SELECT * FROM scripts WHERE id = ? AND user_id = ?',
                         (script_id, session['user_id'])).fetchone()

    if not script:
        return jsonify({'error': 'Script not found'}), 404

    # Convert sqlite3.Row to dict for easier access
    script = dict(script)
    
    # Get API keys
    api_keys = conn.execute('SELECT * FROM api_keys WHERE user_id = ?',
                           (session['user_id'],)).fetchone()

    # Convert api_keys to dict if it exists, otherwise use None
    api_keys = dict(api_keys) if api_keys else None
    
    # Create video directory
    user_dir = os.path.join(app.config['UPLOAD_FOLDER'], str(session['user_id']))
    os.makedirs(user_dir, exist_ok=True)
    
    video_filename = f"video_{script_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
    video_path = os.path.join(user_dir, video_filename)
    
    try:
        # Log to file for debugging
        with open('video_generation.log', 'a', encoding='utf-8') as log:
            log.write(f"\n{'='*60}\n")
            log.write(f"[ROUTE] /generate-video/{script_id} called at {datetime.now()}\n")
            log.write(f"  Script: {script}\n")
            log.write(f"  Video path: {video_path}\n")
            log.write(f"  API keys: {api_keys}\n")
            log.write(f"  About to call create_video_ffmpeg...\n")
            log.write(f"{'='*60}\n")

        # Generate video with FFmpeg
        success = create_video_ffmpeg(script, video_path, api_keys)

        if success:
            # Save video record
            cursor = conn.execute('''
                INSERT INTO videos (user_id, script_id, file_path, status)
                VALUES (?, ?, ?, 'completed')
            ''', (session['user_id'], script_id, video_path))

            video_record_id = cursor.lastrowid

            # Post to Facebook if credentials available
            facebook_video_id = None
            if api_keys and api_keys['facebook_page_token'] and api_keys['facebook_page_id']:
                # Note: post_to_facebook needs to be called with different signature
                # We'll update it to accept api_keys dict
                facebook_video_id = post_to_facebook_with_keys(video_path, script, api_keys)

                if facebook_video_id:
                    # Update video record with Facebook video ID
                    conn.execute('''
                        UPDATE videos SET facebook_video_id = ?, posted_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    ''', (facebook_video_id, video_record_id))

                    # Auto-share to Story if enabled
                    if api_keys['auto_share_to_story']:
                        share_reel_to_story(facebook_video_id, api_keys)

            # Update user's video count
            conn.execute('''
                UPDATE users SET videos_generated = videos_generated + 1
                WHERE id = ?
            ''', (session['user_id'],))

            # Unselect script
            conn.execute('UPDATE scripts SET selected = False WHERE id = ?', (script_id,))

            conn.commit()

            return jsonify({
                'success': True,
                'message': 'Video created and posted successfully!',
                'video_path': video_path,
                'facebook_video_id': facebook_video_id
            })
        else:
            return jsonify({'error': 'Video generation failed - check console logs for details'}), 500

    except Exception as e:
        # Log the full traceback for debugging
        import traceback
        error_details = f"{str(e)}\n{traceback.format_exc()}"

        # Write to log file
        with open('video_generation.log', 'a', encoding='utf-8') as log:
            log.write(f"\n{'='*60}\n")
            log.write(f"[ERROR] Exception in /generate-video/{script_id}\n")
            log.write(f"  Error: {str(e)}\n")
            log.write(f"  Traceback:\n{traceback.format_exc()}\n")
            log.write(f"{'='*60}\n")

        print(f"[ERROR] Video generation exception:\n{error_details}")
        return jsonify({'error': f'Video generation error: {str(e)}'}), 500
    finally:
        conn.close()

def post_to_facebook_with_keys(video_path, script, api_keys):
    """Upload video to Facebook Page using api_keys dict"""

    url = f"https://graph.facebook.com/v18.0/{api_keys['facebook_page_id']}/videos"

    # Generate relevant hashtags
    hashtags = generate_hashtags(script.get('topic', ''), script['hook'], script['payoff'])
    caption = f"{script['hook']} 🤯\n\n{script['payoff']}\n\n{hashtags}"
    
    try:
        with open(video_path, 'rb') as video_file:
            files = {'source': video_file}
            data = {
                'access_token': api_keys['facebook_page_token'],
                'description': caption
            }
            
            response = requests.post(url, files=files, data=data)
            
            if response.status_code == 200:
                video_id = response.json().get('id')
                print(f"[OK] Posted to Facebook: {video_id}")
                return video_id
            else:
                print(f"[ERROR] Upload failed: {response.text}")
                return None

    except Exception as e:
        print(f"[ERROR] Error posting: {e}")
        return None

# ============================================================================
# SCHEDULING ROUTES
# ============================================================================

@app.route('/schedule')
@login_required
def schedule():
    """Show scheduling page with available videos"""
    conn = get_db()

    # Get unposted videos
    videos = conn.execute('''
        SELECT v.*, s.topic, s.hook, s.viral_score
        FROM videos v
        JOIN scripts s ON v.script_id = s.id
        WHERE v.user_id = ?
        AND v.status = 'completed'
        AND v.facebook_video_id IS NULL
        ORDER BY s.viral_score DESC
    ''', (session['user_id'],)).fetchall()

    # Get scheduled posts
    scheduled = conn.execute('''
        SELECT sp.*, v.file_path, s.topic
        FROM scheduled_posts sp
        JOIN videos v ON sp.video_id = v.id
        JOIN scripts s ON v.script_id = s.id
        WHERE sp.user_id = ?
        ORDER BY sp.scheduled_time ASC
    ''', (session['user_id'],)).fetchall()

    conn.close()

    return render_template('schedule.html', videos=videos, scheduled=scheduled)

@app.route('/schedule-posts', methods=['POST'])
@login_required
def schedule_posts():
    """Schedule multiple videos to be posted at specified intervals"""

    data = request.get_json()

    if not data:
        return jsonify({'error': 'No data provided'}), 400

    video_ids = data.get('video_ids', [])
    start_time = data.get('start_time')  # Format: "2025-01-12T08:00"
    interval_hours = data.get('interval_hours', 2)

    if not video_ids:
        return jsonify({'error': 'No videos selected'}), 400

    if not start_time:
        return jsonify({'error': 'Start time required'}), 400

    try:
        # Parse the start time
        scheduled_time = datetime.fromisoformat(start_time.replace('Z', '+00:00'))

        conn = get_db()

        # Schedule each video
        scheduled_count = 0
        for i, video_id in enumerate(video_ids):
            # Calculate scheduled time for this video
            video_time = scheduled_time + timedelta(hours=i * interval_hours)

            # Create scheduled post
            conn.execute('''
                INSERT INTO scheduled_posts (user_id, video_id, scheduled_time)
                VALUES (?, ?, ?)
            ''', (session['user_id'], video_id, video_time.strftime('%Y-%m-%d %H:%M:%S')))

            scheduled_count += 1

        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'message': f'Scheduled {scheduled_count} posts',
            'scheduled_count': scheduled_count
        })

    except ValueError as e:
        return jsonify({'error': f'Invalid datetime format: {str(e)}'}), 400
    except Exception as e:
        return jsonify({'error': f'Scheduling failed: {str(e)}'}), 500

@app.route('/scheduled-posts')
@login_required
def scheduled_posts_list():
    """Show all scheduled posts with status"""
    conn = get_db()

    posts = conn.execute('''
        SELECT sp.*, s.topic, s.hook
        FROM scheduled_posts sp
        JOIN videos v ON sp.video_id = v.id
        JOIN scripts s ON v.script_id = s.id
        WHERE sp.user_id = ?
        ORDER BY sp.scheduled_time ASC
    ''', (session['user_id'],)).fetchall()

    conn.close()

    return render_template('scheduled_posts.html', posts=posts)

@app.route('/scheduled-posts/<int:post_id>/cancel', methods=['POST'])
@login_required
def cancel_scheduled_post(post_id):
    """Cancel a scheduled post"""

    conn = get_db()

    # Verify ownership
    post = conn.execute('''
        SELECT * FROM scheduled_posts WHERE id = ? AND user_id = ?
    ''', (post_id, session['user_id'])).fetchone()

    if not post:
        flash('Scheduled post not found.', 'danger')
        conn.close()
        return redirect(url_for('scheduled_posts_list'))

    # Only allow cancelling pending posts
    if post['status'] != 'pending':
        flash('Cannot cancel a post that has already been processed.', 'warning')
        conn.close()
        return redirect(url_for('scheduled_posts_list'))

    # Delete the scheduled post
    conn.execute('DELETE FROM scheduled_posts WHERE id = ?', (post_id,))
    conn.commit()
    conn.close()

    flash('Scheduled post cancelled.', 'success')
    return redirect(url_for('scheduled_posts_list'))

# ============================================================================
# QUEUE ROUTES (3-hour continuous posting)
# ============================================================================

@app.route('/queue')
@login_required
def queue_view():
    """View and manage the video queue"""
    conn = get_db()

    # Get queued items
    queued_items = conn.execute('''
        SELECT q.*, v.file_path, s.topic, s.hook, s.viral_score
        FROM video_queue q
        JOIN videos v ON q.video_id = v.id
        JOIN scripts s ON v.script_id = s.id
        WHERE q.user_id = ? AND q.status = 'queued'
        ORDER BY q.queued_at ASC
    ''', (session['user_id'],)).fetchall()

    # Get available videos not in queue
    # Only show videos that actually exist on disk, sorted by creation date (newest first), limit to 20 most recent
    all_videos = conn.execute('''
        SELECT v.*, s.topic, s.hook, s.viral_score
        FROM videos v
        JOIN scripts s ON v.script_id = s.id
        WHERE v.user_id = ?
        AND v.status = 'completed'
        AND v.id NOT IN (SELECT video_id FROM video_queue WHERE user_id = ? AND status = 'queued')
        AND v.facebook_video_id IS NULL
        ORDER BY v.created_at DESC
    ''', (session['user_id'], session['user_id'])).fetchall()

    # Filter to only show videos that exist on disk, limit to 20 most recent
    available_videos = []
    for video in all_videos:
        video_path = video['file_path']
        # Check if video file exists
        if os.path.exists(video_path):
            available_videos.append(video)
            if len(available_videos) >= 20:  # Limit to 20 most recent
                break

    conn.close()
    return render_template('queue.html', queued_items=queued_items, available_videos=available_videos)

@app.route('/add-to-queue', methods=['POST'])
@login_required
def add_to_queue():
    """Add videos to the queue"""
    video_ids = request.form.getlist('video_ids')

    if not video_ids:
        flash('Please select at least 1 video.', 'warning')
        return redirect(url_for('queue_view'))

    conn = get_db()
    added_count = 0

    for video_id in video_ids:
        # Check if video exists and belongs to user
        video = conn.execute('''
            SELECT * FROM videos WHERE id = ? AND user_id = ?
        ''', (video_id, session['user_id'])).fetchone()

        if video:
            # Check if already in queue
            existing = conn.execute('''
                SELECT * FROM video_queue WHERE video_id = ? AND user_id = ? AND status = 'queued'
            ''', (video_id, session['user_id'])).fetchone()

            if not existing:
                conn.execute('''
                    INSERT INTO video_queue (user_id, video_id, status, queued_at)
                    VALUES (?, ?, 'queued', CURRENT_TIMESTAMP)
                ''', (session['user_id'], video_id))
                added_count += 1

    conn.commit()
    conn.close()

    if added_count > 0:
        flash(f'Added {added_count} video(s) to queue. Will post every 3 hours!', 'success')
    else:
        flash('No new videos added (may already be in queue).', 'info')

    return redirect(url_for('queue_view'))

@app.route('/queue/<int:queue_id>/remove', methods=['POST'])
@login_required
def remove_from_queue(queue_id):
    """Remove a video from the queue"""
    conn = get_db()

    # Verify ownership
    queue_item = conn.execute('''
        SELECT * FROM video_queue WHERE id = ? AND user_id = ?
    ''', (queue_id, session['user_id'])).fetchone()

    if queue_item:
        conn.execute('DELETE FROM video_queue WHERE id = ?', (queue_id,))
        conn.commit()
        flash('Removed from queue.', 'success')
    else:
        flash('Queue item not found.', 'danger')

    conn.close()
    return redirect(url_for('queue_view'))

@app.route('/clear-queue', methods=['POST'])
@login_required
def clear_queue():
    """Clear all videos from the queue"""
    conn = get_db()

    result = conn.execute('''
        DELETE FROM video_queue WHERE user_id = ? AND status = 'queued'
    ''', (session['user_id'],))
    deleted_count = result.rowcount

    conn.commit()
    conn.close()

    flash(f'Cleared {deleted_count} video(s) from queue.', 'success')
    return redirect(url_for('queue_view'))

@app.route('/post-now/<int:video_id>', methods=['POST'])
@login_required
def post_video_now(video_id):
    """Immediately post a video to Facebook (bypasses queue)"""
    conn = get_db()

    try:
        # Get video details with script and API keys
        video = conn.execute('''
            SELECT v.*, s.hook, s.payoff, s.topic,
                   ak.facebook_page_token, ak.facebook_page_id, ak.auto_share_to_story
            FROM videos v
            JOIN scripts s ON v.script_id = s.id
            JOIN api_keys ak ON v.user_id = ak.user_id
            WHERE v.id = ? AND v.user_id = ?
        ''', (video_id, session['user_id'])).fetchone()

        if not video:
            return jsonify({'success': False, 'error': 'Video not found'}), 404

        # Check if video file exists
        if not os.path.exists(video['file_path']):
            return jsonify({'success': False, 'error': 'Video file not found on disk'}), 400

        # Check Facebook credentials
        if not video['facebook_page_token'] or not video['facebook_page_id']:
            return jsonify({'success': False, 'error': 'Facebook credentials not configured'}), 400

        # Check if already posted (race condition protection)
        if video['facebook_video_id']:
            return jsonify({'success': False, 'error': 'Video already posted to Facebook'}), 400

        # Mark video as "posting" to prevent race conditions
        conn.execute('UPDATE videos SET status = "posting" WHERE id = ?', (video_id,))
        conn.commit()

        # Post video to Facebook
        facebook_video_id = post_video_to_facebook(
            video['file_path'],
            video['hook'],
            video['payoff'],
            video['facebook_page_token'],
            video['facebook_page_id']
        )

        if facebook_video_id:
            # Success - optionally share to Story (non-critical)
            story_id = None
            try:
                if video['auto_share_to_story']:
                    story_id = share_reel_to_story(
                        facebook_video_id,
                        video['facebook_page_token'],
                        video['facebook_page_id']
                    )
            except Exception as story_error:
                print(f"Story share failed (non-critical): {story_error}")
                story_id = None

            # Update video record with success
            conn.execute('''
                UPDATE videos
                SET facebook_video_id = ?, posted_at = CURRENT_TIMESTAMP, status = 'posted'
                WHERE id = ?
            ''', (facebook_video_id, video_id))

            conn.commit()
            conn.close()

            return jsonify({
                'success': True,
                'message': 'Posted to Facebook successfully!',
                'facebook_video_id': facebook_video_id,
                'story_id': story_id
            })
        else:
            # Posting failed - reset status
            conn.execute('UPDATE videos SET status = "completed" WHERE id = ?', (video_id,))
            conn.commit()
            conn.close()
            return jsonify({'success': False, 'error': 'Facebook upload failed'}), 500

    except Exception as e:
        # Ensure connection is closed on error
        try:
            conn.execute('UPDATE videos SET status = "completed" WHERE id = ?', (video_id,))
            conn.commit()
        except:
            pass
        finally:
            try:
                conn.close()
            except:
                pass

        # Log error but don't expose internal details (safe encoding)
        try:
            error_msg = str(e).encode('ascii', 'ignore').decode('ascii')
            print(f"[ERROR] Post-now failed for video {video_id}: {error_msg}")
        except:
            print(f"[ERROR] Post-now failed for video {video_id}")
        return jsonify({'success': False, 'error': 'An unexpected error occurred. Please try again.'}), 500


# ============================================================================
# VIDEO GENERATION FUNCTIONS
# ============================================================================

def create_video_ffmpeg(script, output_path, api_keys):
    """
    Create video using FFmpeg with per-slide generation approach
    Each slide is generated independently with proper timing, then concatenated
    This ensures TTS sync and allows padding for slides that are too short
    """

    log_file = 'video_generation.log'

    def log(msg):
        """Helper function to write to log file"""
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(msg + '\n')
        print(msg)

    try:
        log(f"\n{'='*60}")
        log(f"[VIDEO] Starting video generation at {datetime.now()}")
        log(f"  Topic: {script['topic']}")
        log(f"  Output: {output_path}")
        log(f"{'='*60}\n")

        # Generate voiceover if ElevenLabs key is available
        section_durations = None
        try:
            if api_keys and api_keys.get('elevenlabs_api_key'):
                audio_path = output_path.replace('.mp4', '.mp3')
                log(f"  [TTS] Starting voiceover generation...")
                section_durations = generate_voiceover(script, audio_path, api_keys['elevenlabs_api_key'])
                if section_durations:
                    total_duration = section_durations.get('_total', {}).get('duration', 0)
                    log(f"  [OK] Generated voiceover ({total_duration:.2f}s)")
                else:
                    log(f"  [INFO] Skipping voiceover (generation failed)")
        except Exception as e:
            log(f"  [ERROR] Voiceover generation failed: {e}")
            import traceback
            log(traceback.format_exc())
            section_durations = None

        # Helper function to wrap text for optimal mobile readability
        def wrap_text(text, max_chars=24):
            """Wrap text to fit in centered 1080x1080 area - 24 chars per line"""
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

            return '\\N'.join(lines)

        # Build ASS (Advanced SubStation Alpha) file template with proper styling
        ass_template = """[Script Info]
ScriptType: v4.00+
Collisions: Normal
PlayDepth: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Verdana Bold,14,&H00FFFFFF,&H000000FF,&H00FFFF00,&H00FF00FF,1,0,0,0,100,100,0,0,1,3,1,5,100,100,420,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        # Helper function to convert seconds to ASS timestamp format (H:MM:SS.CC)
        def ass_timestamp(seconds):
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            centisecs = int((seconds - int(seconds)) * 100)
            return f"{hours}:{minutes:02d}:{secs:02d}.{centisecs:02d}"

        # Get all script sections in order
        sections = ['hook', 'fact1', 'fact2', 'fact3', 'fact4', 'payoff']

        # Generate each slide independently
        # Use unique temp directory per video generation to avoid conflicts
        import os
        import uuid
        temp_dir = os.path.join(os.getcwd(), 'temp_slides', str(uuid.uuid4()))
        os.makedirs(temp_dir, exist_ok=True)
        log(f"  [INFO] Using temp directory: {temp_dir}")

        slide_videos = []  # Initialize list to store successful slide paths

        for idx, section in enumerate(sections):
            try:
                text = script.get(section, '')
                if not text:
                    continue  # Skip empty sections

                log(f"  [SLIDE] Creating slide {idx + 1}/6: {section}")

                # Determine duration for this slide
                if section_durations and section in section_durations:
                    # Use actual audio duration + 1 second padding
                    slide_duration = section_durations[section]['duration'] + 1.0
                    section_audio = section_durations[section]['audio_file']
                    log(f"    [TIMING] {section}: {slide_duration:.2f}s (audio + 1s padding)")
                else:
                    # No audio - estimate based on word count
                    word_count = len(text.split())
                    slide_duration = max(word_count / 3.5, 2.5)
                    slide_duration = min(slide_duration, 6.0)
                    section_audio = None
                    log(f"    [TIMING] {section}: {slide_duration:.2f}s (estimated, {word_count} words)")

                wrapped_text = wrap_text(text)

                # Create ASS file for this slide
                slide_ass_path = os.path.join(temp_dir, f'slide_{idx}_{section}.ass')
                slide_ass_content = ass_template + f"Dialogue: 0,0:00:00.00,{ass_timestamp(slide_duration)},Default,,0,0,0,,{wrapped_text}\n"

                with open(slide_ass_path, 'w', encoding='utf-8') as f:
                    f.write(slide_ass_content)

                # Generate this slide's video
                slide_video_path = os.path.join(temp_dir, f'slide_{idx}_{section}.mp4')

                # Use relative path from current directory with forward slashes for FFmpeg
                slide_ass_rel = os.path.relpath(slide_ass_path).replace('\\', '/')

                if section_audio and os.path.exists(section_audio):
                    # With audio - use audio duration + padding
                    cmd = [
                        'ffmpeg',
                        '-f', 'lavfi',
                        '-i', f'color=c=black:s=1080x1920:d={slide_duration}:r=30',
                        '-i', section_audio,
                        '-vf', f"ass={slide_ass_rel}",
                        '-c:v', 'libx264',
                        '-c:a', 'aac',
                        '-preset', 'fast',
                        '-pix_fmt', 'yuv420p',
                        '-shortest',
                        '-y',
                        slide_video_path
                    ]
                else:
                    # Without audio
                    cmd = [
                        'ffmpeg',
                        '-f', 'lavfi',
                        '-i', f'color=c=black:s=1080x1920:d={slide_duration}:r=30',
                        '-vf', f"ass={slide_ass_rel}",
                        '-c:v', 'libx264',
                        '-preset', 'fast',
                        '-pix_fmt', 'yuv420p',
                        '-y',
                        slide_video_path
                    ]

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

                if result.returncode == 0:
                    log(f"    [OK] Slide created: {slide_video_path}")
                    slide_videos.append(slide_video_path)
                    # Clean up ASS file
                    try:
                        os.remove(slide_ass_path)
                    except:
                        pass
                else:
                    log(f"    [ERROR] FFmpeg error for {section}: {result.stderr[-200:]}")
                    # Clean up and continue
                    try:
                        os.remove(slide_ass_path)
                    except:
                        pass
            except Exception as e:
                log(f"    [ERROR] Exception processing slide {section}: {e}")
                import traceback
                log(traceback.format_exc())
                continue

        if not slide_videos:
            log(f"  [ERROR] No slides were generated")
            return False

        log(f"  [CONCAT] Concatenating {len(slide_videos)} slides...")

        # Create concat list file
        concat_list_path = os.path.join(temp_dir, 'concat_list.txt')
        with open(concat_list_path, 'w') as f:
            for slide_path in slide_videos:
                # Convert path for FFmpeg
                slide_path_ffmpeg = slide_path.replace('\\', '/')
                f.write(f"file '{slide_path_ffmpeg}'\n")

        # Concatenate all slides
        cmd = [
            'ffmpeg',
            '-f', 'concat',
            '-safe', '0',
            '-i', concat_list_path,
            '-c', 'copy',
            '-y',
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        # Clean up temporary files and directory
        try:
            os.remove(concat_list_path)
            for slide_path in slide_videos:
                os.remove(slide_path)
            # Remove the temp directory itself
            os.rmdir(temp_dir)
            log(f"  [INFO] Cleaned up temp directory: {temp_dir}")
        except Exception as e:
            log(f"  [WARN] Cleanup warning: {e}")

        if result.returncode == 0:
            log(f"  [OK] Final video created: {output_path}")
            log(f"{'='*60}\n")
            return True
        else:
            log(f"  [ERROR] Concatenation failed: {result.stderr[-200:]}")
            log(f"{'='*60}\n")
            # Try to clean up even on failure
            try:
                import shutil
                shutil.rmtree(temp_dir)
            except:
                pass
            return False

    except FileNotFoundError:
        log(f"  [ERROR] FFmpeg not found. Install: brew install ffmpeg (Mac) or download from ffmpeg.org")
        log(f"{'='*60}\n")
        # Cleanup on error
        try:
            import shutil
            shutil.rmtree(temp_dir)
        except:
            pass
        return False
    except Exception as e:
        log(f"  [ERROR] Error: {e}")
        import traceback
        log(traceback.format_exc())
        log(f"{'='*60}\n")
        # Cleanup on error
        try:
            import shutil
            shutil.rmtree(temp_dir)
        except:
            pass
        return False

def generate_voiceover(script, output_path, api_key):
    """
    Generate voiceover using ElevenLabs API with per-section timing
    Returns dict with {section: {'audio_file': path, 'duration': seconds}} if successful, None otherwise
    Uses Rachel voice (21m00Tcm4TlvDq8ikWAM) - clear, professional female voice
    """

    # Setup logging
    log_file = 'video_generation.log'

    def log(msg):
        """Helper function to write to log file"""
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(msg + '\n')
        print(msg)

    try:
        # ElevenLabs API endpoint - Rachel voice (clear, professional female)
        voice_id = "21m00Tcm4TlvDq8ikWAM"  # Rachel

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json"
        }

        # Voice settings for Country Gentleman style
        voice_settings = {
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.35,
                "similarity_boost": 0.8,
                "style": 0.2,
                "use_speaker_boost": True
            }
        }

        # Generate audio for each section
        sections = ['hook', 'fact1', 'fact2', 'fact3', 'fact4', 'payoff']
        section_audios = {}
        base_path = output_path.replace('.mp3', '_section_{}')

        log(f"    [TTS] Starting ElevenLabs voiceover generation...")

        for section in sections:
            text = script.get(section, '')
            if not text:
                continue

            log(f"    [TTS] Generating audio for {section}...")

            payload = voice_settings.copy()
            payload["text"] = text

            try:
                response = requests.post(url, json=payload, headers=headers, timeout=60)

                if response.status_code == 200:
                    section_audio_path = base_path.format(section)
                    with open(section_audio_path, 'wb') as f:
                        f.write(response.content)

                    # Get exact duration using ffprobe
                    try:
                        result = subprocess.run([
                            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                            '-of', 'default=noprint_wrappers=1:nokey=1', section_audio_path
                        ], capture_output=True, text=True, timeout=10)

                        if result.returncode == 0:
                            duration = float(result.stdout.strip())
                            section_audios[section] = {
                                'audio_file': section_audio_path,
                                'duration': duration
                            }
                            log(f"    [TTS] {section}: {duration:.2f}s")
                        else:
                            log(f"    [WARN] Could not get duration for {section}")
                    except Exception as e:
                        log(f"    [WARN] Error getting duration for {section}: {e}")
                else:
                    log(f"    [ERROR] ElevenLabs error for {section}: HTTP {response.status_code}")
                    log(f"    [ERROR] Response: {response.text[:200]}")
            except requests.exceptions.RequestException as e:
                log(f"    [ERROR] Request failed for {section}: {e}")
            except Exception as e:
                log(f"    [ERROR] Unexpected error for {section}: {e}")

        if not section_audios:
            log(f"    [ERROR] No audio sections were generated successfully")
            return None

        # Combine all audio files into one
        log(f"    [TTS] Combining audio sections...")
        concat_list_path = output_path.replace('.mp3', '_concat.txt')
        with open(concat_list_path, 'w', encoding='utf-8') as f:
            for section in sections:
                if section in section_audios:
                    # Use single quotes for Windows path compatibility
                    audio_path = section_audios[section]['audio_file'].replace('\\', '/')
                    f.write(f"file '{audio_path}'\n")

        # Concatenate audio files
        result = subprocess.run([
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
            '-i', concat_list_path,
            '-c', 'copy', output_path
        ], capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            log(f"    [ERROR] FFmpeg concat failed: {result.stderr}")
            # Try alternative method: use concat filter instead
            log(f"    [TTS] Trying alternative concat method...")
            input_args = []
            for section in sections:
                if section in section_audios:
                    input_args.extend(['-i', section_audios[section]['audio_file']])

            filter_complex = ''.join([f'[{i}:0]' for i in range(len(section_audios))]) + f'concat=n={len(section_audios)}:v=0:a=1[out]'

            result = subprocess.run(
                ['ffmpeg', '-y'] + input_args +
                ['-filter_complex', filter_complex, '-map', '[out]', output_path],
                capture_output=True, text=True, timeout=30
            )

        # Clean up concat file only - keep section audio files for individual slide generation
        try:
            os.remove(concat_list_path)
        except:
            pass

        # Get total duration
        if os.path.exists(output_path):
            result = subprocess.run([
                'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', output_path
            ], capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                total_duration = float(result.stdout.strip())
                log(f"    [TTS] Combined audio duration: {total_duration:.2f}s")
                # Add total duration to the return value with proper format
                section_audios['_total'] = {'audio_file': output_path, 'duration': total_duration}
                return section_audios
            else:
                log(f"    [ERROR] Could not get duration: {result.stderr}")
        else:
            log(f"    [ERROR] Output file not created: {output_path}")

        # Even if combined file failed, return individual sections
        total_duration = sum(info['duration'] for info in section_audios.values() if isinstance(info, dict))
        section_audios['_total'] = {'audio_file': None, 'duration': total_duration}
        log(f"    [TTS] Using individual sections with total duration: {total_duration:.2f}s")
        return section_audios

    except Exception as e:
        log(f"    [ERROR] Voiceover error: {e}")
        import traceback
        log(traceback.format_exc())
        return None

def escape_text(text):
    """Not needed anymore with subtitle approach"""
    return text

# ============================================================================
# RUN APP
# ============================================================================

# Start the scheduler when the module is imported (for gunicorn/Railway)
# This ensures background jobs run in production
try:
    start_scheduler()
except Exception as e:
    print(f"[WARNING] Failed to start scheduler: {e}")

if __name__ == '__main__':
    # Create necessary directories for Railway deployment
    directories = [
        'videos',
        os.path.join('videos', '1'),
        'temp_slides',
        'flask_session'
    ]

    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        print(f"[OK] Created directory: {directory}")

    # Initialize database
    if not os.path.exists(app.config['DATABASE']):
        init_db()
    else:
        # Ensure new tables exist even if DB already exists
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()

        # Check if scheduled_posts table exists
        c.execute('''
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='scheduled_posts'
        ''')

        if not c.fetchone():
            # Create scheduled_posts table
            c.execute('''
                CREATE TABLE IF NOT EXISTS scheduled_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    video_id INTEGER NOT NULL,
                    scheduled_time TIMESTAMP NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    posted_at TIMESTAMP,
                    facebook_video_id TEXT,
                    story_id TEXT,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (video_id) REFERENCES videos(id)
                )
            ''')
            conn.commit()
            print("[OK] Added scheduled_posts table to existing database")

        # Check if video_queue table exists
        c.execute('''
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='video_queue'
        ''')

        if not c.fetchone():
            # Create video_queue table
            c.execute('''
                CREATE TABLE IF NOT EXISTS video_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    video_id INTEGER NOT NULL,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    queued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'queued',
                    posted_at TIMESTAMP,
                    facebook_video_id TEXT,
                    story_id TEXT,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (video_id) REFERENCES videos(id)
                )
            ''')
            conn.commit()
            print("[OK] Added video_queue table to existing database")

        conn.close()

    # Create videos directory
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    print("\n" + "="*60)
    print("VIRAL REELS GENERATOR")
    print("="*60)
    print(f"\nAdmin email: {ADMIN_EMAIL}")
    print("   (This account gets lifetime free access)\n")
    print("Starting server at http://localhost:5000")
    print("\nScheduler: ACTIVE")
    print("  - Scheduled posts: checks every 60 seconds")
    print("  - Video queue: processes every 3 hours")
    print("  - Script generation: processes every 30 seconds")
    print("  - Auto-shares to Story if enabled")
    print("\nPress CTRL+C to stop\n")

    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
