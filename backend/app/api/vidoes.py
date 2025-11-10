from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
import uuid

from app.database import get_db
from app.models import User, Video, Candidate
from app.api.auth import get_current_user
from app.services.s3_service import generate_signed_upload_url

router = APIRouter()


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


@router.post("/videos", response_model=VideoResponse, status_code=status.HTTP_201_CREATED)
async def create_video(
    video_data: VideoCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create video record after successful upload
    
    - **upload_id**: ID returned from /uploads/init
    - **title**: Optional video title
    - **tags**: Optional list of tags
    
    Creates a database record for the uploaded video
    """
    # Construct S3 URL from upload_id
    # In production, verify the upload actually succeeded
    s3_url = f"s3://anime-clips/uploads/{current_user.id}/{video_data.upload_id}.mp4"
    
    # Create video record
    new_video = Video(
        user_id=current_user.id,
        title=video_data.title or f"Video {video_data.upload_id[:8]}",
        src_url=s3_url,
        duration=None,  # Will be populated during analysis
        resolution=None  # Will be populated during analysis
    )
    
    db.add(new_video)
    db.commit()
    db.refresh(new_video)
    
    return {
        "video_id": str(new_video.id),
        "title": new_video.title,
        "duration": new_video.duration,
        "resolution": new_video.resolution,
        "created_at": new_video.created_at.isoformat()
    }


@router.get("/videos/{video_id}", response_model=VideoResponse)
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


@router.get("/videos", response_model=List[VideoResponse])
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


@router.delete("/videos/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
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


@router.get("/videos/{video_id}/candidates", response_model=CandidatesListResponse)
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