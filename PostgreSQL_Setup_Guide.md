# Railway PostgreSQL Setup Guide

## Why You Need This

Railway's free tier uses **ephemeral storage** - every time your app restarts or redeploys:
- ❌ SQLite database gets deleted
- ❌ API keys are lost
- ❌ Login sessions are lost

**Solution:** Add Railway's managed PostgreSQL database (persistent, free tier available!)

---

## Step 1: Add PostgreSQL Database to Railway

1. Go to your Railway project dashboard: https://railway.app/
2. Click on your **viralreels** project
3. Click the **"New Service"** button (top right)
4. Select **"Database"** → **"Add PostgreSQL"**
5. Click **"Add PostgreSQL"** to confirm

Railway will:
- Create a PostgreSQL database
- Automatically add a `DATABASE_URL` environment variable to your app
- Keep data persistent across deployments ✅

---

## Step 2: Wait for Deployment

Once you add PostgreSQL:
1. Railway will detect the code changes (PostgreSQL support)
2. Your app will automatically redeploy
3. Look for the log message: `[OK] Using PostgreSQL database (Railway)`
4. Wait for the green status (healthy)

---

## Step 3: Verify It Works

1. Visit your app: https://viralreels-production.up.railway.app
2. Sign up / log in
3. Go to Settings and add your API keys
4. **Wait for Railway to restart** (or manually restart)
5. **Check if your keys are still there** ✅

If your keys persist after a restart, it's working!

---

## How It Works

Your app now supports **both** databases:

- **Local development:** Uses SQLite (`viral_reels.db`)
- **Railway production:** Uses PostgreSQL (persistent)

The code automatically detects which one to use:
```python
if DATABASE_URL exists → PostgreSQL
else → SQLite
```

---

## Costs

- **PostgreSQL on Railway:** $0 free tier (512 MB storage)
- **Plenty for your app!**

---

## Troubleshooting

### App won't start after adding PostgreSQL?
- Check Deploy Logs in Railway
- Look for: `[OK] Using PostgreSQL database (Railway)`
- If you see errors, restart the deployment

### Keys still getting lost?
- Make sure you actually added the PostgreSQL service
- Check that `DATABASE_URL` is in your Variables tab (should be auto-added)
- Try manually restarting the deployment

### Can't add database?
- Make sure you're on the free tier (has database allowance)
- Try refreshing the page

---

## Benefits

✅ **Persistent data** - survives deployments and restarts
✅ **Better performance** - PostgreSQL is faster than SQLite
✅ **Scalable** - can handle multiple users
✅ **Free** - included in Railway's free tier

---

**Generated:** 2025-01-15
