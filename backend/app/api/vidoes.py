from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
import os
import uuid
import glob

from app.database import get_db
from app.models import User, Video, Candidate, Job
from app.api.auth import get_current_user
from app.services.s3_service import generate_signed_upload_url

router = APIRouter()
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/tmp/videos/uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


class UploadInit(BaseModel):
    filename: str
    filesize: int
    content_type: str = "video/mp4"


class UploadInitResponse(BaseModel):
    upload_url: str
    upload_id: str
    expires_in: int


class VideoCreate(BaseModel):
    upload_id: str
    title: Optional[str] = None
    tags: Optional[List[str]] = []
    source: Optional[str] = "s3"  # "s3" or "local"
    local_ext: Optional[str] = None  # e.g. ".mp4" when source=local


class VideoResponse(BaseModel):
    video_id: str
    title: Optional[str]
    duration: Optional[float]
    resolution: Optional[str]
    created_at: str
    
    class Config:
        from_attributes = True


class CandidateResponse(BaseModel):
    id: str
    start_s: float
    end_s: float
    score: float
    features: dict
    thumb_url: Optional[str]
    
    class Config:
        from_attributes = True


class CandidatesListResponse(BaseModel):
    video_id: str
    total: int
    candidates: List[CandidateResponse]


@router.post("/upload", response_model=dict)
async def direct_upload(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """
    Direct file upload to disk (for LOCAL_MODE). Saves to UPLOAD_DIR and returns upload_id and ext.
    """
    if not file.filename or not file.content_type or not file.content_type.startswith("video/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Valid video file required")
    ext = os.path.splitext(file.filename or "x.mp4")[1] or ".mp4"
    upload_id = str(uuid.uuid4())
    path = os.path.join(UPLOAD_DIR, f"{upload_id}{ext}")
    with open(path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)
    return {"upload_id": upload_id, "ext": ext}


@router.post("/uploads/init", response_model=UploadInitResponse)
async def initialize_upload(
    upload_data: UploadInit,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Initialize video upload and get signed S3 URL
    
    - **filename**: Original filename
    - **filesize**: File size in bytes (max 2GB)
    - **content_type**: MIME type (e.g., video/mp4)
    
    Returns a signed URL for direct upload to S3
    """
    # Validate file size (2GB max)
    MAX_SIZE = 2 * 1024 * 1024 * 1024  # 2GB
    if upload_data.filesize > MAX_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File size exceeds maximum of {MAX_SIZE / 1024 / 1024 / 1024}GB"
        )
    
    # Validate content type
    allowed_types = [
        'video/mp4', 'video/x-matroska', 'video/avi', 
        'video/quicktime', 'video/x-msvideo'
    ]
    if upload_data.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported content type. Allowed: {', '.join(allowed_types)}"
        )
    
    # Generate unique upload ID
    upload_id = str(uuid.uuid4())
    
    # Generate file extension
    ext_map = {
        'video/mp4': 'mp4',
        'video/x-matroska': 'mkv',
        'video/avi': 'avi',
        'video/quicktime': 'mov',
        'video/x-msvideo': 'avi'
    }
    ext = ext_map.get(upload_data.content_type, 'mp4')
    
    # Generate S3 key
    s3_key = f"uploads/{current_user.id}/{upload_id}.{ext}"
    
    # Generate signed URL
    signed_url = generate_signed_upload_url(
        s3_key,
        content_type=upload_data.content_type,
        expires_in=3600  # 1 hour
    )
    
    return {
        "upload_url": signed_url,
        "upload_id": upload_id,
        "expires_in": 3600
    }


@router.post("", response_model=VideoResponse, status_code=status.HTTP_201_CREATED)
async def create_video(
    video_data: VideoCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create video record after successful upload.
    - **upload_id**: From /uploads/init (S3) or /upload (local)
    - **source**: "s3" or "local"
    - **local_ext**: e.g. ".mp4" when source=local
    """
    if (video_data.source or "s3") == "local":
        ext = (video_data.local_ext or ".mp4").strip()
        if ext and not ext.startswith("."):
            ext = "." + ext
        if not ext:
            ext = ".mp4"
        path = os.path.join(UPLOAD_DIR, f"{video_data.upload_id}{ext}")
        if not os.path.isfile(path):
            # try glob
            matches = glob.glob(os.path.join(UPLOAD_DIR, f"{video_data.upload_id}.*"))
            path = matches[0] if matches else path
        if not os.path.isfile(path):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Local upload file not found")
        src_url = "file://" + os.path.abspath(path)
    else:
        src_url = f"s3://anime-clips/uploads/{current_user.id}/{video_data.upload_id}.mp4"

    new_video = Video(
        user_id=current_user.id,
        title=video_data.title or f"Video {video_data.upload_id[:8]}",
        src_url=src_url,
        duration=None,
        resolution=None,
    )
    db.add(new_video)
    db.commit()
    db.refresh(new_video)

    return {
        "video_id": str(new_video.id),
        "title": new_video.title,
        "duration": new_video.duration,
        "resolution": new_video.resolution,
        "created_at": new_video.created_at.isoformat(),
    }


@router.get("/{video_id}", response_model=VideoResponse)
async def get_video(
    video_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get video details by ID
    
    Returns video metadata including duration and resolution
    """
    video = db.query(Video).filter(
        Video.id == video_id,
        Video.user_id == current_user.id
    ).first()
    
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found"
        )
    
    return {
        "video_id": str(video.id),
        "title": video.title,
        "duration": video.duration,
        "resolution": video.resolution,
        "created_at": video.created_at.isoformat()
    }


@router.get("", response_model=List[VideoResponse])
async def list_videos(
    skip: int = 0,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all videos for current user
    
    - **skip**: Number of records to skip (pagination)
    - **limit**: Maximum number of records to return
    """
    videos = db.query(Video).filter(
        Video.user_id == current_user.id
    ).order_by(
        Video.created_at.desc()
    ).offset(skip).limit(limit).all()
    
    return [
        {
            "video_id": str(v.id),
            "title": v.title,
            "duration": v.duration,
            "resolution": v.resolution,
            "created_at": v.created_at.isoformat()
        }
        for v in videos
    ]


@router.delete("/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_video(
    video_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a video and all associated data
    
    This will delete:
    - Video record
    - All candidate clips
    - Transcripts
    - Jobs
    - Associated files in S3
    """
    video = db.query(Video).filter(
        Video.id == video_id,
        Video.user_id == current_user.id
    ).first()
    
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found"
        )
    
    # Delete video (cascade will handle related records)
    db.delete(video)
    db.commit()
    
    # TODO: Also delete files from S3
    # delete_from_s3(video.src_url)
    
    return None


@router.get("/{video_id}/jobs", response_model=List[dict])
async def get_video_jobs(
    video_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List jobs for a video (used by analyze page for polling)."""
    video = db.query(Video).filter(Video.id == video_id, Video.user_id == current_user.id).first()
    if not video:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
    jobs = db.query(Job).filter(Job.video_id == video_id).order_by(Job.created_at.desc()).limit(5).all()
    return [
        {
            "job_id": str(j.id),
            "video_id": str(j.video_id),
            "type": j.type,
            "status": j.status,
            "progress": j.progress,
            "logs": j.logs or {},
            "created_at": j.created_at.isoformat(),
        }
        for j in jobs
    ]


@router.get("/{video_id}/candidates", response_model=CandidatesListResponse)
async def get_video_candidates(
    video_id: str,
    min_score: Optional[float] = None,
    sort_by: str = "score",  # score, duration, start
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get candidate clips for a video
    
    - **video_id**: Video ID
    - **min_score**: Optional minimum score filter (0.0-1.0)
    - **sort_by**: Sort order (score, duration, start)
    
    Returns list of candidate clips with scores and thumbnails
    """
    # Verify video ownership
    video = db.query(Video).filter(
        Video.id == video_id,
        Video.user_id == current_user.id
    ).first()
    
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found"
        )
    
    # Query candidates
    query = db.query(Candidate).filter(Candidate.video_id == video_id)
    
    # Apply filters
    if min_score is not None:
        query = query.filter(Candidate.score >= min_score)
    
    # Apply sorting
    if sort_by == "score":
        query = query.order_by(Candidate.score.desc())
    elif sort_by == "duration":
        query = query.order_by((Candidate.end_s - Candidate.start_s).desc())
    elif sort_by == "start":
        query = query.order_by(Candidate.start_s.asc())
    
    candidates = query.all()
    
    return {
        "video_id": video_id,
        "total": len(candidates),
        "candidates": [
            {
                "id": str(c.id),
                "start_s": c.start_s,
                "end_s": c.end_s,
                "score": c.score,
                "features": c.features,
                "thumb_url": c.thumb_url
            }
            for c in candidates
        ]
    }