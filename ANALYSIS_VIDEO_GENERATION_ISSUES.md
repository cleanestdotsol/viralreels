# Railway Video Generation Failure Analysis

**Date:** 2026-01-15
**Status:** CRITICAL - Video generation completely broken on Railway

---

## Executive Summary

Video generation is experiencing **4 critical failures** on Railway that prevent any videos from being created:

1. **Path Duplication Bug** - FFmpeg cannot find audio files due to relative path issues
2. **FFmpeg Slide Generation Failing** - All slide video creation returns errors
3. **Railway Worker Timeout (30s)** - Gunicorn kills workers during video generation
4. **Synchronous Architecture** - Video generation blocks HTTP request, causing timeouts

**Root Cause:** Video generation is synchronous and takes >60 seconds, but Railway has a 30-second worker timeout.

---

## Issue 1: Path Duplication Bug (CRITICAL)

### Error Log
```
[concat @ 0x23f07140] Impossible to open 'videos/5/videos/5/video_20_20260115_165428_section_hook'
[in#0 @ 0x23f06e80] Error opening input: No such file or directory
Error opening input file videos/5/video_20_20260115_165428_concat.txt.
```

### Root Cause Analysis

**Location:** `app.py:3442-3448`

```python
# concat_list_path = "videos/5/video_20_20260115_165428_concat.txt"
concat_list_path = output_path.replace('.mp3', '_concat.txt')

with open(concat_list_path, 'w', encoding='utf-8') as f:
    for section in sections:
        if section in section_audios:
            # section_audio_path = "videos/5/video_20_20260115_165428_section_hook"
            audio_path = section_audios[section]['audio_file'].replace('\\', '/')
            f.write(f"file '{audio_path}'\n")
```

**Problem:** When FFmpeg reads the concat file at `videos/5/video_concat.txt`, it interprets the paths as **relative to the concat file's directory**. So `file 'videos/5/video_section_hook'` becomes `videos/5/videos/5/video_section_hook`.

**Example:**
- Concat file location: `/app/videos/5/video_concat.txt`
- Entry in concat file: `file 'videos/5/video_section_hook.mp3'`
- FFmpeg tries to open: `/app/videos/5/videos/5/video_section_hook.mp3` ❌
- Actual file location: `/app/videos/5/video_section_hook.mp3` ✅

### Solution

**Option 1: Use relative paths from concat file directory**
```python
# In generate_voiceover(), app.py:3447
concat_dir = os.path.dirname(concat_list_path)
for section in sections:
    if section in section_audios:
        audio_path = section_audios[section]['audio_file']
        # Make path relative to concat file directory
        rel_path = os.path.relpath(audio_path, concat_dir).replace('\\', '/')
        f.write(f"file '{rel_path}'\n")
```

**Option 2: Use absolute paths**
```python
# In generate_voiceover(), app.py:3447
for section in sections:
    if section in section_audios:
        audio_path = os.path.abspath(section_audios[section]['audio_file']).replace('\\', '/')
        f.write(f"file '{audio_path}'\n")
```

**Recommended:** Option 2 (absolute paths) - more reliable across environments.

---

## Issue 2: FFmpeg Slide Generation Failing (CRITICAL)

### Error Log
```
[SLIDE] Creating slide 1/6: hook
[TIMING] hook: 4.29s (audio + 1s padding)
[ERROR] FFmpeg error for hook:
frame=    0 fps=0.0 q=0.0 size=       0KiB time=N/A bitrate=N/A speed=N/A
```

### Root Cause Analysis

**Location:** `app.py:3220-3233`

```python
cmd = [
    'ffmpeg',
    '-f', 'lavfi',
    '-i', f'color=c=black:s=1080x1920:d={slide_duration}:r=30',
    '-i', section_audio,
    '-vf', f"ass={slide_ass_rel}",
    '-c:v', 'libx264',
    '-c:a', 'aac',
    '-preset', 'fast',
    '-pix_fmt', 'yuv420p',
    '-shortest',
    '-y',
    slide_video_path
]
```

**Problem:** The ASS subtitle file path is relative, but FFmpeg cannot find it. The `slide_ass_rel` is computed as:

```python
# app.py:3216
slide_ass_rel = os.path.relpath(slide_ass_path).replace('\\', '/')
```

This creates a path like `temp_slides/uuid/slide_0_hook.ass`, but FFmpeg's current working directory might be different.

**Additional Issue:** The error shows `frame=0 fps=0.0`, which means FFmpeg is not encoding any frames. This could be due to:
1. ASS file not found
2. Invalid ASS syntax
3. Font missing (Verdana Bold not available on Railway)

### Solution

**Fix 1: Use absolute paths for ASS files**
```python
# In create_video_ffmpeg(), app.py:3216
slide_ass_abs = os.path.abspath(slide_ass_path).replace('\\', '/')
cmd = [
    'ffmpeg',
    '-f', 'lavfi',
    '-i', f'color=c=black:s=1080x1920:d={slide_duration}:r=30',
    '-i', section_audio,
    '-vf', f"ass={slide_ass_abs}",
    # ... rest of command
]
```

**Fix 2: Add font to Railway build**
```toml
# nixpacks.toml
[phases.setup]
nixPkgs = ["python3", "ffmpeg", "gcc", "postgresql_16.dev", "freefont"]
```

**Fix 3: Add error detection**
```python
# Check if ASS file exists before FFmpeg call
if not os.path.exists(slide_ass_path):
    log(f"    [ERROR] ASS file not found: {slide_ass_path}")
    continue

# Verify FFmpeg can read the ASS file
result = subprocess.run(['ffmpeg', '-f', 'lavfi', '-i', 'color=c=black:s=1080x1920:d=1',
                        '-vf', f"ass='{slide_ass_abs}'",
                        '-frames:v', '1', '-f', 'null', '-'],
                       capture_output=True, text=True, timeout=5)
if 'ass' in result.stderr.lower() or 'error' in result.stderr.lower():
    log(f"    [ERROR] FFmpeg cannot use ASS filter: {result.stderr[:200]}")
    continue
```

---

## Issue 3: Railway Worker Timeout (CRITICAL)

### Error Log
```
[2026-01-15 16:54:58 +0000] [1] [CRITICAL] WORKER TIMEOUT (pid:4)
[2026-01-15 16:54:58 +0000] [4] [INFO] Worker exiting (pid: 4)
```

### Root Cause Analysis

**Railway Configuration:** Railway has a **30-second timeout** for HTTP workers (gunicorn).

**Timeline:**
1. `16:54:28` - Video generation starts
2. `16:54:58` - Worker timeout (exactly 30 seconds later)
3. Worker killed, video generation incomplete

**Location:** `app.py:2568-2612`

```python
@app.route('/generate-video/<int:script_id>', methods=['POST'])
@login_required
def generate_video(script_id):
    # ... validation code ...

    # ❌ BLOCKING CALL - takes 60+ seconds
    success = create_video_ffmpeg(script, video_path, api_keys)

    if success:
        # Save video record
        # ...
```

**Problem:** The route handler calls `create_video_ffmpeg()` synchronously, which takes 60+ seconds:
- ElevenLabs TTS: ~25 seconds (6 API calls × ~4s each)
- Slide generation: ~30 seconds (6 slides × ~5s each)
- Concatenation: ~5 seconds
- **Total: ~60 seconds**

Railway's gunicorn worker is configured to timeout after 30 seconds, killing the process mid-generation.

### Solution

**Convert video generation to async job queue** (same pattern as script generation):

```python
# 1. Create video_generation_jobs table
CREATE TABLE video_generation_jobs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    script_id INTEGER NOT NULL,
    status TEXT DEFAULT 'pending',
    video_path TEXT,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (script_id) REFERENCES scripts(id)
);

# 2. Update route to queue job instead of blocking
@app.route('/generate-video/<int:script_id>', methods=['POST'])
@login_required
def generate_video(script_id):
    # Queue the job
    conn.execute('''
        INSERT INTO video_generation_jobs (user_id, script_id, status)
        VALUES (?, ?, 'pending')
    ''', (session['user_id'], script_id))

    return jsonify({'success': True, 'redirect': f'/video-status/{job_id}'})

# 3. Create background job processor
def process_video_generation_job(job_id):
    # Similar to process_script_generation_job()
    # Runs in APScheduler thread, safe from Railway timeouts
```

**This is the ONLY sustainable solution.** We cannot make video generation fast enough to fit in 30 seconds.

---

## Issue 4: Missing Font on Railway

### Error Analysis

FFmpeg ASS subtitle filter uses **Verdana Bold** font:

```python
# app.py:3154
Style: Default,Verdana Bold,14,&H00FFFFFF,&H000000FF,&H00FFFF00,&H00FF00FF,1,0,0,0,100,100,0,0,1,3,1,5,100,100,420,1
```

**Problem:** Railway's minimal Nixpacks image may not include Verdana font.

**Symptoms:**
- FFmpeg error: "font not found"
- Slide generation fails silently
- Output: `frame=0 fps=0.0 q=0.0 size=0KiB`

### Solution

**Add fonts to nixpacks.toml:**
```toml
[phases.setup]
nixPkgs = ["python3", "ffmpeg", "gcc", "postgresql_16.dev", "freefont", "dejavu-fonts"]
```

**Or use a font that's guaranteed to exist:**
```python
# Change font in ASS template
# From: Verdana Bold
# To: Arial (more widely available)
Style: Default,Arial,14,&H00FFFFFF,&H000000FF,&H00FFFF00,&H00FF00FF,1,0,0,0,100,100,0,0,1,3,1,5,100,100,420,1
```

---

## Implementation Priority

### Phase 1: Quick Fixes (Do First)
1. ✅ **Add ffmpeg to nixpacks.toml** - COMPLETED
2. 🔧 **Fix path duplication bug** (Issue #1) - Use absolute paths in concat file
3. 🔧 **Fix ASS file path** (Issue #2) - Use absolute paths for subtitle files

### Phase 2: Critical Fix
4. 🔧 **Convert video generation to async job queue** (Issue #3) - ESSENTIAL
   - Create `video_generation_jobs` table
   - Create `process_video_generation_job()` function
   - Create `/video-status/<job_id>` status page
   - Add to APScheduler queue processor

### Phase 3: Polish
5. 🔧 **Add fonts to nixpacks.toml** (Issue #4)
6. 🔧 **Better error handling and logging**
7. 🔧 **Video preview on status page**

---

## Testing Checklist

After fixes:
- [ ] Video generation completes without worker timeout
- [ ] Audio concatenation works (no path duplication errors)
- [ ] Slide generation succeeds (no "frame=0" errors)
- [ ] Subtitles render correctly (fonts available)
- [ ] Final video has audio and video in sync
- [ ] Status page shows progress correctly
- [ ] User redirected to dashboard after completion

---

## Code References

| Issue | File | Lines | Function |
|-------|------|-------|----------|
| Path Duplication | app.py | 3442-3448 | `generate_voiceover()` |
| ASS File Path | app.py | 3206-3246 | `create_video_ffmpeg()` |
| Worker Timeout | app.py | 2568-2612 | `generate_video()` route |
| Missing Font | app.py | 3154 | ASS template definition |
| Async Job Pattern | app.py | 514-688 | `process_script_generation_job()` |

---

## Notes

- Script generation was successfully converted to async, proving this pattern works
- The same pattern MUST be applied to video generation
- Railway's 30-second timeout is non-negotiable - we MUST work around it
- FFmpeg is now installed, but there are path and font issues to resolve
