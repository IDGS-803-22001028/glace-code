"""add two factor fields to user

Revision ID: a1f9c2d3e4b5
Revises: d8f3a7c2b1e4
Create Date: 2026-04-20 14:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1f9c2d3e4b5'
down_revision = 'd8f3a7c2b1e4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('two_factor_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('two_factor_secret', sa.String(length=64), nullable=True))
        batch_op.create_index(batch_op.f('ix_user_two_factor_enabled'), ['two_factor_enabled'], unique=False)


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_two_factor_enabled'))
        batch_op.drop_column('two_factor_secret')
        batch_op.drop_column('two_factor_enabled')
