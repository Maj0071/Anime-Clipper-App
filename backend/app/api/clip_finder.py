"""
Clip Finder API Routes - Browse and interact with clip suggestions.

Provides endpoints for:
- Listing suggestions with filtering
- Daily curated picks
- Downloading suggested clips
- User interactions (like, dismiss)
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone
import uuid

from app.database import get_db
from app.models import (
    User,
    ClipSource,
    ClipSuggestion,
    UserClipInteraction,
    DailySuggestion,
)
from app.api.auth import get_current_user
from app.services.clip_discovery_service import ClipDiscoveryService
from app.services.video_download_service import VideoDownloadService


router = APIRouter(prefix="/clips", tags=["clips"])


# =============================================================================
# Pydantic Models
# =============================================================================


class ClipSourceResponse(BaseModel):
    id: str
    platform: str
    name: str
    is_active: bool
    last_scraped: Optional[str]

    class Config:
        from_attributes = True


class ClipSuggestionResponse(BaseModel):
    id: str
    external_id: Optional[str]
    title: str
    description: Optional[str]
    url: str
    thumbnail_url: Optional[str]
    anime_name: Optional[str]
    episode_info: Optional[str]
    duration: Optional[float]
    view_count: int
    trending_score: float
    quality_score: float
    watermark_detected: int
    is_downloaded: bool
    status: str
    discovered_at: str
    source_platform: Optional[str] = None

    class Config:
        from_attributes = True


class SuggestionsListResponse(BaseModel):
    total: int
    suggestions: List[ClipSuggestionResponse]


class DailySuggestionResponse(BaseModel):
    id: str
    category: str
    position: int
    is_featured: bool
    suggestion: ClipSuggestionResponse


class DailyPicksResponse(BaseModel):
    date: str
    picks: List[DailySuggestionResponse]


class DownloadResponse(BaseModel):
    success: bool
    suggestion_id: str
    local_path: Optional[str]
    file_size: Optional[int]
    error: Optional[str]


class InteractionCreate(BaseModel):
    action: str  # 'liked', 'dismissed', 'downloaded', 'used'


class SearchRequest(BaseModel):
    anime_name: str
    max_results: int = 20


class TriggerDiscoveryRequest(BaseModel):
    max_per_source: int = 25


# =============================================================================
# Helper Functions
# =============================================================================


def suggestion_to_response(suggestion: ClipSuggestion) -> ClipSuggestionResponse:
    """Convert a ClipSuggestion model to response format."""
    source_platform = None
    if suggestion.source:
        source_platform = suggestion.source.platform

    return ClipSuggestionResponse(
        id=str(suggestion.id),
        external_id=suggestion.external_id,
        title=suggestion.title,
        description=suggestion.description,
        url=suggestion.url,
        thumbnail_url=suggestion.thumbnail_url,
        anime_name=suggestion.anime_name,
        episode_info=suggestion.episode_info,
        duration=suggestion.duration,
        view_count=suggestion.view_count or 0,
        trending_score=suggestion.trending_score or 0,
        quality_score=suggestion.quality_score or 0,
        watermark_detected=suggestion.watermark_detected or 0,
        is_downloaded=bool(suggestion.is_downloaded),
        status=suggestion.status or "active",
        discovered_at=suggestion.discovered_at.isoformat() if suggestion.discovered_at else "",
        source_platform=source_platform,
    )


# =============================================================================
# Suggestion Endpoints
# =============================================================================


@router.get("/suggestions", response_model=SuggestionsListResponse)
async def get_suggestions(
    category: Optional[str] = Query(None, description="Filter by category (trending, classic, underrated)"),
    anime_name: Optional[str] = Query(None, description="Filter by anime name"),
    min_quality: Optional[float] = Query(None, description="Minimum quality score (0-100)"),
    min_trending: Optional[float] = Query(None, description="Minimum trending score (0-100)"),
    hide_watermarked: bool = Query(False, description="Hide clips with detected watermarks"),
    status: Optional[str] = Query("active", description="Filter by status"),
    sort_by: str = Query("trending", description="Sort by: trending, quality, recent, views"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get clip suggestions with optional filtering.

    Filters:
    - category: trending, classic, underrated
    - anime_name: Filter by specific anime
    - min_quality/min_trending: Score thresholds
    - hide_watermarked: Exclude clips with detected watermarks
    - status: active, dismissed, used

    Sorting:
    - trending: By trending score (default)
    - quality: By quality score
    - recent: By discovery date
    - views: By view count
    """
    query = db.query(ClipSuggestion)

    # Apply filters
    if status:
        query = query.filter(ClipSuggestion.status == status)

    if anime_name:
        query = query.filter(ClipSuggestion.anime_name.ilike(f"%{anime_name}%"))

    if min_quality is not None:
        query = query.filter(ClipSuggestion.quality_score >= min_quality)

    if min_trending is not None:
        query = query.filter(ClipSuggestion.trending_score >= min_trending)

    if hide_watermarked:
        query = query.filter(ClipSuggestion.watermark_detected != 1)

    # Get user's dismissed suggestions to exclude
    dismissed_ids = db.query(UserClipInteraction.suggestion_id).filter(
        UserClipInteraction.user_id == current_user.id,
        UserClipInteraction.action == "dismissed",
    ).subquery()

    query = query.filter(~ClipSuggestion.id.in_(dismissed_ids))

    # Apply sorting
    if sort_by == "trending":
        query = query.order_by(ClipSuggestion.trending_score.desc())
    elif sort_by == "quality":
        query = query.order_by(ClipSuggestion.quality_score.desc())
    elif sort_by == "recent":
        query = query.order_by(ClipSuggestion.discovered_at.desc())
    elif sort_by == "views":
        query = query.order_by(ClipSuggestion.view_count.desc())
    else:
        query = query.order_by(
            (ClipSuggestion.trending_score * 0.6 + ClipSuggestion.quality_score * 0.4).desc()
        )

    # Get total count
    total = query.count()

    # Apply pagination
    suggestions = query.offset(skip).limit(limit).all()

    return SuggestionsListResponse(
        total=total,
        suggestions=[suggestion_to_response(s) for s in suggestions],
    )


@router.get("/daily", response_model=DailyPicksResponse)
async def get_daily_picks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get today's curated daily picks.

    Returns a selection of clips categorized as:
    - trending: High-performing viral clips
    - classic: Quality clips from popular anime
    - underrated: Hidden gems with good quality but lower visibility
    """
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    daily_picks = db.query(DailySuggestion).filter(
        DailySuggestion.date == today
    ).order_by(DailySuggestion.position).all()

    picks = []
    for pick in daily_picks:
        if pick.suggestion:
            picks.append(DailySuggestionResponse(
                id=str(pick.id),
                category=pick.category,
                position=pick.position,
                is_featured=bool(pick.is_featured),
                suggestion=suggestion_to_response(pick.suggestion),
            ))

    return DailyPicksResponse(
        date=today.isoformat(),
        picks=picks,
    )


@router.get("/suggestions/{suggestion_id}", response_model=ClipSuggestionResponse)
async def get_suggestion(
    suggestion_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get details for a specific suggestion."""
    suggestion = db.query(ClipSuggestion).filter(
        ClipSuggestion.id == suggestion_id
    ).first()

    if not suggestion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Suggestion not found",
        )

    return suggestion_to_response(suggestion)


# =============================================================================
# User Interaction Endpoints
# =============================================================================


@router.post("/suggestions/{suggestion_id}/download", response_model=DownloadResponse)
async def download_suggestion(
    suggestion_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Download a suggested clip.

    This will:
    1. Download the video using yt-dlp
    2. Store locally for editing
    3. Mark as downloaded in the database

    Returns immediately with task info; download happens in background.
    """
    suggestion = db.query(ClipSuggestion).filter(
        ClipSuggestion.id == suggestion_id
    ).first()

    if not suggestion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Suggestion not found",
        )

    if suggestion.is_downloaded and suggestion.local_path:
        return DownloadResponse(
            success=True,
            suggestion_id=str(suggestion.id),
            local_path=suggestion.local_path,
            file_size=None,
            error=None,
        )

    # Start download in background
    download_service = VideoDownloadService()

    async def download_task():
        result = await download_service.download_from_suggestion(
            suggestion_id=str(suggestion.id),
            url=suggestion.url,
            db_session=db,
        )
        if result.success:
            # Record interaction
            interaction = UserClipInteraction(
                user_id=current_user.id,
                suggestion_id=suggestion.id,
                action="downloaded",
            )
            db.add(interaction)
            db.commit()

    background_tasks.add_task(download_task)

    return DownloadResponse(
        success=True,
        suggestion_id=str(suggestion.id),
        local_path=None,  # Will be set after download completes
        file_size=None,
        error=None,
    )


@router.post("/suggestions/{suggestion_id}/like")
async def like_suggestion(
    suggestion_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Mark a suggestion as liked.

    Liked suggestions influence future recommendations.
    """
    suggestion = db.query(ClipSuggestion).filter(
        ClipSuggestion.id == suggestion_id
    ).first()

    if not suggestion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Suggestion not found",
        )

    # Check if already liked
    existing = db.query(UserClipInteraction).filter(
        UserClipInteraction.user_id == current_user.id,
        UserClipInteraction.suggestion_id == suggestion.id,
        UserClipInteraction.action == "liked",
    ).first()

    if existing:
        return {"message": "Already liked", "suggestion_id": suggestion_id}

    interaction = UserClipInteraction(
        user_id=current_user.id,
        suggestion_id=suggestion.id,
        action="liked",
    )
    db.add(interaction)
    db.commit()

    return {"message": "Liked", "suggestion_id": suggestion_id}


@router.post("/suggestions/{suggestion_id}/dismiss")
async def dismiss_suggestion(
    suggestion_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Mark a suggestion as dismissed.

    Dismissed suggestions won't appear in future listings for this user.
    """
    suggestion = db.query(ClipSuggestion).filter(
        ClipSuggestion.id == suggestion_id
    ).first()

    if not suggestion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Suggestion not found",
        )

    # Check if already dismissed
    existing = db.query(UserClipInteraction).filter(
        UserClipInteraction.user_id == current_user.id,
        UserClipInteraction.suggestion_id == suggestion.id,
        UserClipInteraction.action == "dismissed",
    ).first()

    if existing:
        return {"message": "Already dismissed", "suggestion_id": suggestion_id}

    interaction = UserClipInteraction(
        user_id=current_user.id,
        suggestion_id=suggestion.id,
        action="dismissed",
    )
    db.add(interaction)
    db.commit()

    return {"message": "Dismissed", "suggestion_id": suggestion_id}


@router.delete("/suggestions/{suggestion_id}/interactions")
async def clear_interactions(
    suggestion_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Clear all user interactions for a suggestion (undo like/dismiss)."""
    db.query(UserClipInteraction).filter(
        UserClipInteraction.user_id == current_user.id,
        UserClipInteraction.suggestion_id == suggestion_id,
    ).delete()
    db.commit()

    return {"message": "Interactions cleared", "suggestion_id": suggestion_id}


# =============================================================================
# Search and Discovery Endpoints
# =============================================================================


@router.post("/search", response_model=SuggestionsListResponse)
async def search_anime_clips(
    request: SearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Search for clips from a specific anime.

    This performs a new search using the discovery service and returns
    results without persisting them (unless explicitly downloaded).
    """
    discovery_service = ClipDiscoveryService()

    try:
        suggestions = await discovery_service.search_specific_anime(
            anime_name=request.anime_name,
            max_results=request.max_results,
        )

        # Convert to response format (these are not persisted yet)
        return SuggestionsListResponse(
            total=len(suggestions),
            suggestions=[
                ClipSuggestionResponse(
                    id=str(uuid.uuid4()),  # Temporary ID
                    external_id=s.external_id,
                    title=s.title,
                    description=s.description,
                    url=s.url,
                    thumbnail_url=s.thumbnail_url,
                    anime_name=s.anime_name,
                    episode_info=s.episode_info,
                    duration=s.duration,
                    view_count=s.view_count or 0,
                    trending_score=s.trending_score or 0,
                    quality_score=s.quality_score or 0,
                    watermark_detected=s.watermark_detected or 0,
                    is_downloaded=False,
                    status="search_result",
                    discovered_at=datetime.now(timezone.utc).isoformat(),
                    source_platform="youtube",
                )
                for s in suggestions
            ],
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {str(e)}",
        )

    finally:
        await discovery_service.close()


@router.post("/discover")
async def trigger_discovery(
    request: TriggerDiscoveryRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Manually trigger clip discovery.

    This will search all configured sources and add new suggestions.
    Normally this runs automatically via Celery every 6 hours.
    """
    async def run_discovery():
        discovery_service = ClipDiscoveryService()
        try:
            suggestions = await discovery_service.discover_trending_clips(
                max_per_source=request.max_per_source,
            )

            # Persist new suggestions
            for suggestion in suggestions:
                # Check if already exists
                existing = db.query(ClipSuggestion).filter(
                    ClipSuggestion.external_id == suggestion.external_id
                ).first()

                if not existing:
                    db.add(suggestion)

            db.commit()

        finally:
            await discovery_service.close()

    background_tasks.add_task(run_discovery)

    return {
        "message": "Discovery started",
        "max_per_source": request.max_per_source,
    }


# =============================================================================
# Source Management Endpoints
# =============================================================================


@router.get("/sources", response_model=List[ClipSourceResponse])
async def get_sources(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all configured clip sources."""
    sources = db.query(ClipSource).order_by(ClipSource.priority.desc()).all()

    return [
        ClipSourceResponse(
            id=str(s.id),
            platform=s.platform,
            name=s.name,
            is_active=bool(s.is_active),
            last_scraped=s.last_scraped.isoformat() if s.last_scraped else None,
        )
        for s in sources
    ]


@router.get("/stats")
async def get_clip_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get statistics about clip suggestions."""
    total = db.query(ClipSuggestion).count()
    active = db.query(ClipSuggestion).filter(ClipSuggestion.status == "active").count()
    downloaded = db.query(ClipSuggestion).filter(ClipSuggestion.is_downloaded == 1).count()

    user_likes = db.query(UserClipInteraction).filter(
        UserClipInteraction.user_id == current_user.id,
        UserClipInteraction.action == "liked",
    ).count()

    user_dismissed = db.query(UserClipInteraction).filter(
        UserClipInteraction.user_id == current_user.id,
        UserClipInteraction.action == "dismissed",
    ).count()

    return {
        "total_suggestions": total,
        "active_suggestions": active,
        "downloaded_clips": downloaded,
        "user_liked": user_likes,
        "user_dismissed": user_dismissed,
    }
