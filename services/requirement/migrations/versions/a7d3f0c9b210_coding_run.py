"""coding: coding_run table

Revision ID: a7d3f0c9b210
Revises: 3b941c3aef6c
Create Date: 2026-07-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7d3f0c9b210'
down_revision: Union[str, None] = '3b941c3aef6c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'coding_run',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('requirement_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
        sa.Column('repo', sa.String(length=512), nullable=False),
        sa.Column('branch', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('mr_url', sa.String(length=512), nullable=True),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('error', sa.Text(), nullable=False),
        sa.Column('created_by', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['requirement_id'], ['requirement.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_coding_run_requirement_id'), 'coding_run', ['requirement_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_coding_run_requirement_id'), table_name='coding_run')
    op.drop_table('coding_run')
