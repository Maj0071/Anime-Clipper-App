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
