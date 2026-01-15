#!/usr/bin/env python3
"""
Passenger WSGI file for HostGator deployment
This file tells Passenger how to run your Flask app
"""

import sys
import os

# Add current directory to Python path
sys.path.insert(0, os.getcwd())

# Set environment variables
os.environ['FLASK_ENV'] = 'production'

# Import the Flask app
from app import app as application

# For development, you can enable debug mode (NOT recommended for production)
# application.debug = False
