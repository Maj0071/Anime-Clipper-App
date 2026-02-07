"""
Clip Discovery Service - Finds trending anime clips from multiple sources.

Supports YouTube, Reddit, and can be extended for Twitter, TikTok, Instagram.
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
import httpx
import cv2
import numpy as np
from io import BytesIO

from app.config import get_config, ClipDiscoveryConfig
from app.models import ClipSource, ClipSuggestion, DailySuggestion
from app.database import SessionLocal

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredClip:
    """Represents a clip discovered from a source."""
    external_id: str
    title: str
    description: str
    url: str
    thumbnail_url: Optional[str]
    anime_name: Optional[str]
    episode_info: Optional[str]
    duration: Optional[float]
    view_count: int
    platform: str


class YouTubeClient:
    """Client for YouTube Data API v3."""

    BASE_URL = "https://www.googleapis.com/youtube/v3"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or get_config().clip_discovery.youtube_api_key
        self.http_client = httpx.AsyncClient(timeout=30.0)

    async def search(
        self,
        query: str,
        max_results: int = 25,
        order: str = "relevance",
        video_definition: str = "high",
    ) -> List[DiscoveredClip]:
        """
        Search YouTube for videos matching the query.

        Args:
            query: Search terms
            max_results: Maximum number of results (up to 50)
            order: Sort order (relevance, viewCount, date, rating)
            video_definition: 'high' for HD only, 'any' for all

        Returns:
            List of discovered clips
        """
        if not self.api_key:
            logger.warning("YouTube API key not configured")
            return []

        try:
            params = {
                "key": self.api_key,
                "q": query,
                "part": "snippet",
                "type": "video",
                "maxResults": min(max_results, 50),
                "order": order,
                "videoDefinition": video_definition,
                "videoDuration": "short",  # Under 4 minutes
                "safeSearch": "none",
            }

            response = await self.http_client.get(
                f"{self.BASE_URL}/search",
                params=params,
            )
            response.raise_for_status()
            data = response.json()

            clips = []
            video_ids = []

            for item in data.get("items", []):
                video_id = item["id"]["videoId"]
                video_ids.append(video_id)
                snippet = item["snippet"]

                # Try to extract anime name from title
                anime_name = self._extract_anime_name(snippet["title"])

                clips.append(DiscoveredClip(
                    external_id=video_id,
                    title=snippet["title"],
                    description=snippet.get("description", ""),
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    thumbnail_url=snippet.get("thumbnails", {}).get("high", {}).get("url"),
                    anime_name=anime_name,
                    episode_info=None,
                    duration=None,  # Need separate API call
                    view_count=0,  # Need separate API call
                    platform="youtube",
                ))

            # Fetch video details for duration and view count
            if video_ids:
                details = await self._get_video_details(video_ids)
                for clip in clips:
                    if clip.external_id in details:
                        clip.duration = details[clip.external_id].get("duration")
                        clip.view_count = details[clip.external_id].get("view_count", 0)

            return clips

        except httpx.HTTPStatusError as e:
            logger.error(f"YouTube API error: {e.response.status_code} - {e.response.text}")
            return []
        except Exception as e:
            logger.error(f"YouTube search failed: {e}")
            return []

    async def _get_video_details(self, video_ids: List[str]) -> Dict[str, Dict]:
        """Get duration and view count for videos."""
        try:
            params = {
                "key": self.api_key,
                "id": ",".join(video_ids),
                "part": "contentDetails,statistics",
            }

            response = await self.http_client.get(
                f"{self.BASE_URL}/videos",
                params=params,
            )
            response.raise_for_status()
            data = response.json()

            details = {}
            for item in data.get("items", []):
                video_id = item["id"]
                duration = self._parse_duration(
                    item.get("contentDetails", {}).get("duration", "PT0S")
                )
                view_count = int(
                    item.get("statistics", {}).get("viewCount", 0)
                )
                details[video_id] = {
                    "duration": duration,
                    "view_count": view_count,
                }

            return details

        except Exception as e:
            logger.error(f"Failed to get video details: {e}")
            return {}

    def _parse_duration(self, duration_str: str) -> float:
        """Parse ISO 8601 duration to seconds."""
        # PT1H2M3S -> 3723 seconds
        match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration_str)
        if not match:
            return 0

        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)

        return hours * 3600 + minutes * 60 + seconds

    def _extract_anime_name(self, title: str) -> Optional[str]:
        """Try to extract anime name from video title."""
        # Common patterns:
        # "Naruto vs Sasuke - Epic Fight Scene"
        # "[4K] Attack on Titan Season 4 Ep 12"
        # "One Piece Episode 1000 - Best Moment"

        # Look for known patterns
        patterns = [
            r"^(.+?)\s*[-|]\s*(?:episode|ep|fight|scene|moment|amv)",
            r"^\[.+?\]\s*(.+?)\s*(?:season|ep|episode)",
            r"^(.+?)\s+(?:episode|ep)\s+\d+",
        ]

        title_lower = title.lower()
        for pattern in patterns:
            match = re.match(pattern, title_lower, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                # Clean up common prefixes/suffixes
                name = re.sub(r"^\[.*?\]\s*", "", name)
                name = re.sub(r"\s*\[.*?\]$", "", name)
                if len(name) > 2:
                    return name.title()

        return None

    async def close(self):
        """Close the HTTP client."""
        await self.http_client.aclose()


class RedditClient:
    """Client for Reddit API."""

    BASE_URL = "https://oauth.reddit.com"
    AUTH_URL = "https://www.reddit.com/api/v1/access_token"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        user_agent: Optional[str] = None,
    ):
        config = get_config().clip_discovery
        self.client_id = client_id or config.reddit_client_id
        self.client_secret = client_secret or config.reddit_client_secret
        self.user_agent = user_agent or config.reddit_user_agent
        self.http_client = httpx.AsyncClient(timeout=30.0)
        self._access_token: Optional[str] = None
        self._token_expires: Optional[datetime] = None

    async def _ensure_authenticated(self):
        """Ensure we have a valid access token."""
        if not self.client_id or not self.client_secret:
            return False

        now = datetime.now(timezone.utc)
        if self._access_token and self._token_expires and now < self._token_expires:
            return True

        try:
            auth = (self.client_id, self.client_secret)
            response = await self.http_client.post(
                self.AUTH_URL,
                auth=auth,
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": self.user_agent},
            )
            response.raise_for_status()
            data = response.json()

            self._access_token = data["access_token"]
            self._token_expires = now + timedelta(seconds=data["expires_in"] - 60)
            return True

        except Exception as e:
            logger.error(f"Reddit auth failed: {e}")
            return False

    async def search_subreddit(
        self,
        subreddit: str,
        sort: str = "hot",
        limit: int = 25,
        time_filter: str = "week",
    ) -> List[DiscoveredClip]:
        """
        Search a subreddit for video posts.

        Args:
            subreddit: Subreddit name (without r/)
            sort: Sort order (hot, new, top, rising)
            limit: Maximum posts to fetch
            time_filter: Time filter for top posts (hour, day, week, month, year, all)

        Returns:
            List of discovered clips
        """
        if not await self._ensure_authenticated():
            logger.warning("Reddit API not configured")
            return []

        try:
            headers = {
                "Authorization": f"Bearer {self._access_token}",
                "User-Agent": self.user_agent,
            }

            endpoint = f"{self.BASE_URL}/r/{subreddit}/{sort}"
            params = {"limit": limit}
            if sort == "top":
                params["t"] = time_filter

            response = await self.http_client.get(
                endpoint,
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            data = response.json()

            clips = []
            for post in data.get("data", {}).get("children", []):
                post_data = post.get("data", {})

                # Only interested in video content
                if not self._is_video_post(post_data):
                    continue

                video_url = self._extract_video_url(post_data)
                if not video_url:
                    continue

                clips.append(DiscoveredClip(
                    external_id=post_data["id"],
                    title=post_data["title"],
                    description=post_data.get("selftext", ""),
                    url=video_url,
                    thumbnail_url=post_data.get("thumbnail") if post_data.get("thumbnail", "").startswith("http") else None,
                    anime_name=self._extract_anime_from_flair(post_data),
                    episode_info=None,
                    duration=None,
                    view_count=post_data.get("ups", 0),  # Use upvotes as proxy
                    platform="reddit",
                ))

            return clips

        except httpx.HTTPStatusError as e:
            logger.error(f"Reddit API error: {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"Reddit search failed: {e}")
            return []

    def _is_video_post(self, post_data: dict) -> bool:
        """Check if a post contains video content."""
        # Reddit hosted video
        if post_data.get("is_video"):
            return True

        # External video links
        url = post_data.get("url", "")
        video_domains = ["youtube.com", "youtu.be", "v.redd.it", "streamable.com", "gfycat.com"]
        return any(domain in url for domain in video_domains)

    def _extract_video_url(self, post_data: dict) -> Optional[str]:
        """Extract the video URL from a post."""
        # Reddit hosted video
        if post_data.get("is_video"):
            media = post_data.get("media", {})
            reddit_video = media.get("reddit_video", {})
            fallback_url = reddit_video.get("fallback_url")
            if fallback_url:
                return fallback_url

        # External links
        url = post_data.get("url", "")
        if any(domain in url for domain in ["youtube.com", "youtu.be", "streamable.com"]):
            return url

        return None

    def _extract_anime_from_flair(self, post_data: dict) -> Optional[str]:
        """Try to extract anime name from post flair."""
        flair = post_data.get("link_flair_text", "")
        if flair and flair.lower() not in ["clip", "video", "media", "misc"]:
            return flair
        return None

    async def close(self):
        """Close the HTTP client."""
        await self.http_client.aclose()


class WatermarkDetector:
    """Detects watermarks in video thumbnails using CV analysis."""

    # Common watermark patterns (corner regions)
    CORNER_REGIONS = [
        (0, 0, 0.15, 0.15),      # Top-left
        (0.85, 0, 1.0, 0.15),    # Top-right
        (0, 0.85, 0.15, 1.0),    # Bottom-left
        (0.85, 0.85, 1.0, 1.0),  # Bottom-right
    ]

    @staticmethod
    async def detect_from_url(thumbnail_url: str) -> int:
        """
        Analyze a thumbnail for potential watermarks.

        Returns:
            0 = no watermark detected
            1 = watermark likely
            2 = unknown/error
        """
        if not thumbnail_url:
            return 2

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(thumbnail_url)
                response.raise_for_status()

                # Load image
                image_data = np.frombuffer(response.content, np.uint8)
                image = cv2.imdecode(image_data, cv2.IMREAD_COLOR)

                if image is None:
                    return 2

                return WatermarkDetector._analyze_corners(image)

        except Exception as e:
            logger.debug(f"Watermark detection failed: {e}")
            return 2

    @staticmethod
    def _analyze_corners(image: np.ndarray) -> int:
        """Analyze corner regions for watermark indicators."""
        height, width = image.shape[:2]

        for x1_pct, y1_pct, x2_pct, y2_pct in WatermarkDetector.CORNER_REGIONS:
            x1, y1 = int(width * x1_pct), int(height * y1_pct)
            x2, y2 = int(width * x2_pct), int(height * y2_pct)

            corner = image[y1:y2, x1:x2]

            # Check for text-like patterns (high contrast, edge density)
            gray = cv2.cvtColor(corner, cv2.COLOR_BGR2GRAY)
            edges = cv2.Canny(gray, 100, 200)
            edge_density = np.sum(edges > 0) / edges.size

            # Also check for semi-transparent overlays
            hsv = cv2.cvtColor(corner, cv2.COLOR_BGR2HSV)
            saturation = hsv[:, :, 1]
            low_sat_ratio = np.sum(saturation < 50) / saturation.size

            # Watermark indicators: high edge density + low saturation
            if edge_density > 0.15 and low_sat_ratio > 0.3:
                return 1

        return 0


class ClipDiscoveryService:
    """Main service for discovering and curating clips."""

    def __init__(self):
        self.config = get_config().clip_discovery
        self.youtube_client = YouTubeClient()
        self.reddit_client = RedditClient()
        self.watermark_detector = WatermarkDetector()

    async def discover_trending_clips(
        self,
        max_per_source: int = 25,
    ) -> List[ClipSuggestion]:
        """
        Discover trending clips from all configured sources.

        Returns:
            List of ClipSuggestion objects (not yet persisted)
        """
        all_clips: List[DiscoveredClip] = []

        # YouTube searches
        for search_term in self.config.youtube_search_terms:
            clips = await self.youtube_client.search(
                query=search_term,
                max_results=max_per_source,
                order="viewCount",
            )
            all_clips.extend(clips)
            await asyncio.sleep(0.1)  # Rate limit

        # Reddit searches
        for subreddit in self.config.reddit_subreddits:
            clips = await self.reddit_client.search_subreddit(
                subreddit=subreddit,
                sort="hot",
                limit=max_per_source,
            )
            all_clips.extend(clips)
            await asyncio.sleep(0.1)

        # Deduplicate by external_id
        seen_ids = set()
        unique_clips = []
        for clip in all_clips:
            if clip.external_id not in seen_ids:
                seen_ids.add(clip.external_id)
                unique_clips.append(clip)

        # Convert to ClipSuggestion objects with quality assessment
        suggestions = []
        for clip in unique_clips:
            quality_score = await self.assess_quality(clip)
            watermark = await self.watermark_detector.detect_from_url(clip.thumbnail_url)
            trending_score = self._calculate_trending_score(clip)

            suggestion = ClipSuggestion(
                external_id=clip.external_id,
                title=clip.title,
                description=clip.description,
                url=clip.url,
                thumbnail_url=clip.thumbnail_url,
                anime_name=clip.anime_name,
                episode_info=clip.episode_info,
                duration=clip.duration,
                view_count=clip.view_count,
                trending_score=trending_score,
                quality_score=quality_score,
                watermark_detected=watermark,
                status="active",
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            )
            suggestions.append(suggestion)

        # Sort by combined score
        suggestions.sort(
            key=lambda s: (s.trending_score * 0.6 + s.quality_score * 0.4),
            reverse=True,
        )

        return suggestions

    async def assess_quality(self, clip: DiscoveredClip) -> float:
        """
        Assess the quality of a discovered clip.

        Returns:
            Quality score from 0-100
        """
        score = 50.0  # Base score

        # Duration bonus (15-60 seconds is ideal for clips)
        if clip.duration:
            if 15 <= clip.duration <= 60:
                score += 20
            elif 60 < clip.duration <= 180:
                score += 10
            elif clip.duration > 180:
                score -= 10

        # Title quality (descriptive titles score higher)
        if clip.title:
            # Penalize clickbait patterns
            clickbait_patterns = ["you won't believe", "insane", "must watch", "!!!"]
            if any(p in clip.title.lower() for p in clickbait_patterns):
                score -= 10
            # Bonus for anime name in title
            if clip.anime_name:
                score += 10

        # Source quality
        if clip.platform == "youtube":
            score += 5  # Generally higher quality
        elif clip.platform == "reddit":
            score += 5  # Often curated content

        # Thumbnail presence
        if clip.thumbnail_url:
            score += 5

        return min(100, max(0, score))

    def _calculate_trending_score(self, clip: DiscoveredClip) -> float:
        """Calculate trending score based on engagement metrics."""
        score = 0.0

        # View count impact (logarithmic scale)
        if clip.view_count > 0:
            import math
            view_score = min(50, math.log10(clip.view_count) * 10)
            score += view_score

        # Platform-specific bonuses
        if clip.platform == "youtube" and clip.view_count > 100000:
            score += 20
        elif clip.platform == "reddit" and clip.view_count > 1000:  # Upvotes
            score += 20

        return min(100, score)

    async def curate_daily_suggestions(
        self,
        db_session=None,
    ) -> List[DailySuggestion]:
        """
        Pick the top suggestions for today's daily picks.

        Creates DailySuggestion entries for the current date.
        """
        if db_session is None:
            db_session = SessionLocal()
            should_close = True
        else:
            should_close = False

        try:
            today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

            # Check if we already have picks for today
            existing = db_session.query(DailySuggestion).filter(
                DailySuggestion.date == today
            ).first()

            if existing:
                logger.info("Daily suggestions already exist for today")
                return db_session.query(DailySuggestion).filter(
                    DailySuggestion.date == today
                ).all()

            # Get top active suggestions
            suggestions = db_session.query(ClipSuggestion).filter(
                ClipSuggestion.status == "active",
                ClipSuggestion.quality_score >= self.config.min_quality_score * 100,
            ).order_by(
                (ClipSuggestion.trending_score * 0.6 + ClipSuggestion.quality_score * 0.4).desc()
            ).limit(self.config.daily_suggestions_count * 3).all()

            # Categorize suggestions
            trending = [s for s in suggestions if s.trending_score >= 60]
            quality = [s for s in suggestions if s.quality_score >= 80]
            underrated = [s for s in suggestions if s.trending_score < 40 and s.quality_score >= 70]

            daily_picks = []
            position = 0

            # Add trending picks
            for suggestion in trending[:3]:
                daily_picks.append(DailySuggestion(
                    date=today,
                    suggestion_id=suggestion.id,
                    category="trending",
                    position=position,
                    is_featured=1 if position == 0 else 0,
                ))
                position += 1

            # Add classic/quality picks
            for suggestion in quality[:3]:
                if suggestion.id not in [d.suggestion_id for d in daily_picks]:
                    daily_picks.append(DailySuggestion(
                        date=today,
                        suggestion_id=suggestion.id,
                        category="classic",
                        position=position,
                    ))
                    position += 1

            # Add underrated picks
            for suggestion in underrated[:4]:
                if suggestion.id not in [d.suggestion_id for d in daily_picks]:
                    daily_picks.append(DailySuggestion(
                        date=today,
                        suggestion_id=suggestion.id,
                        category="underrated",
                        position=position,
                    ))
                    position += 1

            # Save to database
            for pick in daily_picks:
                db_session.add(pick)
            db_session.commit()

            logger.info(f"Created {len(daily_picks)} daily suggestions for {today}")
            return daily_picks

        except Exception as e:
            logger.error(f"Failed to curate daily suggestions: {e}")
            db_session.rollback()
            return []

        finally:
            if should_close:
                db_session.close()

    async def search_specific_anime(
        self,
        anime_name: str,
        max_results: int = 20,
    ) -> List[ClipSuggestion]:
        """
        Search for clips from a specific anime.
        """
        search_queries = [
            f"{anime_name} best scene",
            f"{anime_name} fight scene",
            f"{anime_name} epic moment",
        ]

        all_clips = []
        for query in search_queries:
            clips = await self.youtube_client.search(
                query=query,
                max_results=max_results // 3,
            )
            all_clips.extend(clips)

        # Convert to suggestions
        suggestions = []
        for clip in all_clips:
            clip.anime_name = anime_name  # Ensure anime name is set
            quality_score = await self.assess_quality(clip)
            trending_score = self._calculate_trending_score(clip)

            suggestion = ClipSuggestion(
                external_id=clip.external_id,
                title=clip.title,
                description=clip.description,
                url=clip.url,
                thumbnail_url=clip.thumbnail_url,
                anime_name=anime_name,
                duration=clip.duration,
                view_count=clip.view_count,
                trending_score=trending_score,
                quality_score=quality_score,
                status="active",
            )
            suggestions.append(suggestion)

        return suggestions

    async def close(self):
        """Clean up resources."""
        await self.youtube_client.close()
        await self.reddit_client.close()
