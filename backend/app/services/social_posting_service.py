"""
Social Posting Service - Handles OAuth and posting to TikTok and Instagram.

Supports OAuth 2.0 flows for both platforms and video upload APIs.
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from pathlib import Path
import httpx

from app.config import get_config, SocialPostingConfig
from app.models import SocialAccount, ScheduledPost
from app.database import SessionLocal

logger = logging.getLogger(__name__)


@dataclass
class OAuthResult:
    """Result of an OAuth flow."""
    success: bool
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_at: Optional[datetime] = None
    account_name: Optional[str] = None
    account_id: Optional[str] = None
    error: Optional[str] = None


@dataclass
class PostResult:
    """Result of posting content to a platform."""
    success: bool
    post_id: Optional[str] = None
    post_url: Optional[str] = None
    error: Optional[str] = None


class TikTokClient:
    """Client for TikTok Content Posting API."""

    AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
    TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
    USER_INFO_URL = "https://open.tiktokapis.com/v2/user/info/"
    VIDEO_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
    VIDEO_UPLOAD_URL = "https://open.tiktokapis.com/v2/post/publish/inbox/video/upload/"
    PUBLISH_STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"

    def __init__(self):
        config = get_config().social_posting
        self.client_key = config.tiktok_client_key
        self.client_secret = config.tiktok_client_secret
        self.redirect_uri = config.tiktok_redirect_uri
        self.http_client = httpx.AsyncClient(timeout=60.0)

    def get_auth_url(self, state: str) -> str:
        """
        Generate TikTok OAuth authorization URL.

        Args:
            state: Random state string for CSRF protection

        Returns:
            Authorization URL to redirect user to
        """
        params = {
            "client_key": self.client_key,
            "scope": "user.info.basic,video.publish",
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "state": state,
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self.AUTH_URL}?{query}"

    async def exchange_code(self, code: str) -> OAuthResult:
        """
        Exchange authorization code for access token.

        Args:
            code: Authorization code from OAuth callback

        Returns:
            OAuthResult with tokens and user info
        """
        if not self.client_key or not self.client_secret:
            return OAuthResult(
                success=False,
                error="TikTok API credentials not configured",
            )

        try:
            response = await self.http_client.post(
                self.TOKEN_URL,
                data={
                    "client_key": self.client_key,
                    "client_secret": self.client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": self.redirect_uri,
                },
            )

            data = response.json()

            if "error" in data:
                return OAuthResult(
                    success=False,
                    error=data.get("error_description", data.get("error")),
                )

            access_token = data.get("access_token")
            refresh_token = data.get("refresh_token")
            expires_in = data.get("expires_in", 86400)
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

            # Get user info
            user_info = await self._get_user_info(access_token)

            return OAuthResult(
                success=True,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
                account_name=user_info.get("display_name"),
                account_id=user_info.get("open_id"),
            )

        except Exception as e:
            logger.error(f"TikTok code exchange failed: {e}")
            return OAuthResult(success=False, error=str(e))

    async def refresh_access_token(self, refresh_token: str) -> OAuthResult:
        """Refresh an expired access token."""
        try:
            response = await self.http_client.post(
                self.TOKEN_URL,
                data={
                    "client_key": self.client_key,
                    "client_secret": self.client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
            )

            data = response.json()

            if "error" in data:
                return OAuthResult(
                    success=False,
                    error=data.get("error_description", data.get("error")),
                )

            expires_in = data.get("expires_in", 86400)
            return OAuthResult(
                success=True,
                access_token=data.get("access_token"),
                refresh_token=data.get("refresh_token"),
                expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
            )

        except Exception as e:
            logger.error(f"TikTok token refresh failed: {e}")
            return OAuthResult(success=False, error=str(e))

    async def _get_user_info(self, access_token: str) -> Dict[str, Any]:
        """Get TikTok user profile info."""
        try:
            response = await self.http_client.get(
                self.USER_INFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                params={"fields": "open_id,display_name,avatar_url"},
            )
            data = response.json()
            return data.get("data", {}).get("user", {})
        except Exception as e:
            logger.error(f"Failed to get TikTok user info: {e}")
            return {}

    async def post_video(
        self,
        access_token: str,
        video_path: str,
        caption: str,
        privacy_level: str = "PUBLIC_TO_EVERYONE",
    ) -> PostResult:
        """
        Post a video to TikTok.

        Args:
            access_token: Valid access token
            video_path: Path to video file
            caption: Video caption/description
            privacy_level: PUBLIC_TO_EVERYONE, MUTUAL_FOLLOW_FRIENDS, SELF_ONLY

        Returns:
            PostResult with post ID and URL
        """
        try:
            # Check file exists and get size
            if not os.path.exists(video_path):
                return PostResult(success=False, error=f"Video file not found: {video_path}")

            file_size = os.path.getsize(video_path)

            # Step 1: Initialize upload
            init_response = await self.http_client.post(
                self.VIDEO_INIT_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "post_info": {
                        "title": caption[:150],  # TikTok limit
                        "privacy_level": privacy_level,
                        "disable_duet": False,
                        "disable_comment": False,
                        "disable_stitch": False,
                    },
                    "source_info": {
                        "source": "FILE_UPLOAD",
                        "video_size": file_size,
                        "chunk_size": file_size,
                        "total_chunk_count": 1,
                    },
                },
            )

            init_data = init_response.json()

            if "error" in init_data:
                return PostResult(
                    success=False,
                    error=init_data.get("error", {}).get("message", "Init failed"),
                )

            publish_id = init_data.get("data", {}).get("publish_id")
            upload_url = init_data.get("data", {}).get("upload_url")

            if not upload_url:
                return PostResult(success=False, error="No upload URL received")

            # Step 2: Upload video file
            with open(video_path, "rb") as f:
                video_data = f.read()

            upload_response = await self.http_client.put(
                upload_url,
                content=video_data,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Range": f"bytes 0-{file_size-1}/{file_size}",
                },
            )

            if upload_response.status_code not in [200, 201]:
                return PostResult(
                    success=False,
                    error=f"Upload failed: {upload_response.status_code}",
                )

            # Step 3: Check publish status
            await asyncio.sleep(5)  # Wait for processing

            status_response = await self.http_client.post(
                self.PUBLISH_STATUS_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"publish_id": publish_id},
            )

            status_data = status_response.json()
            status = status_data.get("data", {}).get("status")

            if status == "PUBLISH_COMPLETE":
                return PostResult(
                    success=True,
                    post_id=publish_id,
                    post_url=f"https://www.tiktok.com/@user/video/{publish_id}",
                )
            elif status == "FAILED":
                return PostResult(
                    success=False,
                    error=status_data.get("data", {}).get("fail_reason", "Publishing failed"),
                )
            else:
                # Still processing, return pending status
                return PostResult(
                    success=True,
                    post_id=publish_id,
                    post_url=None,  # Not yet available
                )

        except Exception as e:
            logger.error(f"TikTok video post failed: {e}")
            return PostResult(success=False, error=str(e))

    async def close(self):
        """Close the HTTP client."""
        await self.http_client.aclose()


class InstagramClient:
    """Client for Instagram Graph API (Business/Creator accounts)."""

    AUTH_URL = "https://api.instagram.com/oauth/authorize"
    TOKEN_URL = "https://api.instagram.com/oauth/access_token"
    LONG_LIVED_TOKEN_URL = "https://graph.instagram.com/access_token"
    GRAPH_URL = "https://graph.instagram.com/v18.0"

    def __init__(self):
        config = get_config().social_posting
        self.app_id = config.instagram_app_id
        self.app_secret = config.instagram_app_secret
        self.redirect_uri = config.instagram_redirect_uri
        self.http_client = httpx.AsyncClient(timeout=60.0)

    def get_auth_url(self, state: str) -> str:
        """
        Generate Instagram OAuth authorization URL.

        Args:
            state: Random state string for CSRF protection

        Returns:
            Authorization URL to redirect user to
        """
        params = {
            "client_id": self.app_id,
            "redirect_uri": self.redirect_uri,
            "scope": "instagram_basic,instagram_content_publish",
            "response_type": "code",
            "state": state,
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self.AUTH_URL}?{query}"

    async def exchange_code(self, code: str) -> OAuthResult:
        """
        Exchange authorization code for access token.

        Args:
            code: Authorization code from OAuth callback

        Returns:
            OAuthResult with tokens and user info
        """
        if not self.app_id or not self.app_secret:
            return OAuthResult(
                success=False,
                error="Instagram API credentials not configured",
            )

        try:
            # Get short-lived token
            response = await self.http_client.post(
                self.TOKEN_URL,
                data={
                    "client_id": self.app_id,
                    "client_secret": self.app_secret,
                    "grant_type": "authorization_code",
                    "redirect_uri": self.redirect_uri,
                    "code": code,
                },
            )

            data = response.json()

            if "error_type" in data:
                return OAuthResult(
                    success=False,
                    error=data.get("error_message", "Authorization failed"),
                )

            short_token = data.get("access_token")
            user_id = data.get("user_id")

            # Exchange for long-lived token (60 days)
            long_token_response = await self.http_client.get(
                self.LONG_LIVED_TOKEN_URL,
                params={
                    "grant_type": "ig_exchange_token",
                    "client_secret": self.app_secret,
                    "access_token": short_token,
                },
            )

            long_data = long_token_response.json()
            access_token = long_data.get("access_token", short_token)
            expires_in = long_data.get("expires_in", 5184000)  # 60 days default
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

            # Get user info
            user_info = await self._get_user_info(access_token, user_id)

            return OAuthResult(
                success=True,
                access_token=access_token,
                refresh_token=None,  # Instagram uses token refresh differently
                expires_at=expires_at,
                account_name=user_info.get("username"),
                account_id=str(user_id),
            )

        except Exception as e:
            logger.error(f"Instagram code exchange failed: {e}")
            return OAuthResult(success=False, error=str(e))

    async def refresh_access_token(self, access_token: str) -> OAuthResult:
        """Refresh a long-lived access token."""
        try:
            response = await self.http_client.get(
                f"{self.GRAPH_URL}/refresh_access_token",
                params={
                    "grant_type": "ig_refresh_token",
                    "access_token": access_token,
                },
            )

            data = response.json()

            if "error" in data:
                return OAuthResult(
                    success=False,
                    error=data.get("error", {}).get("message", "Refresh failed"),
                )

            expires_in = data.get("expires_in", 5184000)
            return OAuthResult(
                success=True,
                access_token=data.get("access_token"),
                expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
            )

        except Exception as e:
            logger.error(f"Instagram token refresh failed: {e}")
            return OAuthResult(success=False, error=str(e))

    async def _get_user_info(self, access_token: str, user_id: str) -> Dict[str, Any]:
        """Get Instagram user profile info."""
        try:
            response = await self.http_client.get(
                f"{self.GRAPH_URL}/{user_id}",
                params={
                    "fields": "id,username,account_type,media_count",
                    "access_token": access_token,
                },
            )
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get Instagram user info: {e}")
            return {}

    async def post_reel(
        self,
        access_token: str,
        user_id: str,
        video_url: str,
        caption: str,
    ) -> PostResult:
        """
        Post a Reel to Instagram.

        Note: Instagram requires the video to be accessible via public URL.
        For local files, you need to upload to a hosting service first.

        Args:
            access_token: Valid access token
            user_id: Instagram user ID
            video_url: Public URL to video file
            caption: Video caption

        Returns:
            PostResult with post ID and URL
        """
        try:
            # Step 1: Create media container
            container_response = await self.http_client.post(
                f"{self.GRAPH_URL}/{user_id}/media",
                params={
                    "media_type": "REELS",
                    "video_url": video_url,
                    "caption": caption,
                    "access_token": access_token,
                },
            )

            container_data = container_response.json()

            if "error" in container_data:
                return PostResult(
                    success=False,
                    error=container_data.get("error", {}).get("message", "Container creation failed"),
                )

            creation_id = container_data.get("id")

            # Step 2: Wait for video processing
            status = "IN_PROGRESS"
            attempts = 0
            max_attempts = 30  # 5 minutes max

            while status == "IN_PROGRESS" and attempts < max_attempts:
                await asyncio.sleep(10)
                attempts += 1

                status_response = await self.http_client.get(
                    f"{self.GRAPH_URL}/{creation_id}",
                    params={
                        "fields": "status_code",
                        "access_token": access_token,
                    },
                )

                status_data = status_response.json()
                status = status_data.get("status_code", "ERROR")

            if status != "FINISHED":
                return PostResult(
                    success=False,
                    error=f"Video processing failed: {status}",
                )

            # Step 3: Publish the container
            publish_response = await self.http_client.post(
                f"{self.GRAPH_URL}/{user_id}/media_publish",
                params={
                    "creation_id": creation_id,
                    "access_token": access_token,
                },
            )

            publish_data = publish_response.json()

            if "error" in publish_data:
                return PostResult(
                    success=False,
                    error=publish_data.get("error", {}).get("message", "Publishing failed"),
                )

            media_id = publish_data.get("id")

            return PostResult(
                success=True,
                post_id=media_id,
                post_url=f"https://www.instagram.com/reel/{media_id}/",
            )

        except Exception as e:
            logger.error(f"Instagram Reel post failed: {e}")
            return PostResult(success=False, error=str(e))

    async def close(self):
        """Close the HTTP client."""
        await self.http_client.aclose()


class SocialPostingService:
    """Main service for social media posting operations."""

    def __init__(self):
        self.config = get_config().social_posting
        self.tiktok_client = TikTokClient()
        self.instagram_client = InstagramClient()

    async def connect_tiktok(self, auth_code: str, user_id: str, db_session=None) -> SocialAccount:
        """
        Complete TikTok OAuth flow and save account.

        Args:
            auth_code: Authorization code from OAuth callback
            user_id: ID of the user connecting the account
            db_session: Optional database session

        Returns:
            SocialAccount object (persisted if db_session provided)
        """
        result = await self.tiktok_client.exchange_code(auth_code)

        if not result.success:
            raise ValueError(f"TikTok OAuth failed: {result.error}")

        account = SocialAccount(
            user_id=user_id,
            platform="tiktok",
            access_token=result.access_token,
            refresh_token=result.refresh_token,
            expires_at=result.expires_at,
            account_name=result.account_name,
            account_id=result.account_id,
            is_active=1,
        )

        if db_session:
            # Check for existing account and update or create
            existing = db_session.query(SocialAccount).filter(
                SocialAccount.user_id == user_id,
                SocialAccount.platform == "tiktok",
            ).first()

            if existing:
                existing.access_token = result.access_token
                existing.refresh_token = result.refresh_token
                existing.expires_at = result.expires_at
                existing.account_name = result.account_name
                existing.account_id = result.account_id
                existing.is_active = 1
                db_session.commit()
                return existing
            else:
                db_session.add(account)
                db_session.commit()

        return account

    async def connect_instagram(self, auth_code: str, user_id: str, db_session=None) -> SocialAccount:
        """
        Complete Instagram OAuth flow and save account.

        Args:
            auth_code: Authorization code from OAuth callback
            user_id: ID of the user connecting the account
            db_session: Optional database session

        Returns:
            SocialAccount object (persisted if db_session provided)
        """
        result = await self.instagram_client.exchange_code(auth_code)

        if not result.success:
            raise ValueError(f"Instagram OAuth failed: {result.error}")

        account = SocialAccount(
            user_id=user_id,
            platform="instagram",
            access_token=result.access_token,
            refresh_token=result.refresh_token,
            expires_at=result.expires_at,
            account_name=result.account_name,
            account_id=result.account_id,
            is_active=1,
        )

        if db_session:
            # Check for existing account and update or create
            existing = db_session.query(SocialAccount).filter(
                SocialAccount.user_id == user_id,
                SocialAccount.platform == "instagram",
            ).first()

            if existing:
                existing.access_token = result.access_token
                existing.refresh_token = result.refresh_token
                existing.expires_at = result.expires_at
                existing.account_name = result.account_name
                existing.account_id = result.account_id
                existing.is_active = 1
                db_session.commit()
                return existing
            else:
                db_session.add(account)
                db_session.commit()

        return account

    async def post_to_tiktok(
        self,
        account: SocialAccount,
        video_path: str,
        caption: str,
        db_session=None,
    ) -> PostResult:
        """
        Post a video to TikTok using a connected account.

        Args:
            account: SocialAccount with valid TikTok credentials
            video_path: Path to video file
            caption: Video caption

        Returns:
            PostResult
        """
        # Check if token needs refresh
        if account.expires_at and account.expires_at <= datetime.now(timezone.utc):
            if account.refresh_token:
                refresh_result = await self.tiktok_client.refresh_access_token(account.refresh_token)
                if refresh_result.success:
                    account.access_token = refresh_result.access_token
                    account.refresh_token = refresh_result.refresh_token
                    account.expires_at = refresh_result.expires_at
                    if db_session:
                        db_session.commit()
                else:
                    return PostResult(success=False, error="Token expired and refresh failed")
            else:
                return PostResult(success=False, error="Token expired")

        return await self.tiktok_client.post_video(
            access_token=account.access_token,
            video_path=video_path,
            caption=caption,
        )

    async def post_to_instagram(
        self,
        account: SocialAccount,
        video_url: str,
        caption: str,
        db_session=None,
    ) -> PostResult:
        """
        Post a Reel to Instagram using a connected account.

        Note: video_url must be a publicly accessible URL.

        Args:
            account: SocialAccount with valid Instagram credentials
            video_url: Public URL to video file
            caption: Video caption

        Returns:
            PostResult
        """
        # Check if token needs refresh
        if account.expires_at and account.expires_at <= datetime.now(timezone.utc):
            refresh_result = await self.instagram_client.refresh_access_token(account.access_token)
            if refresh_result.success:
                account.access_token = refresh_result.access_token
                account.expires_at = refresh_result.expires_at
                if db_session:
                    db_session.commit()
            else:
                return PostResult(success=False, error="Token expired and refresh failed")

        return await self.instagram_client.post_reel(
            access_token=account.access_token,
            user_id=account.account_id,
            video_url=video_url,
            caption=caption,
        )

    async def schedule_post(
        self,
        user_id: str,
        account_id: str,
        video_path: str,
        caption: str,
        hashtags: List[str],
        scheduled_time: datetime,
        db_session=None,
    ) -> ScheduledPost:
        """
        Schedule a post for later publishing.

        Args:
            user_id: User ID
            account_id: SocialAccount ID
            video_path: Path to video file
            caption: Video caption
            hashtags: List of hashtags
            scheduled_time: When to publish
            db_session: Optional database session

        Returns:
            ScheduledPost object
        """
        post = ScheduledPost(
            user_id=user_id,
            social_account_id=account_id,
            video_path=video_path,
            caption=caption,
            hashtags=hashtags,
            scheduled_time=scheduled_time,
            status="pending",
        )

        if db_session:
            db_session.add(post)
            db_session.commit()

        return post

    def get_auth_url(self, platform: str, state: str) -> str:
        """Get OAuth authorization URL for a platform."""
        if platform == "tiktok":
            return self.tiktok_client.get_auth_url(state)
        elif platform == "instagram":
            return self.instagram_client.get_auth_url(state)
        else:
            raise ValueError(f"Unsupported platform: {platform}")

    async def close(self):
        """Clean up resources."""
        await self.tiktok_client.close()
        await self.instagram_client.close()
