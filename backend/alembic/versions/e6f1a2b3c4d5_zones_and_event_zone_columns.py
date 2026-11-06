"""zones table + zone/clip columns on events (Phase 6)

Revision ID: e6f1a2b3c4d5
Revises: c7c48adc1ccd
Create Date: 2026-11-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6f1a2b3c4d5'
down_revision: Union[str, Sequence[str], None] = 'c7c48adc1ccd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('zones',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('video_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('x1', sa.Float(), nullable=False),
        sa.Column('y1', sa.Float(), nullable=False),
        sa.Column('x2', sa.Float(), nullable=False),
        sa.Column('y2', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['video_id'], ['videos.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_zones_video_id'), 'zones', ['video_id'], unique=False)
    op.add_column('events', sa.Column('zone_name', sa.String(length=255), nullable=True))
    op.add_column('events', sa.Column('track_id', sa.Integer(), nullable=True))
    op.add_column('events', sa.Column('label', sa.String(length=128), nullable=True))
    op.add_column('events', sa.Column('evidence_clip_start', sa.Float(), nullable=True))
    op.add_column('events', sa.Column('evidence_clip_end', sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('events', 'evidence_clip_end')
    op.drop_column('events', 'evidence_clip_start')
    op.drop_column('events', 'label')
    op.drop_column('events', 'track_id')
    op.drop_column('events', 'zone_name')
    op.drop_index(op.f('ix_zones_video_id'), table_name='zones')
    op.drop_table('zones')
