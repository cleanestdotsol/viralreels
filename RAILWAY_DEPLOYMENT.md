# Railway.app Deployment Guide for ViralReels

## Why Railway?

HostGator has Python 3.6 (too old for Flask 3.0). Railway has Python 3.11+.

Railway is:
- ✅ Free tier available ($5 credit every month!)
- ✅ Modern Python (3.11+)
- ✅ Automatic HTTPS
- ✅ One-click deployment
- ✅ Easy environment variables

---

## Deployment Steps (5 minutes)

### Step 1: Create Railway Account

1. Go to https://railway.app/
2. Click **"Sign Up"**
3. Sign up with GitHub, Google, or email

### Step 2: Create New Project

1. Click **"New Project"** → **"Deploy from GitHub Repo"**
2. Or click **"New Project"** → **"Empty Project"** (if uploading directly)

### Step 3: Connect Your Code

**Option A: From GitHub (Recommended)**
1. Push your code to a GitHub repository
2. Select it in Railway
3. Railway will auto-detect Flask

**Option B: Upload Directly**
1. Click **"New Project"** → **"Empty Project"**
2. Click **"Upload Files"** (or drag & drop)
3. Upload all your files (app.py, templates/, requirements.txt, etc.)

### Step 4: Add Environment Variables

In Railway project dashboard:

1. Click **"Variables"** tab (left sidebar)
2. Add these variables:

| Name | Value |
|------|-------|
| `FLASK_ENV` | `production` |
| `SECRET_KEY` | `38a396599b27c155d1e2f6baaae21f5f83691db35cbd25a15d2f3161dc0598e2` |
| `FACEBOOK_APP_ID` | `2370511290077574` |
| `FACEBOOK_APP_SECRET` | *(your app secret)* |
| `DOMAIN_NAME` | *(auto-generated Railway URL)* |
| `BASE_URL` | *(your Railway domain)* |
| `ADMIN_EMAIL` | *(your email)* |

### Step 5: Deploy!

Railway will:
1. Install all dependencies automatically
2. Detect Flask app
3. Start the server
4. Give you a live URL

**Your app will be live!** 🚀

---

## Step 6: Update Facebook App URLs

Once deployed, Railway will give you a URL like:
`https://viralreels-production.up.railway.app`

Update your Facebook App:
1. Go to https://developers.facebook.com/apps/
2. Open your app settings
3. Update:
   - **Privacy Policy**: `https://your-railway-url.railway.app/privacy.html`
   - **Terms**: `https://your-railway-url.railway.app/terms.html`
   - **Redirect URI**: `https://your-railway-url.railway.app/facebook/callback`

---

## Step 7: (Optional) Use Your Custom Domain

If you want to use `reportriser.com`:

1. In Railway project, click **"Domains"** tab
2. Click **"Create Domain"**
3. Enter `reportriser.com`
4. Railway will give you DNS settings
5. Go to your domain registrar (where you bought reportriser.com)
6. Update nameservers to:
   ```
   ns1.railway.app
   ns2.railway.app
   ```

---

## Costs

Railway pricing:
- **Free tier:** $5 credit each month (renews monthly)
- **Pay-as-you-go:** Only pay when you exceed free tier
- **Typical cost:** $0-5/month for this app

---

## Troubleshooting

### App won't start?
- Check **"Deploy Logs"** in Railway dashboard
- Look for Python errors

### Environment variables not working?
- Make sure you clicked **"Save"** after adding each variable
- Try restarting the deployment

### Can't connect to Facebook?
- Verify redirect URI matches exactly
- Check FACEBOOK_APP_SECRET is correct

---

## Why This Is Better Than HostGator

| Feature | HostGator | Railway |
|---------|-----------|---------|
| Python Version | 3.6 (old) | 3.11 (new) |
| Package Installation | Broken (old pip) | Automatic |
| Setup Time | Hours/days | 5 minutes |
| HTTPS | Manual config | Automatic |
| Cost | $5-10/month | Free tier |
| Support | Slow chat | Fast email |
| Deployment | FTP/manual | Git/automatic |

---

**Ready to deploy?** Go to https://railway.app/ now! 🚀
