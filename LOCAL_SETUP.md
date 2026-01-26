# Local-Only Setup

Run the app locally as the only user: no sign-up, direct file upload, and 1‑minute clips for TikTok/Instagram.

## Quick start with Docker

```bash
docker-compose up -d
```

- **Frontend**: http://localhost:3000  
- **API**: http://localhost:8000  
- **LOCAL_MODE** and **NEXT_PUBLIC_LOCAL_MODE** are set so that:
  - Auth is optional (default user `local@local.dev` when no token).
  - Videos are uploaded directly to the API (saved under `/tmp/videos/uploads`).

Create the MinIO bucket once:

1. Open http://localhost:9001  
2. Login: `minioadmin` / `minioadmin`  
3. Create bucket: `anime-clips`

Run migrations:

```bash
docker-compose exec api alembic upgrade head
```

## Flow

1. **Upload** – Choose a video and **clip length** (15s, 30s, **1 min**, or custom). 1 min is best for Reels/TikTok.
2. **Analyze** – AI finds the best action scenes (motion, audio, hooks) and proposes clip candidates.
3. **Gallery** – Pick candidates and **Export** with caption style (Clean, Manga, Impact, Karaoke) and aspect ratio (9:16, 1:1, 4:5).
4. **Render** – Clips are cut, captioned, and normalized; download via the API.

## Without Docker

- **Backend**: set `LOCAL_MODE=true`, `DATABASE_URL`, `REDIS_URL`, and optionally S3/MinIO. Use `UPLOAD_DIR` if you want uploads somewhere other than `/tmp/videos/uploads`.
- **Frontend**: set `NEXT_PUBLIC_API_URL=http://localhost:8000` and `NEXT_PUBLIC_LOCAL_MODE=true`.
- Ensure PostgreSQL, Redis, and FFmpeg are available. MinIO is still needed for storing rendered clips unless you change the renderer to write to disk.

## Clip length

- **15s** – Short teasers  
- **30s** – Quick highlights  
- **1 min (default)** – Fits Reels and TikTok, keeps attention.  
- **Custom** – 15–180 seconds.

The analyzer uses these as `clip_min_s`, `clip_max_s`, and `target_s` to pick and trim the best segments.
