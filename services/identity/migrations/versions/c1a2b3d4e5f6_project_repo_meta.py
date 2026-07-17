"""project: repo_meta (name -> git_url/default_branch)

Revision ID: c1a2b3d4e5f6
Revises: b89da7c4730a
Create Date: 2026-07-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, None] = 'b89da7c4730a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # TEXT 不能带 server_default;新列 nullable,读侧按 "{}" 兜底(存量行为 NULL 不影响)
    op.add_column('project', sa.Column('repo_meta', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('project', 'repo_meta')
