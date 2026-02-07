"""Add clip finder, social posting, templates, music, thumbnails tables

Revision ID: 002
Revises: 001
Create Date: 2025-01-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade():
    # --- Edit Templates ---
    op.create_table(
        'edit_templates',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('category', sa.String(50)),
        sa.Column('settings', sa.JSON, nullable=False, server_default='{}'),
        sa.Column('is_public', sa.Integer, server_default='0'),
        sa.Column('downloads', sa.Integer, server_default='0'),
        sa.Column('likes', sa.Integer, server_default='0'),
        sa.Column('preview_url', sa.Text),
        sa.Column('thumbnail_url', sa.Text),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_edit_templates_user_id', 'edit_templates', ['user_id'])
    op.create_index('ix_edit_templates_category', 'edit_templates', ['category'])

    # --- Music Tracks ---
    op.create_table(
        'music_tracks',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('artist', sa.String(200)),
        sa.Column('duration', sa.Float),
        sa.Column('file_url', sa.Text, nullable=False),
        sa.Column('preview_url', sa.Text),
        sa.Column('mood', sa.String(50)),
        sa.Column('energy', sa.Integer, server_default='50'),
        sa.Column('genre', sa.String(50)),
        sa.Column('bpm', sa.Integer),
        sa.Column('beats', sa.JSON, server_default='[]'),
        sa.Column('uses', sa.Integer, server_default='0'),
        sa.Column('license_type', sa.String(50), server_default="'royalty_free'"),
        sa.Column('attribution', sa.Text),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_music_tracks_mood', 'music_tracks', ['mood'])
    op.create_index('ix_music_tracks_genre', 'music_tracks', ['genre'])

    # --- Thumbnails ---
    op.create_table(
        'thumbnails',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('candidate_id', sa.String(36), sa.ForeignKey('candidates.id', ondelete='CASCADE'), nullable=False),
        sa.Column('frame_time', sa.Float, nullable=False),
        sa.Column('style', sa.String(50), server_default="'default'"),
        sa.Column('text_overlay', sa.String(200)),
        sa.Column('image_url', sa.Text, nullable=False),
        sa.Column('image_url_small', sa.Text),
        sa.Column('quality_score', sa.Float, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_thumbnails_candidate_id', 'thumbnails', ['candidate_id'])

    # --- Clip Sources ---
    op.create_table(
        'clip_sources',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('platform', sa.String(50), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('url', sa.Text),
        sa.Column('api_config', sa.JSON, server_default='{}'),
        sa.Column('priority', sa.Integer, server_default='5'),
        sa.Column('is_active', sa.Integer, server_default='1'),
        sa.Column('last_scraped', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_clip_sources_platform', 'clip_sources', ['platform'])

    # --- Clip Suggestions ---
    op.create_table(
        'clip_suggestions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('source_id', sa.String(36), sa.ForeignKey('clip_sources.id', ondelete='SET NULL'), nullable=True),
        sa.Column('external_id', sa.String(200)),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('url', sa.Text, nullable=False),
        sa.Column('thumbnail_url', sa.Text),
        sa.Column('anime_name', sa.String(200)),
        sa.Column('episode_info', sa.String(100)),
        sa.Column('duration', sa.Float),
        sa.Column('view_count', sa.Integer, server_default='0'),
        sa.Column('trending_score', sa.Float, server_default='0'),
        sa.Column('quality_score', sa.Float, server_default='0'),
        sa.Column('watermark_detected', sa.Integer, server_default='0'),
        sa.Column('is_downloaded', sa.Integer, server_default='0'),
        sa.Column('local_path', sa.Text),
        sa.Column('discovered_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(timezone=True)),
        sa.Column('status', sa.String(50), server_default="'active'"),
    )
    op.create_index('ix_clip_suggestions_source_id', 'clip_suggestions', ['source_id'])
    op.create_index('ix_clip_suggestions_external_id', 'clip_suggestions', ['external_id'])
    op.create_index('ix_clip_suggestions_anime_name', 'clip_suggestions', ['anime_name'])
    op.create_index('ix_clip_suggestions_trending_score', 'clip_suggestions', ['trending_score'])
    op.create_index('ix_clip_suggestions_quality_score', 'clip_suggestions', ['quality_score'])
    op.create_index('ix_clip_suggestions_status', 'clip_suggestions', ['status'])

    # --- User Clip Interactions ---
    op.create_table(
        'user_clip_interactions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('suggestion_id', sa.String(36), sa.ForeignKey('clip_suggestions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_user_clip_interactions_user_id', 'user_clip_interactions', ['user_id'])
    op.create_index('ix_user_clip_interactions_suggestion_id', 'user_clip_interactions', ['suggestion_id'])
    op.create_index('ix_user_clip_interactions_action', 'user_clip_interactions', ['action'])

    # --- Social Accounts ---
    op.create_table(
        'social_accounts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('platform', sa.String(50), nullable=False),
        sa.Column('access_token', sa.Text, nullable=False),
        sa.Column('refresh_token', sa.Text),
        sa.Column('expires_at', sa.DateTime(timezone=True)),
        sa.Column('account_name', sa.String(200)),
        sa.Column('account_id', sa.String(200)),
        sa.Column('is_active', sa.Integer, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_social_accounts_user_id', 'social_accounts', ['user_id'])
    op.create_index('ix_social_accounts_platform', 'social_accounts', ['platform'])

    # --- Scheduled Posts ---
    op.create_table(
        'scheduled_posts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('social_account_id', sa.String(36), sa.ForeignKey('social_accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('video_path', sa.Text, nullable=False),
        sa.Column('caption', sa.Text),
        sa.Column('hashtags', sa.JSON, server_default='[]'),
        sa.Column('scheduled_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(50), server_default="'pending'"),
        sa.Column('posted_at', sa.DateTime(timezone=True)),
        sa.Column('error_message', sa.Text),
        sa.Column('post_id', sa.String(200)),
        sa.Column('post_url', sa.Text),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_scheduled_posts_user_id', 'scheduled_posts', ['user_id'])
    op.create_index('ix_scheduled_posts_social_account_id', 'scheduled_posts', ['social_account_id'])
    op.create_index('ix_scheduled_posts_scheduled_time', 'scheduled_posts', ['scheduled_time'])
    op.create_index('ix_scheduled_posts_status', 'scheduled_posts', ['status'])

    # --- Daily Suggestions ---
    op.create_table(
        'daily_suggestions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('suggestion_id', sa.String(36), sa.ForeignKey('clip_suggestions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('category', sa.String(50), nullable=False),
        sa.Column('position', sa.Integer, server_default='0'),
        sa.Column('is_featured', sa.Integer, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_daily_suggestions_date', 'daily_suggestions', ['date'])
    op.create_index('ix_daily_suggestions_suggestion_id', 'daily_suggestions', ['suggestion_id'])
    op.create_index('ix_daily_suggestions_category', 'daily_suggestions', ['category'])


def downgrade():
    op.drop_table('daily_suggestions')
    op.drop_table('scheduled_posts')
    op.drop_table('social_accounts')
    op.drop_table('user_clip_interactions')
    op.drop_table('clip_suggestions')
    op.drop_table('clip_sources')
    op.drop_table('thumbnails')
    op.drop_table('music_tracks')
    op.drop_table('edit_templates')
