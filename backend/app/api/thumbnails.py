"""
AI Thumbnail Generation API

Generates optimized thumbnails for clips with multiple style variations.
Extracts the best frame and adds optional text overlays.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Dict, List
import logging
import os
import subprocess
import json
import uuid

from app.database import get_db
from app.models import User, Candidate, Video, Thumbnail
from app.api.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()

THUMBNAIL_DIR = "/tmp/videos/thumbnails"
os.makedirs(THUMBNAIL_DIR, exist_ok=True)


# ══════════════════════════════════════════════════════════════════════
#  REQUEST/RESPONSE MODELS
# ══════════════════════════════════════════════════════════════════════

class GenerateThumbnailRequest(BaseModel):
    candidate_id: str
    styles: List[str] = ['default']  # 'default', 'text', 'border', 'vignette', 'neon', 'anime'
    text_overlay: Optional[str] = None
    auto_select_frame: bool = True  # Use AI to find best frame
    custom_frame_time: Optional[float] = None  # Override frame selection


class ThumbnailResponse(BaseModel):
    id: str
    candidate_id: str
    frame_time: float
    style: str
    text_overlay: Optional[str]
    image_url: str
    quality_score: float

    class Config:
        from_attributes = True


class GenerateThumbnailResponse(BaseModel):
    thumbnails: List[ThumbnailResponse]
    best_frame_time: float
    quality_analysis: Dict


# ══════════════════════════════════════════════════════════════════════
#  THUMBNAIL GENERATION ENGINE
# ══════════════════════════════════════════════════════════════════════

class ThumbnailGenerator:
    """
    Generates optimized thumbnails using FFmpeg and OpenCV.
    """

    def __init__(self, video_path: str):
        self.video_path = video_path

    def find_best_frame(self, start_s: float, end_s: float) -> Dict:
        """
        Find the best frame for thumbnail using multiple criteria:
        - Face presence (characters visible)
        - Sharpness (not blurry)
        - Color vibrancy
        - Action peak (interesting moment)

        Returns dict with frame_time and quality_score.
        """
        try:
            import cv2
            import numpy as np
        except ImportError:
            # Fallback: middle frame
            return {
                'frame_time': (start_s + end_s) / 2,
                'quality_score': 50.0,
                'analysis': {'method': 'fallback_middle'}
            }

        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            return {
                'frame_time': (start_s + end_s) / 2,
                'quality_score': 50.0,
                'analysis': {'method': 'fallback_error'}
            }

        fps = cap.get(cv2.CAP_PROP_FPS) or 24
        start_frame = int(start_s * fps)
        end_frame = int(end_s * fps)

        # Sample frames throughout the clip
        sample_count = min(20, end_frame - start_frame)
        sample_interval = max(1, (end_frame - start_frame) // sample_count)

        # Load face cascade
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )

        best_frame = None
        best_score = -1
        best_time = (start_s + end_s) / 2
        analysis = {}

        for i in range(sample_count):
            frame_idx = start_frame + (i * sample_interval)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret:
                continue

            current_time = start_s + (frame_idx - start_frame) / fps

            # Score this frame
            score = 0

            # 1. Face detection (50 points max)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=3, minSize=(30, 30)
            )
            face_score = min(50, len(faces) * 25)
            score += face_score

            # 2. Sharpness via Laplacian variance (25 points max)
            laplacian = cv2.Laplacian(gray, cv2.CV_64F)
            sharpness = laplacian.var()
            sharpness_score = min(25, sharpness / 100)
            score += sharpness_score

            # 3. Color vibrancy (25 points max)
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            saturation = np.mean(hsv[:, :, 1])
            vibrancy_score = min(25, saturation / 10)
            score += vibrancy_score

            if score > best_score:
                best_score = score
                best_time = current_time
                best_frame = frame.copy()
                analysis = {
                    'face_score': face_score,
                    'sharpness_score': sharpness_score,
                    'vibrancy_score': vibrancy_score,
                    'faces_detected': len(faces),
                    'sharpness_value': float(sharpness),
                    'saturation_value': float(saturation),
                }

        cap.release()

        return {
            'frame_time': best_time,
            'quality_score': min(100, best_score),
            'analysis': analysis,
        }

    def generate_thumbnail(self, frame_time: float, output_path: str,
                           style: str = 'default', text: str = None,
                           width: int = 1280, height: int = 720) -> bool:
        """
        Generate a thumbnail at the specified frame time.

        Styles:
        - default: Clean frame extraction
        - text: With text overlay
        - border: With stylized border
        - vignette: With vignette effect
        - neon: With neon glow effect
        - anime: Enhanced for anime (high saturation)
        """
        # Base extraction
        filters = [f'scale={width}:{height}:force_original_aspect_ratio=decrease']
        filters.append(f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black')

        # Style-specific filters
        if style == 'vignette':
            filters.append('vignette=PI/4')

        elif style == 'neon':
            filters.append('eq=saturation=1.5:contrast=1.3')
            filters.append('unsharp=5:5:1.5')

        elif style == 'anime':
            filters.append('eq=saturation=1.4:contrast=1.2:brightness=0.02')
            filters.append('unsharp=5:5:1.2')

        elif style == 'border':
            # Add white border
            border = 8
            filters.append(f'pad={width+border*2}:{height+border*2}:{border}:{border}:white')

        # Text overlay
        if text and style in ['text', 'default']:
            escaped = text.replace("'", "\\'").replace(":", "\\:")
            filters.append(
                f"drawtext=text='{escaped}':"
                f"fontfile=/System/Library/Fonts/Supplemental/Arial Bold.ttf:"
                f"fontsize=48:fontcolor=white:borderw=3:bordercolor=black:"
                f"x=(w-text_w)/2:y=h-60"
            )

        vf = ','.join(filters)

        cmd = [
            'ffmpeg', '-ss', str(frame_time),
            '-i', self.video_path,
            '-vframes', '1',
            '-vf', vf,
            '-y', output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode == 0

    def generate_variations(self, frame_time: float, styles: List[str],
                            text: str = None, output_dir: str = THUMBNAIL_DIR) -> List[Dict]:
        """Generate multiple style variations of a thumbnail."""
        results = []

        for style in styles:
            thumb_id = str(uuid.uuid4())[:8]
            filename = f"thumb_{thumb_id}_{style}.jpg"
            output_path = os.path.join(output_dir, filename)

            success = self.generate_thumbnail(
                frame_time, output_path,
                style=style,
                text=text if style == 'text' else None
            )

            if success:
                results.append({
                    'style': style,
                    'path': output_path,
                    'filename': filename,
                })

        return results


# ══════════════════════════════════════════════════════════════════════
#  API ENDPOINTS
# ══════════════════════════════════════════════════════════════════════

@router.post("", response_model=GenerateThumbnailResponse)
async def generate_thumbnails(
    request: GenerateThumbnailRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generate thumbnails for a clip.

    - **candidate_id**: The clip to generate thumbnails for
    - **styles**: List of styles to generate (default, text, border, vignette, neon, anime)
    - **text_overlay**: Optional text to add (used with 'text' style)
    - **auto_select_frame**: Use AI to find the best frame
    - **custom_frame_time**: Override with specific timestamp
    """
    import glob as glob_mod

    # Get candidate
    candidate = db.query(Candidate).filter(Candidate.id == request.candidate_id).first()
    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate not found"
        )

    # Get video
    video = db.query(Video).filter(
        Video.id == candidate.video_id,
        Video.user_id == current_user.id
    ).first()
    if not video:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    # Resolve video path
    video_path = None
    if video.src_url.startswith("file://"):
        local_src = video.src_url.replace("file://", "")
        if os.path.isfile(local_src):
            video_path = local_src
        else:
            matches = glob_mod.glob(f"/tmp/videos/{video.id}.*")
            if matches:
                video_path = matches[0]
    else:
        video_path = f"/tmp/videos/{video.id}.mp4"

    if not video_path or not os.path.exists(video_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video file not found"
        )

    # Initialize generator
    generator = ThumbnailGenerator(video_path)

    # Find best frame or use custom time
    if request.custom_frame_time is not None:
        frame_time = request.custom_frame_time
        quality_analysis = {'method': 'custom', 'quality_score': 50}
    elif request.auto_select_frame:
        result = generator.find_best_frame(candidate.start_s, candidate.end_s)
        frame_time = result['frame_time']
        quality_analysis = result['analysis']
    else:
        frame_time = (candidate.start_s + candidate.end_s) / 2
        quality_analysis = {'method': 'middle', 'quality_score': 50}

    # Generate variations
    variations = generator.generate_variations(
        frame_time,
        request.styles,
        request.text_overlay
    )

    if not variations:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate thumbnails"
        )

    # Save to database and build response
    thumbnails = []
    for var in variations:
        thumb = Thumbnail(
            candidate_id=str(candidate.id),
            frame_time=frame_time,
            style=var['style'],
            text_overlay=request.text_overlay if var['style'] == 'text' else None,
            image_url=f"/api/thumbnails/file/{var['filename']}",
            quality_score=quality_analysis.get('quality_score', 50) if 'quality_score' in quality_analysis else 50,
        )
        db.add(thumb)
        db.commit()
        db.refresh(thumb)

        thumbnails.append({
            'id': str(thumb.id),
            'candidate_id': str(thumb.candidate_id),
            'frame_time': thumb.frame_time,
            'style': thumb.style,
            'text_overlay': thumb.text_overlay,
            'image_url': thumb.image_url,
            'quality_score': thumb.quality_score or 50,
        })

    return {
        'thumbnails': thumbnails,
        'best_frame_time': frame_time,
        'quality_analysis': quality_analysis,
    }


@router.get("/{candidate_id}", response_model=List[ThumbnailResponse])
async def get_thumbnails(
    candidate_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all generated thumbnails for a candidate."""
    # Verify access
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate not found"
        )

    video = db.query(Video).filter(
        Video.id == candidate.video_id,
        Video.user_id == current_user.id
    ).first()
    if not video:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    thumbnails = db.query(Thumbnail).filter(
        Thumbnail.candidate_id == candidate_id
    ).order_by(Thumbnail.quality_score.desc()).all()

    return [
        {
            'id': str(t.id),
            'candidate_id': str(t.candidate_id),
            'frame_time': t.frame_time,
            'style': t.style,
            'text_overlay': t.text_overlay,
            'image_url': t.image_url,
            'quality_score': t.quality_score or 50,
        }
        for t in thumbnails
    ]


@router.get("/file/{filename}")
async def get_thumbnail_file(filename: str):
    """Serve a thumbnail file."""
    file_path = os.path.join(THUMBNAIL_DIR, filename)

    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thumbnail not found"
        )

    return FileResponse(file_path, media_type="image/jpeg")


@router.delete("/{thumbnail_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thumbnail(
    thumbnail_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a thumbnail."""
    thumbnail = db.query(Thumbnail).filter(Thumbnail.id == thumbnail_id).first()

    if not thumbnail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thumbnail not found"
        )

    # Verify ownership through candidate -> video
    candidate = db.query(Candidate).filter(Candidate.id == thumbnail.candidate_id).first()
    if candidate:
        video = db.query(Video).filter(
            Video.id == candidate.video_id,
            Video.user_id == current_user.id
        ).first()
        if not video:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )

    # Delete file
    if thumbnail.image_url:
        filename = thumbnail.image_url.split('/')[-1]
        file_path = os.path.join(THUMBNAIL_DIR, filename)
        if os.path.exists(file_path):
            os.remove(file_path)

    db.delete(thumbnail)
    db.commit()
    return None


@router.get("/styles/list")
async def list_thumbnail_styles(
    current_user: User = Depends(get_current_user)
):
    """Get available thumbnail styles with descriptions."""
    return {
        'styles': [
            {
                'id': 'default',
                'name': 'Default',
                'description': 'Clean frame extraction',
            },
            {
                'id': 'text',
                'name': 'With Text',
                'description': 'Add custom text overlay',
            },
            {
                'id': 'border',
                'name': 'Bordered',
                'description': 'White stylized border',
            },
            {
                'id': 'vignette',
                'name': 'Vignette',
                'description': 'Darkened edges for focus',
            },
            {
                'id': 'neon',
                'name': 'Neon',
                'description': 'High contrast neon glow',
            },
            {
                'id': 'anime',
                'name': 'Anime Enhanced',
                'description': 'Optimized for anime (vibrant colors)',
            },
        ]
    }
