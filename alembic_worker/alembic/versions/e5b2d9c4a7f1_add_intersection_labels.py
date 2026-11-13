"""add intersection labels to frames and an intersection filter to dataset exports

Sprint 3 ticket 3: label frames as signalized / unsignalized / non-intersection.

Revision ID: e5b2d9c4a7f1
Revises: d7f3b2e8a1c4
Create Date: 2026-11-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5b2d9c4a7f1'
down_revision: Union[str, Sequence[str], None] = 'd7f3b2e8a1c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('frames', sa.Column('intersection_type', sa.String(length=32), nullable=True))
    op.add_column('frames', sa.Column('intersection_details', sa.JSON(), nullable=True))
    op.create_index('ix_frames_route_intersection_type', 'frames', ['route_id', 'intersection_type'])
    op.add_column('dataset_exports', sa.Column('intersection_types', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('dataset_exports', 'intersection_types')
    op.drop_index('ix_frames_route_intersection_type', table_name='frames')
    op.drop_column('frames', 'intersection_details')
    op.drop_column('frames', 'intersection_type')
