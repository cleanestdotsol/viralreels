# Setup Environment Variables in cPanel (No .env File Needed)

## Why This Is More Secure

Instead of storing secrets in a `.env` file that could potentially be accessed, we'll use cPanel's built-in environment variable system. These are stored in the server configuration and cannot be accessed via web.

---

## Step 1: Access Environment Variables in cPanel

1. Log into cPanel
2. Look for one of these:
   - **"Software"** section → **"Setup Python App"**
   - **"Advanced"** section → **"Environment Variables"**
   - Or directly in your Python app configuration

---

## Step 2: Add Environment Variables

If using **"Setup Python App"**:

1. Create or edit your Python app
2. Look for **"Environment Variables"** section
3. Add each variable:

```
Name: FLASK_ENV
Value: production

Name: SECRET_KEY
Value: 38a396599b27c155d1e2f6baaae21f5f83691db35cbd25a15d2f3161dc0598e2

Name: FACEBOOK_APP_ID
Value: 2370511290077574

Name: FACEBOOK_APP_SECRET
Value: your_actual_app_secret_here

Name: DOMAIN_NAME
Value: reportriser.com

Name: BASE_URL
Value: https://reportriser.com

Name: ADMIN_EMAIL
Value: your-email@example.com
```

4. Click **"Update"** or **"Save"**

---

## Step 3: Alternative - Use .htaccess (If no Environment Variable UI)

Add this to your `.htaccess` file:

```apache
SetEnv FLASK_ENV production
SetEnv SECRET_KEY 38a396599b27c155d1e2f6baaae21f5f83691db35cbd25a15d2f3161dc0598e2
SetEnv FACEBOOK_APP_ID 2370511290077574
SetEnv FACEBOOK_APP_SECRET your_actual_app_secret_here
SetEnv DOMAIN_NAME reportriser.com
SetEnv BASE_URL https://reportriser.com
```

⚠️ **Warning:** Values in .htaccess are less secure than cPanel env vars because they can be viewed in file backups.

---

## Step 4: Verify It's Working

Create a test file `test_env.py`:

```python
import os
print("FLASK_ENV:", os.environ.get('FLASK_ENV'))
print("SECRET_KEY:", os.environ.get('SECRET_KEY', 'NOT SET'))
print("FACEBOOK_APP_ID:", os.environ.get('FACEBOOK_APP_ID'))
```

Upload and run it. If you see values, it's working!

---

## Security Benefits

✅ **No .env file** to accidentally upload to public folder
✅ **Not accessible** via web requests
✅ **Stored in server config** - protected by file system permissions
✅ **Can be changed** without editing files
✅ **Survives app updates** - values stay in cPanel

---

## Which Method Should You Use?

**Most Secure:**
cPanel Environment Variables (Method 1-2 above)

**Good:**
.htaccess SetEnv (Method 3 above)

**Less Secure (but okay with .htaccess protection):**
.env file with proper .htaccess blocking

---

## Recommendation

**Use cPanel Environment Variables if available.** If you can't find that option, use the .htaccess SetEnv method as fallback.
