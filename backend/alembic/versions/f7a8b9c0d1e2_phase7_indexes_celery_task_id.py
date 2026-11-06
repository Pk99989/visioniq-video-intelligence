"""Composite time-ordered indexes + ProcessingJob.celery_task_id (Phase 7)

Revision ID: f7a8b9c0d1e2
Revises: e6f1a2b3c4d5
Create Date: 2026-11-06

The read paths order captions/detections/frames by
(video_id, timestamp_seconds) — single-column video_id indexes do
not serve that ordering, so these composites are the ones the
planner actually uses. celery_task_id (M10) lets a stuck job be
reconciled against the Celery result backend.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7a8b9c0d1e2'
down_revision: Union[str, Sequence[str], None] = 'e6f1a2b3c4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index('ix_captions_video_id_timestamp_seconds', 'captions',
                    ['video_id', 'timestamp_seconds'], unique=False)
    op.create_index('ix_detections_video_id_timestamp_seconds', 'detections',
                    ['video_id', 'timestamp_seconds'], unique=False)
    op.create_index('ix_frames_video_id_timestamp_seconds', 'frames',
                    ['video_id', 'timestamp_seconds'], unique=False)
    op.add_column('processing_jobs',
                  sa.Column('celery_task_id', sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('processing_jobs', 'celery_task_id')
    op.drop_index('ix_frames_video_id_timestamp_seconds', table_name='frames')
    op.drop_index('ix_detections_video_id_timestamp_seconds', table_name='detections')
    op.drop_index('ix_captions_video_id_timestamp_seconds', table_name='captions')
