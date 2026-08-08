"""hypertable

Revision ID: 3c1db4d84047
Revises: 6f272a04f85c
Create Date: 2026-08-08 19:16:30.733372

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3c1db4d84047'
down_revision: Union[str, Sequence[str], None] = '6f272a04f85c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SELECT create_hypertable('macro_variables', 'timestamp');")


def downgrade() -> None:
    """Downgrade schema."""
    pass
