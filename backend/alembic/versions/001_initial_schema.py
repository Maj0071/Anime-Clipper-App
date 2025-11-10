"""Initial schema

Revision ID: 001
Revises: 
Create Date: 2025-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('email', sa.String(255), unique=True, nullable=False),
        sa.Column('pw_hash', sa.String(255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now())
    )
    op.create_index('ix_users_email', 'users', ['email'])

    # Create videos table
    op.create_table(
        'videos',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('title', sa.String(500)),
        sa.Column('src_url', sa.Text, nullable=False),
        sa.Column('duration', sa.Float),
        sa.Column('resolution', sa.String(50)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE')
    )
    op.create_index('ix_videos_user_id', 'videos', ['user_id'])

    # Create jobs table
    op.create_table(
        'jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('video_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('type', sa.String(50), nullable=False),
        sa.Column('status', sa.String(50), default='pending'),
        sa.Column('progress', sa.Integer, default=0),
        sa.Column('logs', postgresql.JSONB, default={}),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['video_id'], ['videos.id'], ondelete='CASCADE')
    )
    op.create_index('ix_jobs_video_id', 'jobs', ['video_id'])
    op.create_index('ix_jobs_status', 'jobs', ['status'])

    # Create transcripts table
    op.create_table(
        'transcripts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('video_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('lang', sa.String(10)),
        sa.Column('words', postgresql.JSONB, nullable=False),
        sa.ForeignKeyConstraint(['video_id'], ['videos.id'], ondelete='CASCADE')
    )
    op.create_index('ix_transcripts_video_id', 'transcripts', ['video_id'])

    # Create candidates table
    op.create_table(
        'candidates',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('video_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('start_s', sa.Float, nullable=False),
        sa.Column('end_s', sa.Float, nullable=False),
        sa.Column('score', sa.Float, nullable=False),
        sa.Column('features', postgresql.JSONB, default={}),
        sa.Column('thumb_url', sa.Text),
        sa.ForeignKeyConstraint(['video_id'], ['videos.id'], ondelete='CASCADE')
    )
    op.create_index('ix_candidates_video_id', 'candidates', ['video_id'])
    op.create_index('ix_candidates_score', 'candidates', ['score'])

    # Create renders table
    op.create_table(
        'renders',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('params', postgresql.JSONB, nullable=False),
        sa.Column('status', sa.String(50), default='pending'),
        sa.Column('files', postgresql.JSONB, default={}),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE')
    )
    op.create_index('ix_renders_user_id', 'renders', ['user_id'])
    op.create_index('ix_renders_status', 'renders', ['status'])


def downgrade():
    op.drop_table('renders')
    op.drop_table('candidates')
    op.drop_table('transcripts')
    op.drop_table('jobs')
    op.drop_table('videos')
    op.drop_table('users')
