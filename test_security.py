#!/usr/bin/env python3
"""
Test if your .env file is properly protected
Run this BEFORE deploying to HostGator
"""

import os

def test_env_security():
    """Check if .env file exists and is readable"""

    print("=== .env Security Test ===\n")

    # Check if .env exists
    env_files = ['.env', '.env.production']
    found = []

    for env_file in env_files:
        if os.path.exists(env_file):
            found.append(env_file)
            # Check file permissions
            stat_info = os.stat(env_file)
            mode = oct(stat_info.st_mode)[-3:]
            print(f"[OK] Found: {env_file}")
            print(f"  Permissions: {mode}")

            # Warn if too open
            if mode in ['644', '666', '777']:
                print(f"  [WARNING] Permissions are too open!")
                print(f"  Recommended: 600 (owner read/write only)")
                print(f"  Fix with: chmod 600 {env_file}")
            elif mode == '600':
                print(f"  [SECURE] Permissions are perfect!")

    if not found:
        print("[OK] No .env files found (using environment variables)")
        return True

    print(f"\n=== .htaccess Protection Check ===")

    if os.path.exists('.htaccess'):
        with open('.htaccess', 'r') as f:
            content = f.read()

        if '.env' in content and 'Deny from all' in content:
            print("[OK] .htaccess blocks .env access")
        else:
            print("[WARNING] .htaccess may not block .env access!")
            print("   Ensure .htaccess contains:")
            print("   <Files .env>")
            print("     Require all denied")
            print("   </Files>")
    else:
        print("[WARNING] No .htaccess found!")

    print("\n=== Recommendation ===")
    print("For production on HostGator:")
    print("1. Use cPanel Environment Variables (most secure)")
    print("2. Or use .htaccess SetEnv directive")
    print("3. Keep .env file permissions at 600")
    print("4. Store .env outside public_html if possible")

    return len(found) == 0

if __name__ == '__main__':
    test_env_security()
