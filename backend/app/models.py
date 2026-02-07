from sqlalchemy import Column, String, Float, Integer, ForeignKey, DateTime, Text, JSON
from sqlalchemy.types import TypeDecorator, CHAR


class PortableUUID(TypeDecorator):
    """UUID type that works on both PostgreSQL and SQLite."""
    impl = CHAR(36)
    cache_ok = True

    def __init__(self, as_uuid=False):
        self.as_uuid = as_uuid
        super().__init__(length=36)

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import UUID as PG_UUID
            return dialect.type_descriptor(PG_UUID(as_uuid=self.as_uuid))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is not None:
            return str(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and self.as_uuid:
            import uuid as _uuid
            return _uuid.UUID(str(value))
        return value


UUID = PortableUUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.database import Base


class User(Base):
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    pw_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    videos = relationship("Video", back_populates="user")
    renders = relationship("Render", back_populates="user")


class Video(Base):
    __tablename__ = "videos"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(500))
    src_url = Column(Text, nullable=False)
    duration = Column(Float)
    resolution = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    user = relationship("User", back_populates="videos")
    jobs = relationship("Job", back_populates="video")
    transcripts = relationship("Transcript", back_populates="video")
    candidates = relationship("Candidate", back_populates="video")


class Job(Base):
    __tablename__ = "jobs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    video_id = Column(UUID(as_uuid=True), ForeignKey("videos.id"), nullable=False, index=True)
    type = Column(String(50), nullable=False)  # 'analyze' or 'render'
    status = Column(String(50), default='pending', index=True)  # pending, processing, completed, failed
    progress = Column(Integer, default=0)
    logs = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    video = relationship("Video", back_populates="jobs")


class Transcript(Base):
    __tablename__ = "transcripts"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    video_id = Column(UUID(as_uuid=True), ForeignKey("videos.id"), nullable=False, index=True)
    lang = Column(String(10))
    words = Column(JSON, nullable=False)  # Array of {word, start, end, confidence}
    
    video = relationship("Video", back_populates="transcripts")


class Candidate(Base):
    __tablename__ = "candidates"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    video_id = Column(UUID(as_uuid=True), ForeignKey("videos.id"), nullable=False, index=True)
    start_s = Column(Float, nullable=False)
    end_s = Column(Float, nullable=False)
    score = Column(Float, nullable=False, index=True)
    features = Column(JSON, default={})  # Detailed scoring breakdown
    thumb_url = Column(Text)
    
    video = relationship("Video", back_populates="candidates")


class Render(Base):
    __tablename__ = "renders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    params = Column(JSON, nullable=False)  # candidate_ids, template, outputs, etc.
    status = Column(String(50), default='pending', index=True)
    files = Column(JSON, default={})  # Output URLs by format
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="renders")


# ══════════════════════════════════════════════════════════════════════
#  LOW PRIORITY: Template Marketplace, Music Library, Thumbnails
# ══════════════════════════════════════════════════════════════════════

class EditTemplate(Base):
    """
    Custom editing template presets that can be saved and shared.

    Stores all effect settings for a complete editing style.
    """
    __tablename__ = "edit_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)  # NULL = system template
    name = Column(String(100), nullable=False)
    description = Column(Text)
    category = Column(String(50), index=True)  # 'velocity', 'flow', 'cinematic', 'custom'

    # Template settings (JSON blob with all effect params)
    settings = Column(JSON, nullable=False, default={})
    # Example settings structure:
    # {
    #   "base_template": "anime_hype",
    #   "enable_beat_sync": true,
    #   "effect_intensity": "high",
    #   "enable_smart_reframe": true,
    #   "caption_style": "pop",
    #   "hook_style": "bold",
    #   "color_grade": {...},
    #   "transitions": {...},
    # }

    # Community features
    is_public = Column(Integer, default=0)  # 0=private, 1=public
    downloads = Column(Integer, default=0)
    likes = Column(Integer, default=0)

    # Preview
    preview_url = Column(Text)  # URL to preview video/gif
    thumbnail_url = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", backref="templates")


class MusicTrack(Base):
    """
    Royalty-free music tracks for adding to clips.

    Categorized by mood/energy for auto-matching.
    """
    __tablename__ = "music_tracks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Track info
    title = Column(String(200), nullable=False)
    artist = Column(String(200))
    duration = Column(Float)  # seconds

    # File storage
    file_url = Column(Text, nullable=False)  # URL to audio file
    preview_url = Column(Text)  # Short preview clip

    # Categorization for mood matching
    mood = Column(String(50), index=True)  # 'hype', 'emotional', 'chill', 'dark', 'epic'
    energy = Column(Integer, default=50)  # 0-100 energy level
    genre = Column(String(50), index=True)  # 'phonk', 'electronic', 'orchestral', 'lofi', 'kpop'

    # Audio analysis data (for beat sync)
    bpm = Column(Integer)
    beats = Column(JSON, default=[])  # Array of beat timestamps

    # Usage tracking
    uses = Column(Integer, default=0)

    # License info
    license_type = Column(String(50), default='royalty_free')
    attribution = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Thumbnail(Base):
    """
    Generated thumbnails for clips.

    Stores multiple variations with different styles.
    """
    __tablename__ = "thumbnails"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id = Column(UUID(as_uuid=True), ForeignKey("candidates.id"), nullable=False, index=True)

    # Frame selection
    frame_time = Column(Float, nullable=False)  # Timestamp of extracted frame

    # Style info
    style = Column(String(50), default='default')  # 'default', 'text', 'border', 'vignette', 'neon'
    text_overlay = Column(String(200))  # Optional text on thumbnail

    # File URLs
    image_url = Column(Text, nullable=False)
    image_url_small = Column(Text)  # 320px thumbnail

    # Quality score (for auto-selection)
    quality_score = Column(Float, default=0)  # Based on clarity, faces, action

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    candidate = relationship("Candidate", backref="thumbnails")


# ══════════════════════════════════════════════════════════════════════
#  CLIP FINDER: Discovery, Social Posting, Scheduling
# ══════════════════════════════════════════════════════════════════════

class ClipSource(Base):
    """
    Tracks source platforms for clip discovery (YouTube, Reddit, etc.)
    """
    __tablename__ = "clip_sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform = Column(String(50), nullable=False, index=True)  # 'youtube', 'reddit', 'twitter', 'tiktok', 'instagram'
    name = Column(String(200), nullable=False)  # Display name for the source
    url = Column(Text)  # Base URL or subreddit/channel URL
    api_config = Column(JSON, default={})  # Platform-specific settings (search terms, filters)
    priority = Column(Integer, default=5)  # 1-10, higher = searched first
    is_active = Column(Integer, default=1)  # 0=disabled, 1=active
    last_scraped = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    suggestions = relationship("ClipSuggestion", back_populates="source")


class ClipSuggestion(Base):
    """
    Individual clip suggestions discovered from sources.
    """
    __tablename__ = "clip_suggestions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(UUID(as_uuid=True), ForeignKey("clip_sources.id"), nullable=True, index=True)
    external_id = Column(String(200), index=True)  # Platform-specific ID (video ID, post ID)

    # Content info
    title = Column(String(500), nullable=False)
    description = Column(Text)
    url = Column(Text, nullable=False)
    thumbnail_url = Column(Text)

    # Anime metadata
    anime_name = Column(String(200), index=True)
    episode_info = Column(String(100))  # "Episode 12" or "Movie"

    # Video properties
    duration = Column(Float)  # seconds
    view_count = Column(Integer, default=0)

    # Quality assessment
    trending_score = Column(Float, default=0, index=True)  # 0-100, based on engagement
    quality_score = Column(Float, default=0, index=True)  # 0-100, based on resolution/clarity
    watermark_detected = Column(Integer, default=0)  # 0=no, 1=yes, 2=unknown

    # Download tracking
    is_downloaded = Column(Integer, default=0)  # 0=no, 1=yes
    local_path = Column(Text)  # Path to downloaded file

    # Timestamps
    discovered_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True))  # When suggestion becomes stale

    # Status
    status = Column(String(50), default='active', index=True)  # 'active', 'dismissed', 'used', 'expired'

    source = relationship("ClipSource", back_populates="suggestions")
    interactions = relationship("UserClipInteraction", back_populates="suggestion")
    daily_features = relationship("DailySuggestion", back_populates="suggestion")


class UserClipInteraction(Base):
    """
    Track user interactions with clip suggestions for better recommendations.
    """
    __tablename__ = "user_clip_interactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    suggestion_id = Column(UUID(as_uuid=True), ForeignKey("clip_suggestions.id"), nullable=False, index=True)
    action = Column(String(50), nullable=False, index=True)  # 'liked', 'dismissed', 'downloaded', 'used'
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", backref="clip_interactions")
    suggestion = relationship("ClipSuggestion", back_populates="interactions")


class SocialAccount(Base):
    """
    OAuth tokens for connected social media accounts (TikTok, Instagram).
    """
    __tablename__ = "social_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    platform = Column(String(50), nullable=False, index=True)  # 'tiktok', 'instagram'

    # OAuth tokens
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text)
    expires_at = Column(DateTime(timezone=True))

    # Account info
    account_name = Column(String(200))  # Display name / username
    account_id = Column(String(200))  # Platform's user ID

    is_active = Column(Integer, default=1)  # 0=disconnected, 1=active
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", backref="social_accounts")
    scheduled_posts = relationship("ScheduledPost", back_populates="social_account")


class ScheduledPost(Base):
    """
    Posts queued for publishing to social media platforms.
    """
    __tablename__ = "scheduled_posts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    social_account_id = Column(UUID(as_uuid=True), ForeignKey("social_accounts.id"), nullable=False, index=True)

    # Content
    video_path = Column(Text, nullable=False)  # Local path or URL to video
    caption = Column(Text)
    hashtags = Column(JSON, default=[])  # Array of hashtag strings

    # Scheduling
    scheduled_time = Column(DateTime(timezone=True), nullable=False, index=True)

    # Status tracking
    status = Column(String(50), default='pending', index=True)  # 'pending', 'posted', 'failed'
    posted_at = Column(DateTime(timezone=True))
    error_message = Column(Text)

    # Platform response
    post_id = Column(String(200))  # ID of the created post on the platform
    post_url = Column(Text)  # URL to view the post

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", backref="scheduled_posts")
    social_account = relationship("SocialAccount", back_populates="scheduled_posts")


class DailySuggestion(Base):
    """
    Curated daily picks from clip suggestions.
    """
    __tablename__ = "daily_suggestions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date = Column(DateTime(timezone=True), nullable=False, index=True)  # Date for this pick
    suggestion_id = Column(UUID(as_uuid=True), ForeignKey("clip_suggestions.id"), nullable=False, index=True)
    category = Column(String(50), nullable=False, index=True)  # 'trending', 'classic', 'underrated'
    position = Column(Integer, default=0)  # Order within the day's picks
    is_featured = Column(Integer, default=0)  # 0=no, 1=yes (highlight pick)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    suggestion = relationship("ClipSuggestion", back_populates="daily_features")
