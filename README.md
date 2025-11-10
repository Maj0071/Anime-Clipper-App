# Anime Auto-Clipper

**Auto-generate viral-ready anime clips for TikTok and Instagram**

Upload a long anime video → get 5-20 short, stylized, platform-ready clips (9:16, captions, sound-leveled, watermark) prioritized for "viral" hooks—no manual editing.

## Features

- 🤖 **AI-Powered Analysis**: Whisper ASR + scene detection + motion tracking
- 🎬 **Smart Clip Selection**: Scores candidates based on speech hooks, motion, audio peaks, and keywords
- 🎨 **4 Caption Templates**: Clean, Manga Pop, Impact Text, Karaoke
- 📱 **Platform-Ready**: 9:16 (TikTok/IG), 1:1, 4:5 aspect ratios
- 🔊 **Audio Normalization**: -14 LUFS loudness with auto-ducking
- 💧 **Watermarks**: Customizable branding overlay
- ⚡ **Batch Processing**: Queue-based rendering with progress tracking

## Tech Stack

- **Frontend**: Next.js 14, TypeScript, Tailwind CSS
- **Backend**: FastAPI, SQLAlchemy, Celery
- **ML/Video**: OpenAI Whisper, OpenCV, FFmpeg
- **Storage**: MinIO (S3-compatible)
- **Database**: PostgreSQL
- **Queue**: Redis

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.10+
- Node.js 18+
- FFmpeg (for local development)

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/yourusername/anime-auto-clipper.git
cd anime-auto-clipper
```

2. **Start services with Docker Compose**
```bash
docker-compose up -d
```

This will start:
- PostgreSQL (port 5432)
- Redis (port 6379)
- MinIO (port 9000, console 9001)
- FastAPI backend (port 8000)
- Celery workers
- Celery Flower (port 5555)
- Next.js frontend (port 3000)

3. **Create MinIO bucket**
```bash
# Access MinIO console at http://localhost:9001
# Login: minioadmin / minioadmin
# Create bucket named "anime-clips"
```

4. **Run database migrations**
```bash
docker-compose exec api alembic upgrade head
```

5. **Access the application**
- Frontend: http://localhost:3000
- API Docs: http://localhost:8000/docs
- Flower (Celery monitor): http://localhost:5555
- MinIO Console: http://localhost:9001

## Project Structure

```
anime-auto-clipper/
├── frontend/                 # Next.js app
│   ├── src/
│   │   ├── app/             # App router pages
│   │   │   ├── page.tsx     # Home/upload page
│   │   │   ├── analyze/[id] # Analysis status page
│   │   │   ├── gallery/[id] # Candidate gallery
│   │   │   └── export/[id]  # Export/render page
│   │   ├── components/      # React components
│   │   │   ├── VideoUploader.tsx
│   │   │   ├── CandidateGallery.tsx
│   │   │   ├── TemplateSelector.tsx
│   │   │   └── RenderQueue.tsx
│   │   └── lib/            # API client, utils
│   └── package.json
│
├── backend/                 # FastAPI app
│   ├── app/
│   │   ├── main.py         # FastAPI application
│   │   ├── database.py     # SQLAlchemy setup
│   │   ├── models.py       # Database models
│   │   ├── api/            # API routes
│   │   │   ├── auth.py
│   │   │   ├── videos.py
│   │   │   ├── jobs.py
│   │   │   └── renders.py
│   │   ├── services/       # Business logic
│   │   │   ├── s3_service.py
│   │   │   ├── auth_service.py
│   │   │   └── video_service.py
│   │   └── workers/        # Celery tasks
│   │       ├── celery_app.py
│   │       ├── analyzer.py  # Video analysis
│   │       └── renderer.py  # Clip rendering
│   ├── alembic/            # DB migrations
│   ├── tests/
│   └── requirements.txt
│
├── docker/
│   ├── Dockerfile.api
│   ├── Dockerfile.worker
│   └── Dockerfile.frontend
│
├── docker-compose.yml
├── config.yaml             # Configuration
└── README.md
```

## Configuration

Edit `config.yaml` to customize behavior:

```yaml
analysis:
  clip_min_s: 7              # Minimum clip length
  clip_max_s: 15             # Maximum clip length
  target_s: 10               # Target clip length
  candidates_per_minute: 4   # Candidates generated per minute

scoring:
  weights:
    speech_hook: 0.30        # Weight for hook phrases
    motion: 0.25             # Weight for motion intensity
    audio_peak: 0.20         # Weight for audio energy
    keyword_match: 0.15      # Weight for keyword matching
    scene_freshness: 0.10    # Weight for avoiding overlaps

whisper:
  model: base                # Whisper model: tiny, base, small, medium, large
  language: auto             # Language code or 'auto'

render:
  templates:
    - clean                  # High-contrast subtitles
    - manga                  # Bold comic-style text
    - impact                 # Word-by-word emphasis
    - karaoke                # Progressive highlight
  default_template: clean
  loudness_target: -14       # LUFS
  output_formats:
    - "9:16"                 # TikTok/IG Reels
    - "1:1"                  # Instagram Feed
    - "4:5"                  # Instagram Story
```

## API Usage

### 1. Register & Login

```bash
# Register
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "secure_password"}'

# Login
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "secure_password"}'
# Returns: {"access_token": "...", "token_type": "bearer"}
```

### 2. Upload Video

```bash
# Initialize upload
curl -X POST http://localhost:8000/uploads/init \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"filename": "anime.mp4", "filesize": 50000000}'
# Returns: {"upload_url": "...", "upload_id": "..."}

# Upload to signed URL (use your S3 client)
# Then create video record:
curl -X POST http://localhost:8000/videos \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"upload_id": "...", "title": "My Anime", "tags": ["action", "fight"]}'
# Returns: {"video_id": "..."}
```

### 3. Analyze Video

```bash
curl -X POST http://localhost:8000/jobs/analyze \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "video_id": "VIDEO_ID",
    "keywords": ["fight", "epic"],
    "targets": {
      "clip_min_s": 7,
      "clip_max_s": 15,
      "target_s": 10
    }
  }'
# Returns: {"job_id": "..."}

# Check status
curl http://localhost:8000/jobs/JOB_ID \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 4. Get Candidates

```bash
curl http://localhost:8000/videos/VIDEO_ID/candidates \
  -H "Authorization: Bearer YOUR_TOKEN"
# Returns: {"candidates": [...]}
```

### 5. Render Clips

```bash
curl -X POST http://localhost:8000/renders \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "candidate_ids": ["CAND_1", "CAND_2"],
    "template": "manga",
    "outputs": ["9:16", "1:1"],
    "watermark": "@myanime",
    "loudness": "-14",
    "captions": "on"
  }'
# Returns: {"render_id": "..."}

# Check render status
curl http://localhost:8000/renders/RENDER_ID \
  -H "Authorization: Bearer YOUR_TOKEN"
# Returns: {"status": "completed", "files": {...}}
```

## Caption Templates

### 1. Clean Subtitles
- High-contrast white text with black outline
- Safe zones for TikTok UI
- Traditional subtitle positioning

### 2. Manga Pop
- Bold yellow text with thick borders
- Comic starburst intro animation
- Subtle 2-4% zoom effect

### 3. Impact Text
- Word-by-word pop-in
- Emphasizes nouns/verbs in red
- Staggered vertical positioning

### 4. Karaoke
- Progressive word highlighting
- Base text in gray, active words in yellow
- Follows Whisper word timestamps

## Scoring Algorithm

Each candidate clip is scored using weighted factors:

```python
score = (
  0.30 * speech_hook +      # Hook phrases ("Wait!", "What?")
  0.25 * motion +            # Visual motion intensity
  0.20 * audio_peak +        # Audio energy spikes
  0.15 * keyword_match +     # User keyword matches
  0.10 * scene_freshness     # Avoid overlapping clips
)
```

### Speech Hook Detection
Identifies attention-grabbing phrases:
- Interjections: "Wait", "Hey", "No!", "Stop"
- Questions: "Who", "What", "Why", "How"
- Exclamations: Words ending with "!"

### Motion Scoring
- Frame differencing to measure visual change
- Optical flow for camera/character movement
- Normalized per video (0-1 scale)

### Audio Peaks
- RMS energy analysis per second
- Detects cheers, explosions, music drops
- Threshold: mean + 1.2σ

## Development

### Running Locally (without Docker)

1. **Setup Python environment**
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

2. **Setup PostgreSQL & Redis**
```bash
# Install and start PostgreSQL
# Install and start Redis
```

3. **Run migrations**
```bash
alembic upgrade head
```

4. **Start backend**
```bash
uvicorn app.main:app --reload --port 8000
```

5. **Start workers**
```bash
celery -A app.workers.celery_app worker --loglevel=info
```

6. **Start frontend**
```bash
cd frontend
npm install
npm run dev
```

### Running Tests

```bash
# Backend tests
cd backend
pytest tests/ -v

# Frontend tests
cd frontend
npm test
```

## Performance Optimization

### GPU Acceleration
For faster processing, use GPU-enabled workers:
```yaml
# docker-compose.yml
worker:
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
```

### Whisper Model Selection
- `tiny`: Fastest, least accurate (~1x realtime on CPU)
- `base`: Good balance (~2x realtime on CPU)
- `small`: Better accuracy (~4x realtime on CPU)
- `medium`: High accuracy (~8x realtime, needs GPU)
- `large`: Best accuracy (~15x realtime, needs GPU)

### Parallel Processing
Adjust worker concurrency:
```bash
celery -A app.workers.celery_app worker --concurrency=4
```

## Troubleshooting

### FFmpeg errors
Ensure FFmpeg is installed with all codecs:
```bash
ffmpeg -version
ffmpeg -codecs | grep h264
```

### Whisper out of memory
Reduce model size or batch size:
```python
# In analyzer.py
model = whisper.load_model('tiny')  # Instead of 'base'
```

### S3 upload failures
Check MinIO credentials and bucket permissions.

### Database connection errors
Verify PostgreSQL is running and credentials match `docker-compose.yml`.

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

MIT License - see LICENSE file for details

## Acknowledgments

- OpenAI Whisper for ASR
- FFmpeg for video processing
- Scene detection inspired by PySceneDetect
- TikTok/IG format guidelines from Meta documentation

## Support

- Documentation: https://docs.animeclipper.com
- Issues: https://github.com/yourusername/anime-auto-clipper/issues
- Discord: https://discord.gg/animeclipper

---

**Note**: Users are responsible for ensuring they have the rights to upload and distribute their content. This tool is for personal/educational use.
