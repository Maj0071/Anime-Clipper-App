from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import text
import os

from app.database import engine, get_db
from app.models import Base
from app.api import auth, jobs
from app.api import vidoes as videos
from app.api import renderer as renders
from app.api import templates, music, thumbnails
from app.api import clip_finder, social

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Anime Auto-Clipper API",
    description="Auto-generate viral-ready anime clips for TikTok/IG",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(videos.router, prefix="/videos", tags=["videos"])
app.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
app.include_router(renders.router, prefix="/renders", tags=["renders"])

# LOW PRIORITY: Template Marketplace, Music Library, Thumbnails
app.include_router(templates.router, prefix="/templates", tags=["templates"])
app.include_router(music.router, prefix="/music", tags=["music"])
app.include_router(thumbnails.router, prefix="/thumbnails", tags=["thumbnails"])

# Clip Finder & Social Media
app.include_router(clip_finder.router, tags=["clips"])
app.include_router(social.router, tags=["social"])

# Serve thumbnail and render files from /tmp/videos
_thumb_dir = "/tmp/videos"
os.makedirs(_thumb_dir, exist_ok=True)
app.mount("/media", StaticFiles(directory=_thumb_dir), name="media")


@app.get("/")
async def root():
    return {
        "service": "Anime Auto-Clipper API",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """Health check endpoint"""
    try:
        # Test database connection
        db.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database connection failed: {str(e)}"
        )
