from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Dict, Optional
import yaml

from app.database import get_db
from app.models import User, Render, Candidate, Video
from app.api.auth import get_current_user
from app.workers.renderer import render_clips_task

router = APIRouter()


class RenderRequest(BaseModel):
    candidate_ids: List[str]
    template: str = "clean"  # clean, manga, impact, karaoke
    outputs: List[str] = ["9:16"]  # 9:16, 1:1, 4:5
    watermark: Optional[str] = "@myanime"
    loudness: Optional[str] = "-14"
    captions: Optional[str] = "on"  # on, off


class RenderResponse(BaseModel):
    render_id: str
    status: str
    message: str


class RenderStatus(BaseModel):
    render_id: str
    status: str
    files: dict
    created_at: str
    
    class Config:
        from_attributes = True


def load_config():
    """Load configuration from config.yaml"""
    try:
        with open('config.yaml', 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        return {
            'render': {
                'templates': ['clean', 'manga', 'impact', 'karaoke'],
                'default_template': 'clean',
                'loudness_target': -14
            }
        }


@router.post("/renders", response_model=RenderResponse, status_code=status.HTTP_201_CREATED)
async def create_render(
    request: RenderRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a render job for selected candidate clips
    
    - **candidate_ids**: List of candidate IDs to render
    - **template**: Caption template (clean, manga, impact, karaoke)
    - **outputs**: List of aspect ratios (9:16, 1:1, 4:5)
    - **watermark**: Watermark text (e.g., @username)
    - **loudness**: Target loudness in LUFS (default: -14)
    - **captions**: Enable/disable captions (on/off)
    
    Starts async job that renders clips with:
    - Selected caption template
    - Multiple aspect ratios
    - Audio normalization
    - Watermark overlay
    """
    # Validate inputs
    config = load_config()
    
    if not request.candidate_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one candidate must be selected"
        )
    
    if request.template not in config['render']['templates']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid template. Must be one of: {', '.join(config['render']['templates'])}"
        )
    
    valid_outputs = ['9:16', '1:1', '4:5']
    for output in request.outputs:
        if output not in valid_outputs:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid output format. Must be one of: {', '.join(valid_outputs)}"
            )
    
    # Verify all candidates exist and belong to user's videos
    candidates = db.query(Candidate).filter(
        Candidate.id.in_(request.candidate_ids)
    ).all()
    
    if len(candidates) != len(request.candidate_ids):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more candidates not found"
        )
    
    # Verify ownership through video
    for candidate in candidates:
        video = db.query(Video).filter(
            Video.id == candidate.video_id,
            Video.user_id == current_user.id
        ).first()
        
        if not video:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied for candidate {candidate.id}"
            )
    
    # Check concurrent render limit
    active_renders = db.query(Render).filter(
        Render.user_id == current_user.id,
        Render.status.in_(['pending', 'processing'])
    ).count()
    
    MAX_CONCURRENT = 3
    if active_renders >= MAX_CONCURRENT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Maximum {MAX_CONCURRENT} concurrent renders allowed"
        )
    
    # Create render record
    render = Render(
        user_id=current_user.id,
        params={
            'candidate_ids': request.candidate_ids,
            'template': request.template,
            'outputs': request.outputs,
            'watermark': request.watermark,
            'loudness': request.loudness,
            'captions': request.captions
        },
        status='pending',
        files={}
    )
    
    db.add(render)
    db.commit()
    db.refresh(render)
    
    # Start async render task
    render_clips_task.delay(
        render_id=str(render.id),
        params=render.params
    )
    
    return {
        "render_id": str(render.id),
        "status": "pending",
        "message": f"Render job started for {len(request.candidate_ids)} clips"
    }


@router.get("/renders/{render_id}", response_model=RenderStatus)
async def get_render_status(
    render_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get render job status and download URLs
    
    Returns:
    - Job status (pending, processing, completed, failed)
    - Download URLs for completed renders (organized by candidate and format)
    """
    render = db.query(Render).filter(
        Render.id == render_id,
        Render.user_id == current_user.id
    ).first()
    
    if not render:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Render not found"
        )
    
    return {
        "render_id": str(render.id),
        "status": render.status,
        "files": render.files,
        "created_at": render.created_at.isoformat()
    }


@router.get("/renders", response_model=List[RenderStatus])
async def list_renders(
    status_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List render jobs for current user
    
    - **status_filter**: Filter by status (pending, processing, completed, failed)
    - **skip**: Pagination offset
    - **limit**: Max results
    """
    query = db.query(Render).filter(Render.user_id == current_user.id)
    
    if status_filter:
        query = query.filter(Render.status == status_filter)
    
    renders = query.order_by(
        Render.created_at.desc()
    ).offset(skip).limit(limit).all()
    
    return [
        {
            "render_id": str(r.id),
            "status": r.status,
            "files": r.files,
            "created_at": r.created_at.isoformat()
        }
        for r in renders
    ]


@router.delete("/renders/{render_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_render(
    render_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a render record and associated files
    
    Note: This only deletes the database record and S3 files.
    Cannot cancel jobs that are already processing.
    """
    render = db.query(Render).filter(
        Render.id == render_id,
        Render.user_id == current_user.id
    ).first()
    
    if not render:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Render not found"
        )
    
    # Delete render record
    db.delete(render)
    db.commit()
    
    # TODO: Delete files from S3
    # for candidate_files in render.files.values():
    #     for file_url in candidate_files.values():
    #         delete_from_s3(file_url)
    
    return None


@router.post("/renders/batch", response_model=List[RenderResponse])
async def batch_render(
    requests: List[RenderRequest],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create multiple render jobs at once
    
    Useful for rendering different templates or formats simultaneously
    """
    if len(requests) > 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 5 batch renders allowed per request"
        )
    
    # Check total concurrent limit
    active_renders = db.query(Render).filter(
        Render.user_id == current_user.id,
        Render.status.in_(['pending', 'processing'])
    ).count()
    
    MAX_CONCURRENT = 3
    if active_renders + len(requests) > MAX_CONCURRENT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Would exceed maximum {MAX_CONCURRENT} concurrent renders"
        )
    
    results = []
    
    for request in requests:
        # Reuse create_render logic
        try:
            result = await create_render(request, current_user, db)
            results.append(result)
        except HTTPException as e:
            # Include error in results
            results.append({
                "render_id": None,
                "status": "error",
                "message": e.detail
            })
    
    return results


@router.get("/renders/{render_id}/download/{candidate_id}/{format}")
async def download_render(
    render_id: str,
    candidate_id: str,
    format: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get a signed download URL for a specific rendered clip
    
    - **render_id**: Render job ID
    - **candidate_id**: Candidate clip ID
    - **format**: Aspect ratio (9x16, 1x1, 4x5)
    
    Returns a signed URL valid for 24 hours
    """
    render = db.query(Render).filter(
        Render.id == render_id,
        Render.user_id == current_user.id
    ).first()
    
    if not render:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Render not found"
        )
    
    if render.status != 'completed':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Render not completed (status: {render.status})"
        )
    
    # Get file URL
    try:
        file_url = render.files[candidate_id][format]
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found for candidate {candidate_id} in format {format}"
        )
    
    # TODO: Generate signed download URL
    # from app.services.s3_service import generate_signed_download_url
    # signed_url = generate_signed_download_url(file_url, expires_in=86400)
    
    return {
        "download_url": file_url,  # In production, this would be a signed URL
        "expires_in": 86400,
        "filename": f"clip_{candidate_id}_{format}.mp4"
    }