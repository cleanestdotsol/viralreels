# ViralReels - Railway Docker Deployment

**Deployment Method:** Dockerfile (bypasses Nixpacks cache)

## Why Dockerfile?

Railway's Nixpacks builder was using cached nixpkgs hashes and ignoring `nixpacks.toml` changes. Switching to Dockerfile gives full control over the build process.

## System Dependencies Installed

- `ffmpeg` - Video generation
- `gcc/g++` - Python package compilation
- `postgresql-client` - Database management
- `fonts-freefont-ttf` - Free font family
- `fonts-liberation` - Liberation Sans (replaces Verdana Bold)
- `fontconfig` - Font management

## Build Process

```dockerfile
1. Start from python:3.12-slim
2. Install system packages (apt-get)
3. Install Python packages (pip)
4. Copy application code
5. Run with gunicorn on port 8080
```

## Expected Railway Build Output

```
Building using Dockerfile...
Step 1/10 : FROM python:3.12-slim
...
Step 4/10 : RUN apt-get update && apt-get install -y ffmpeg gcc g++ postgresql-client fonts-freefont-ttf fonts-liberation fontconfig
...
Successfully built [hash]
```

## Expected Application Startup

```
[OK] Scheduler started:
  - Scheduled posts: checks every 60 seconds
  - Video queue: processes every 3 hours
  - Script generation: processes every 30 seconds
  - Video generation queue: processes every 30 seconds
```

**Last updated:** Thu, Jan 15, 2026  5:55:00 PM
