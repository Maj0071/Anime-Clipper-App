from sqlalchemy import Column, String, Float, Integer, ForeignKey, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
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
    logs = Column(JSONB, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    video = relationship("Video", back_populates="jobs")


class Transcript(Base):
    __tablename__ = "transcripts"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    video_id = Column(UUID(as_uuid=True), ForeignKey("videos.id"), nullable=False, index=True)
    lang = Column(String(10))
    words = Column(JSONB, nullable=False)  # Array of {word, start, end, confidence}
    
    video = relationship("Video", back_populates="transcripts")


class Candidate(Base):
    __tablename__ = "candidates"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    video_id = Column(UUID(as_uuid=True), ForeignKey("videos.id"), nullable=False, index=True)
    start_s = Column(Float, nullable=False)
    end_s = Column(Float, nullable=False)
    score = Column(Float, nullable=False, index=True)
    features = Column(JSONB, default={})  # Detailed scoring breakdown
    thumb_url = Column(Text)
    
    video = relationship("Video", back_populates="candidates")


class Render(Base):
    __tablename__ = "renders"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    params = Column(JSONB, nullable=False)  # candidate_ids, template, outputs, etc.
    status = Column(String(50), default='pending', index=True)
    files = Column(JSONB, default={})  # Output URLs by format
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    user = relationship("User", back_populates="renders")
