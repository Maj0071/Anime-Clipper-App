from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Dict, List
import yaml

from app.database import get_db
from app.models import User, Video, Job
from app.api.auth import get_current_user
from app.workers.analyzer import analyze_video_task

router = APIRouter()


class AnalyzeRequest(BaseModel):
    video_id: str
    keywords: Optional[List[str]] = []
    targets: Optional[Dict] = {}


class AnalyzeResponse(BaseModel):
    job_id: str
    video_id: str
    status: str
    message: str


class JobStatus(BaseModel):
    job_id: str
    video_id: str
    type: str
    status: str
    progress: int
    logs: dict
    created_at: str
    
    class Config:
        from_attributes = True


def load_config():
    """Load configuration from config.yaml"""
    try:
        with open('config.yaml', 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        # Return default config if file doesn't exist
        return {
            'analysis': {
                'clip_min_s': 7,
                'clip_max_s': 15,
                'target_s': 10,
                'candidates_per_minute': 4,
                'max_candidates': 20
            },
            'scoring': {
                'weights': {
                    'speech_hook': 0.30,
                    'motion': 0.25,
                    'audio_peak': 0.20,
                    'keyword_match': 0.15,
                    'scene_freshness': 0.10
                }
            },
            'whisper': {
                'model': 'base',
                'language': 'auto'
            }
        }


@router.post("/jobs/analyze", response_model=AnalyzeResponse, status_code=status.HTTP_201_CREATED)
async def start_analysis(
    request: AnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Start video analysis job
    
    - **video_id**: ID of uploaded video
    - **keywords**: Optional keywords to boost in scoring (e.g., ["fight", "funny"])
    - **targets**: Optional override of default clip length targets
    
    Starts async job that:
    1. Transcribes audio with Whisper
    2. Detects scenes and motion
    3. Analyzes audio peaks
    4. Generates and scores candidate clips
    5. Creates thumbnails
    """
    # Verify video exists and belongs to user
    video = db.query(Video).filter(
        Video.id == request.video_id,
        Video.user_id == current_user.id
    ).first()
    
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found"
        )
    
    # Check if analysis already in progress
    existing_job = db.query(Job).filter(
        Job.video_id == request.video_id,
        Job.type == 'analyze',
        Job.status.in_(['pending', 'processing'])
    ).first()
    
    if existing_job:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Analysis already in progress for this video"
        )
    
    # Load configuration
    config = load_config()
    
    # Merge with user-provided targets
    analysis_config = config['analysis'].copy()
    if request.targets:
        analysis_config.update(request.targets)
    
    # Add other config sections
    analysis_config['keywords'] = request.keywords
    analysis_config['weights'] = config['scoring']['weights']
    analysis_config['whisper_model'] = config['whisper']['model']
    analysis_config['language'] = config['whisper'].get('language', 'auto')
    
    # Create job record
    job = Job(
        video_id=request.video_id,
        type='analyze',
        status='pending',
        progress=0,
        logs={}
    )
    
    db.add(job)
    db.commit()
    db.refresh(job)
    
    # Start async task
    analyze_video_task.delay(
        job_id=str(job.id),
        video_id=request.video_id,
        config=analysis_config
    )
    
    return {
        "job_id": str(job.id),
        "video_id": request.video_id,
        "status": "pending",
        "message": "Analysis job started. This typically takes 2-5 minutes."
    }


@router.get("/jobs/{job_id}", response_model=JobStatus)
async def get_job_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get job status and progress
    
    Returns real-time status of analysis or render job
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )
    
    # Verify user owns the video
    video = db.query(Video).filter(
        Video.id == job.video_id,
        Video.user_id == current_user.id
    ).first()
    
    if not video:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    return {
        "job_id": str(job.id),
        "video_id": str(job.video_id),
        "type": job.type,
        "status": job.status,
        "progress": job.progress,
        "logs": job.logs,
        "created_at": job.created_at.isoformat()
    }


@router.get("/jobs", response_model=List[JobStatus])
async def list_jobs(
    video_id: Optional[str] = None,
    job_type: Optional[str] = None,
    status_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List jobs for current user
    
    - **video_id**: Filter by video ID
    - **job_type**: Filter by job type (analyze, render)
    - **status_filter**: Filter by status (pending, processing, completed, failed)
    - **skip**: Pagination offset
    - **limit**: Max results
    """
    # Get all video IDs for current user
    user_video_ids = [str(v.id) for v in db.query(Video).filter(
        Video.user_id == current_user.id
    ).all()]
    
    if not user_video_ids:
        return []
    
    # Build query
    query = db.query(Job).filter(Job.video_id.in_(user_video_ids))
    
    # Apply filters
    if video_id:
        query = query.filter(Job.video_id == video_id)
    
    if job_type:
        query = query.filter(Job.type == job_type)
    
    if status_filter:
        query = query.filter(Job.status == status_filter)
    
    # Order by most recent first
    query = query.order_by(Job.created_at.desc())
    
    # Pagination
    jobs = query.offset(skip).limit(limit).all()
    
    return [
        {
            "job_id": str(j.id),
            "video_id": str(j.video_id),
            "type": j.type,
            "status": j.status,
            "progress": j.progress,
            "logs": j.logs,
            "created_at": j.created_at.isoformat()
        }
        for j in jobs
    ]


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Cancel a pending or processing job
    
    Note: Jobs that are already processing may not stop immediately
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )
    
    # Verify user owns the video
    video = db.query(Video).filter(
        Video.id == job.video_id,
        Video.user_id == current_user.id
    ).first()
    
    if not video:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # Only allow cancellation of pending/processing jobs
    if job.status not in ['pending', 'processing']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel job with status: {job.status}"
        )
    
    # Update job status
    job.status = 'cancelled'
    job.logs = {**job.logs, 'cancelled_by': 'user', 'message': 'Job cancelled by user'}
    db.commit()
    
    # TODO: Send cancellation signal to Celery worker
    # from app.workers.celery_app import celery_app
    # celery_app.control.revoke(str(job.id), terminate=True)
    
    return None


@router.post("/jobs/{job_id}/retry", response_model=AnalyzeResponse)
async def retry_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Retry a failed job
    
    Creates a new job with the same parameters as the failed one
    """
    original_job = db.query(Job).filter(Job.id == job_id).first()
    
    if not original_job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )
    
    # Verify user owns the video
    video = db.query(Video).filter(
        Video.id == original_job.video_id,
        Video.user_id == current_user.id
    ).first()
    
    if not video:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # Only allow retry of failed jobs
    if original_job.status != 'failed':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot retry job with status: {original_job.status}"
        )
    
    # Create new job
    new_job = Job(
        video_id=original_job.video_id,
        type=original_job.type,
        status='pending',
        progress=0,
        logs={'retried_from': str(original_job.id)}
    )
    
    db.add(new_job)
    db.commit()
    db.refresh(new_job)
    
    # Extract config from original job logs
    config = original_job.logs.get('config', load_config())
    
    # Start task based on type
    if original_job.type == 'analyze':
        analyze_video_task.delay(
            job_id=str(new_job.id),
            video_id=str(original_job.video_id),
            config=config
        )
    
    return {
        "job_id": str(new_job.id),
        "video_id": str(original_job.video_id),
        "status": "pending",
        "message": "Job retried"
    }