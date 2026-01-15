# Trigger Railway rebuild - Thu, Jan 15, 2026  5:45:00 PM

**Forces fresh Railway build with cache-busting:**
- nixpacks.toml: Cache-bust timestamp 2026-01-15T17:45:00Z
- Startup logs now include "Video generation queue: processes every 30 seconds"
- .dockerignore added for build optimization

**Expected build output:**
```
║ setup      │ python3, ffmpeg, gcc, postgresql_16.dev, freefont
```

**Expected startup logs:**
```
[OK] Scheduler started:
  - Scheduled posts: checks every 60 seconds
  - Video queue: processes every 3 hours
  - Script generation: processes every 30 seconds
  - Video generation queue: processes every 30 seconds  ← NEW!
```
