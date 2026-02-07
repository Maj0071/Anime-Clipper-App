"""
Configuration module for Anime Clipper application.

Loads settings from environment variables with sensible defaults.
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class ClipDiscoveryConfig:
    """Configuration for clip discovery service."""
    youtube_api_key: Optional[str] = None
    reddit_client_id: Optional[str] = None
    reddit_client_secret: Optional[str] = None
    reddit_user_agent: str = "AnimeClipper/1.0"

    # Discovery settings
    discovery_interval_hours: int = 6
    daily_suggestions_count: int = 10
    min_quality_score: float = 0.7

    # Search configuration
    youtube_search_terms: list = None
    reddit_subreddits: list = None

    def __post_init__(self):
        if self.youtube_search_terms is None:
            self.youtube_search_terms = [
                "anime fight scene 4k",
                "anime epic moment",
                "anime best scene",
                "anime sakuga",
                "anime amv",
            ]
        if self.reddit_subreddits is None:
            self.reddit_subreddits = [
                "anime",
                "animeclips",
                "AnimeEdits",
                "animegifs",
            ]


@dataclass
class SocialPostingConfig:
    """Configuration for social media posting service."""
    tiktok_client_key: Optional[str] = None
    tiktok_client_secret: Optional[str] = None
    instagram_app_id: Optional[str] = None
    instagram_app_secret: Optional[str] = None

    # OAuth redirect URLs (set based on your deployment)
    tiktok_redirect_uri: str = "http://localhost:3000/auth/tiktok/callback"
    instagram_redirect_uri: str = "http://localhost:3000/auth/instagram/callback"


@dataclass
class AppConfig:
    """Main application configuration."""
    local_mode: bool = True
    test_mode: bool = True

    # Database
    database_url: str = "postgresql://clipper:clipper_dev_password@db:5432/anime_clipper"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # S3/MinIO
    s3_endpoint: str = "http://minio:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "anime-clips"

    # Auth
    jwt_secret: str = "dev_jwt_secret_change_in_production"

    # Sub-configurations
    clip_discovery: ClipDiscoveryConfig = None
    social_posting: SocialPostingConfig = None

    def __post_init__(self):
        if self.clip_discovery is None:
            self.clip_discovery = ClipDiscoveryConfig()
        if self.social_posting is None:
            self.social_posting = SocialPostingConfig()


def load_config() -> AppConfig:
    """Load configuration from environment variables."""
    clip_discovery = ClipDiscoveryConfig(
        youtube_api_key=os.getenv("YOUTUBE_API_KEY"),
        reddit_client_id=os.getenv("REDDIT_CLIENT_ID"),
        reddit_client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
        reddit_user_agent=os.getenv("REDDIT_USER_AGENT", "AnimeClipper/1.0"),
        discovery_interval_hours=int(os.getenv("CLIP_DISCOVERY_INTERVAL_HOURS", "6")),
        daily_suggestions_count=int(os.getenv("DAILY_SUGGESTIONS_COUNT", "10")),
        min_quality_score=float(os.getenv("MIN_QUALITY_SCORE", "0.7")),
    )

    social_posting = SocialPostingConfig(
        tiktok_client_key=os.getenv("TIKTOK_CLIENT_KEY"),
        tiktok_client_secret=os.getenv("TIKTOK_CLIENT_SECRET"),
        instagram_app_id=os.getenv("INSTAGRAM_APP_ID"),
        instagram_app_secret=os.getenv("INSTAGRAM_APP_SECRET"),
        tiktok_redirect_uri=os.getenv("TIKTOK_REDIRECT_URI", "http://localhost:3000/auth/tiktok/callback"),
        instagram_redirect_uri=os.getenv("INSTAGRAM_REDIRECT_URI", "http://localhost:3000/auth/instagram/callback"),
    )

    return AppConfig(
        local_mode=os.getenv("LOCAL_MODE", "true").lower() == "true",
        test_mode=os.getenv("TEST_MODE", "true").lower() == "true",
        database_url=os.getenv("DATABASE_URL", "postgresql://clipper:clipper_dev_password@db:5432/anime_clipper"),
        redis_url=os.getenv("REDIS_URL", "redis://redis:6379/0"),
        s3_endpoint=os.getenv("S3_ENDPOINT", "http://minio:9000"),
        s3_access_key=os.getenv("S3_ACCESS_KEY", "minioadmin"),
        s3_secret_key=os.getenv("S3_SECRET_KEY", "minioadmin"),
        s3_bucket=os.getenv("S3_BUCKET", "anime-clips"),
        jwt_secret=os.getenv("JWT_SECRET", "dev_jwt_secret_change_in_production"),
        clip_discovery=clip_discovery,
        social_posting=social_posting,
    )


# Global config instance (lazy loaded)
_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = load_config()
    return _config
