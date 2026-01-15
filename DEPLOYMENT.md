# HostGator Deployment Guide for ViralReels

## Prerequisites
- HostGator account with cPanel access
- Python 3.8+ support
- Domain: reportriser.com
- SSL certificate (usually free with HostGator)

---

## Step 1: Prepare Your Local Files

### 1.1 Update Facebook App URLs
Before uploading, update your Facebook App:
1. Go to https://developers.facebook.com/apps/
2. Open your app settings
3. Update these URLs to use your new domain:
   - **Privacy Policy**: `https://reportriser.com/privacy.html`
   - **Terms of Service**: `https://reportriser.com/terms.html`
   - **Redirect URI**: `https://reportriser.com/facebook/callback`
   - **App Domains**: Add `reportriser.com`

### 1.2 Files to Upload
Upload these via **cPanel → File Manager** or **FTP**:

```
public_html/
├── app.py
├── passenger_wsgi.py
├── requirements.txt
├── .htaccess
├── .env (create from .env.production template)
├── privacy.html
├── terms.html
├── templates/ (entire folder)
└── videos/ (create this folder, set permissions to 755)
```

---

## Step 2: Upload Files to HostGator

### Method 1: cPanel File Manager
1. Log into cPanel
2. Click **"File Manager"**
3. Navigate to `public_html/`
4. Click **"Upload"** and upload all files

### Method 2: FTP/SFTP
Use FileZilla or WinSCP:
- Host: `reportriser.com` (or your HostGator server IP)
- Username: Your cPanel username
- Password: Your cPanel password
- Port: 21 (FTP) or 22 (SFTP)

---

## Step 3: Configure the Application

### 3.1 Update `.env` File
In cPanel File Manager:
1. Copy `.env.production` to `.env`
2. Edit `.env` and update:
   ```bash
   SECRET_KEY=generate_a_random_secret_key_here
   FACEBOOK_APP_SECRET=your_actual_app_secret
   DOMAIN_NAME=reportriser.com
   BASE_URL=https://reportriser.com
   ADMIN_EMAIL=your-email@example.com
   ```

### 3.2 Generate Secret Key
Run this in Python to generate a secret key:
```python
import secrets
print(secrets.token_hex(32))
```

### 3.3 Set File Permissions
In cPanel File Manager or via SSH:
```bash
chmod 644 app.py
chmod 644 passenger_wsgi.py
chmod 600 .env  # Important: keep .env private!
chmod 755 videos/
```

---

## Step 4: Install Python Dependencies

### Via cPanel (Setup Python App):
1. In cPanel, look for **"Setup Python App"**
2. Click **"Create Application"**
3. Configure:
   - **Python version**: 3.9 or higher
   - **Application root**: `/public_html`
   - **Application URL**: `reportriser.com` (leave blank for root)
   - **Application startup file**: `passenger_wsgi.py`
   - **Application entry point**: `application`

4. Click **"Create"**
5. Go to the application details
6. Click **"Restart"**

### Install pip packages:
In the cPanel Python App interface:
1. Click **"Run Pip Install"** next to your app
2. Enter: `requirements.txt`
3. Click **"Install"**

---

## Step 5: Configure Domain

### 5.1 Point Domain to HostGator
1. Log into your domain registrar (where you bought reportriser.com)
2. Go to **DNS Settings** or **Nameservers**
3. Update nameservers to HostGator's:
   - `ns1.hostgator.com`
   - `ns2.hostgator.com`
   (Use the actual nameservers HostGator provided you)

### 5.2 Add Domain in cPanel
1. In cPanel, click **"Addon Domains"**
2. New domain name: `reportriser.com`
3. Subdomain/FTP username: auto-filled
4. Document root: `/public_html`
5. Click **"Add Domain"**

---

## Step 6: SSL Certificate (HTTPS)

### 6.1 Install Free SSL
1. In cPanel, find **"SSL/TLS Status"** or **"Let's Encrypt"**
2. Select `reportriser.com`
3. Click **"Install"** or **"Issue"**
4. Wait for installation (usually 1-2 minutes)

### 6.2 Force HTTPS
Your `.htaccess` file already has this:
```apache
RewriteCond %{HTTPS} off
RewriteRule ^(.*)$ https://%{HTTP_HOST}%{REQUEST_URI} [L,R=301]
```

---

## Step 7: Create Database
The app uses SQLite, which will be auto-created on first run.

If you want to use MySQL instead (recommended for production):
1. In cPanel, click **"MySQL Database Wizard"**
2. Create database: `viralreels_db`
3. Create user: `viralreels_user`
4. Grant all privileges
5. Update `.env`:
   ```bash
   DATABASE_URL=mysql://viralreels_user:password@localhost/viralreels_db
   ```

---

## Step 8: Test the Application

### 8.1 Check Application Status
1. Visit: `https://reportriser.com`
2. You should see the ViralReels landing page
3. Check error log if it doesn't work:
   - In cPanel → **"Errors"** or **"Raw Access Logs"**
   - Or: `/public_html/passenger_errors.log`

### 8.2 Verify OAuth Works
1. Visit: `https://reportriser.com/settings`
2. Click **"Connect Facebook Page"**
3. Should redirect to Facebook, then back with success message

### 8.3 Test Video Posting
1. Go to Queue
2. Click **"Post Now"** on a video
3. Check it posts to your Facebook Page

---

## Step 9: Set Up Automated Posting

The app has a built-in scheduler. On HostGator:
1. In cPanel, click **"Cron Jobs"**
2. Add a cron job to keep the scheduler alive:
   ```
   */5 * * * * /usr/bin/curl -s https://reportriser.com > /dev/null 2>&1
   ```
   This hits your site every 5 minutes to keep the scheduler running.

---

## Troubleshooting

### Issue: 500 Internal Server Error
**Solution**: Check error logs in cPanel → "Errors"

### Issue: Permission Denied
**Solution**:
```bash
chmod 755 videos/
chmod 644 app.py
chmod 600 .env
```

### Issue: Python Not Found
**Solution**: Check correct Python path:
```bash
which python3
# Then update .htaccess with correct path
```

### Issue: App Not Starting
**Solution**: In cPanel Python App interface, click "Restart"

### Issue: Facebook OAuth Fails
**Solution**:
1. Verify redirect URI is `https://reportriser.com/facebook/callback`
2. Check .env has correct APP_SECRET
3. Ensure SSL certificate is installed

---

## Maintenance

### Update Code
1. Upload new files via FTP/cPanel
2. In cPanel Python App, click **"Restart"**

### Backup Database
```bash
# Via SSH or cPanel terminal
cp viral_reels.db viral_reels.db.backup.$(date +%Y%m%d)
```

### View Logs
- cPanel → **"Errors"**
- Or: `/public_html/passenger_errors.log`

---

## Security Checklist

- ✅ SSL/HTTPS enabled
- ✅ .env file not accessible (permissions 600)
- ✅ SECRET_KEY is random and unique
- ✅ Database backed up regularly
- ✅ Facebook App Secret is secure
- ✅ Error logs don't expose sensitive info

---

## Need Help?

If you run into issues:
1. Check HostGator documentation: https://www.hostgator.com/help
2. Contact HostGator support (24/7 chat available)
3. Check error logs in cPanel

---

## Next Steps After Deployment

1. Test all functionality
2. Create your admin account
3. Connect Facebook Page
4. Generate your first video
5. Test posting to Facebook
6. Set up your posting queue

Good luck! 🚀
