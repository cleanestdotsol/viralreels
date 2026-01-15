"""
Secure configuration loader
This file loads secrets from a location outside public_html for maximum security
"""

import os
from dotenv import load_dotenv

def load_config():
    """
    Load configuration from multiple secure locations in order of priority:
    1. Server environment variables (set in cPanel)
    2. .env file in home directory (OUTSIDE public_html)
    3. .env file in current directory (for local development)
    """

    # Try to load .env from home directory (outside public_html) - MOST SECURE
    home_env = os.path.expanduser('~/.viralreels/.env')
    if os.path.exists(home_env):
        load_dotenv(home_env)
        print(f"Loaded config from: {home_env}")
        return

    # Try to load .env from current directory (development)
    local_env = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(local_env):
        load_dotenv(local_env)
        print(f"Loaded config from: {local_env}")
        return

    # Fall back to environment variables (production with cPanel env vars)
    print("Using environment variables for configuration")

# Load configuration when module is imported
load_config()

# Configuration values
def get_config(key, default=None):
    """Get configuration value with fallback"""
    return os.environ.get(key, default)

# Required configuration
SECRET_KEY = get_config('SECRET_KEY') or os.urandom(32).hex()
FACEBOOK_APP_ID = get_config('FACEBOOK_APP_ID', '2370511290077574')
FACEBOOK_APP_SECRET = get_config('FACEBOOK_APP_SECRET')
DATABASE_URL = get_config('DATABASE_URL', 'sqlite:///viral_reels.db')
DOMAIN_NAME = get_config('DOMAIN_NAME', 'localhost:5000')
BASE_URL = get_config('BASE_URL', 'http://localhost:5000')
ADMIN_EMAIL = get_config('ADMIN_EMAIL', 'your-email@example.com')

# Validate required config
if not FACEBOOK_APP_SECRET:
    raise ValueError(
        "FACEBOOK_APP_SECRET not found! "
        "Set it in cPanel environment variables or ~/.viralreels/.env"
    )
