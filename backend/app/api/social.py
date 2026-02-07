"""
Social Media API Routes - OAuth, posting, and scheduled post management.

Provides endpoints for:
- OAuth authorization URLs and callbacks for TikTok/Instagram
- Listing/disconnecting connected accounts
- Posting clips to connected accounts
- Scheduling posts for later publishing
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone
import uuid
import secrets

from app.database import get_db
from app.models import User, SocialAccount, ScheduledPost
from app.api.auth import get_current_user
from app.services.social_posting_service import SocialPostingService


router = APIRouter(prefix="/social", tags=["social"])


# =============================================================================
# Pydantic Models
# =============================================================================


class AuthURLResponse(BaseModel):
    auth_url: str
    state: str


class OAuthCallbackRequest(BaseModel):
    code: str
    state: str


class SocialAccountResponse(BaseModel):
    id: str
    platform: str
    account_name: Optional[str]
    account_id: Optional[str]
    is_active: bool
    expires_at: Optional[str]
    created_at: str

    class Config:
        from_attributes = True


class PostRequest(BaseModel):
    video_path: str
    caption: str
    hashtags: List[str] = []


class PostResponse(BaseModel):
    success: bool
    post_id: Optional[str]
    post_url: Optional[str]
    error: Optional[str]


class SchedulePostRequest(BaseModel):
    account_id: str
    video_path: str
    caption: str
    hashtags: List[str] = []
    scheduled_time: str  # ISO 8601


class ScheduledPostResponse(BaseModel):
    id: str
    platform: str
    account_name: Optional[str]
    video_path: str
    caption: Optional[str]
    hashtags: list
    scheduled_time: str
    status: str
    posted_at: Optional[str]
    post_url: Optional[str]
    error_message: Optional[str]
    created_at: str

    class Config:
        from_attributes = True


# =============================================================================
# OAuth Endpoints
# =============================================================================


@router.get("/auth/{platform}", response_model=AuthURLResponse)
async def get_auth_url(
    platform: str,
    current_user: User = Depends(get_current_user),
):
    """
    Get OAuth authorization URL for a platform.

    Supported platforms: tiktok, instagram
    """
    if platform not in ("tiktok", "instagram"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported platform: {platform}. Use 'tiktok' or 'instagram'.",
        )

    state = secrets.token_urlsafe(32)
    service = SocialPostingService()
    auth_url = service.get_auth_url(platform, state)

    return AuthURLResponse(auth_url=auth_url, state=state)


@router.post("/auth/{platform}/callback", response_model=SocialAccountResponse)
async def oauth_callback(
    platform: str,
    request: OAuthCallbackRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Handle OAuth callback and connect a social account.

    The frontend should call this after receiving the OAuth redirect with
    the authorization code.
    """
    if platform not in ("tiktok", "instagram"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported platform: {platform}",
        )

    service = SocialPostingService()

    try:
        if platform == "tiktok":
            account = await service.connect_tiktok(
                auth_code=request.code,
                user_id=str(current_user.id),
                db_session=db,
            )
        else:
            account = await service.connect_instagram(
                auth_code=request.code,
                user_id=str(current_user.id),
                db_session=db,
            )

        return SocialAccountResponse(
            id=str(account.id),
            platform=account.platform,
            account_name=account.account_name,
            account_id=account.account_id,
            is_active=bool(account.is_active),
            expires_at=account.expires_at.isoformat() if account.expires_at else None,
            created_at=account.created_at.isoformat() if account.created_at else datetime.now(timezone.utc).isoformat(),
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"OAuth flow failed: {str(e)}",
        )
    finally:
        await service.close()


# =============================================================================
# Account Management
# =============================================================================


@router.get("/accounts", response_model=List[SocialAccountResponse])
async def list_accounts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all connected social media accounts."""
    accounts = db.query(SocialAccount).filter(
        SocialAccount.user_id == current_user.id,
    ).order_by(SocialAccount.created_at.desc()).all()

    return [
        SocialAccountResponse(
            id=str(a.id),
            platform=a.platform,
            account_name=a.account_name,
            account_id=a.account_id,
            is_active=bool(a.is_active),
            expires_at=a.expires_at.isoformat() if a.expires_at else None,
            created_at=a.created_at.isoformat() if a.created_at else "",
        )
        for a in accounts
    ]


@router.delete("/accounts/{account_id}")
async def disconnect_account(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Disconnect a social media account."""
    account = db.query(SocialAccount).filter(
        SocialAccount.id == account_id,
        SocialAccount.user_id == current_user.id,
    ).first()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    account.is_active = 0
    db.commit()

    return {"message": "Account disconnected", "account_id": account_id}


# =============================================================================
# Posting Endpoints
# =============================================================================


@router.post("/accounts/{account_id}/post", response_model=PostResponse)
async def post_to_account(
    account_id: str,
    request: PostRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Post a video to a connected social account.

    For TikTok: video_path should be a local file path.
    For Instagram: video_path should be a publicly accessible URL.
    """
    account = db.query(SocialAccount).filter(
        SocialAccount.id == account_id,
        SocialAccount.user_id == current_user.id,
        SocialAccount.is_active == 1,
    ).first()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active account not found",
        )

    caption = request.caption
    if request.hashtags:
        caption += "\n\n" + " ".join(f"#{tag}" for tag in request.hashtags)

    service = SocialPostingService()

    try:
        if account.platform == "tiktok":
            result = await service.post_to_tiktok(
                account=account,
                video_path=request.video_path,
                caption=caption,
                db_session=db,
            )
        elif account.platform == "instagram":
            result = await service.post_to_instagram(
                account=account,
                video_url=request.video_path,
                caption=caption,
                db_session=db,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported platform: {account.platform}",
            )

        return PostResponse(
            success=result.success,
            post_id=result.post_id,
            post_url=result.post_url,
            error=result.error,
        )

    finally:
        await service.close()


# =============================================================================
# Scheduled Posts
# =============================================================================


@router.post("/schedule", response_model=ScheduledPostResponse)
async def schedule_post(
    request: SchedulePostRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Schedule a post for later publishing.

    The post will be automatically published at the scheduled time
    by the background worker.
    """
    # Verify account belongs to user
    account = db.query(SocialAccount).filter(
        SocialAccount.id == request.account_id,
        SocialAccount.user_id == current_user.id,
        SocialAccount.is_active == 1,
    ).first()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active account not found",
        )

    try:
        scheduled_time = datetime.fromisoformat(request.scheduled_time)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid scheduled_time format. Use ISO 8601.",
        )

    if scheduled_time <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Scheduled time must be in the future.",
        )

    post = ScheduledPost(
        user_id=current_user.id,
        social_account_id=account.id,
        video_path=request.video_path,
        caption=request.caption,
        hashtags=request.hashtags,
        scheduled_time=scheduled_time,
        status="pending",
    )
    db.add(post)
    db.commit()
    db.refresh(post)

    return ScheduledPostResponse(
        id=str(post.id),
        platform=account.platform,
        account_name=account.account_name,
        video_path=post.video_path,
        caption=post.caption,
        hashtags=post.hashtags or [],
        scheduled_time=post.scheduled_time.isoformat(),
        status=post.status,
        posted_at=None,
        post_url=None,
        error_message=None,
        created_at=post.created_at.isoformat() if post.created_at else datetime.now(timezone.utc).isoformat(),
    )


@router.get("/schedule", response_model=List[ScheduledPostResponse])
async def list_scheduled_posts(
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List scheduled posts for the current user."""
    query = db.query(ScheduledPost).filter(
        ScheduledPost.user_id == current_user.id,
    )

    if status_filter:
        query = query.filter(ScheduledPost.status == status_filter)

    posts = query.order_by(ScheduledPost.scheduled_time.asc()).all()

    results = []
    for post in posts:
        account = db.query(SocialAccount).filter(
            SocialAccount.id == post.social_account_id,
        ).first()

        results.append(ScheduledPostResponse(
            id=str(post.id),
            platform=account.platform if account else "unknown",
            account_name=account.account_name if account else None,
            video_path=post.video_path,
            caption=post.caption,
            hashtags=post.hashtags or [],
            scheduled_time=post.scheduled_time.isoformat(),
            status=post.status,
            posted_at=post.posted_at.isoformat() if post.posted_at else None,
            post_url=post.post_url,
            error_message=post.error_message,
            created_at=post.created_at.isoformat() if post.created_at else "",
        ))

    return results


@router.delete("/schedule/{post_id}")
async def cancel_scheduled_post(
    post_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cancel a pending scheduled post."""
    post = db.query(ScheduledPost).filter(
        ScheduledPost.id == post_id,
        ScheduledPost.user_id == current_user.id,
    ).first()

    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scheduled post not found",
        )

    if post.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel post with status '{post.status}'",
        )

    db.delete(post)
    db.commit()

    return {"message": "Scheduled post cancelled", "post_id": post_id}
