#!/usr/bin/env python3
"""
Generate a random SECRET_KEY for production use
Run this on your local machine and copy the output to your .env file
"""

import secrets

print("Flask SECRET_KEY for production:")
print(secrets.token_hex(32))
print("\nCopy this to your .env file as:")
print(f"SECRET_KEY={secrets.token_hex(32)}")
