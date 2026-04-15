"""add producto_id to Merma

Revision ID: d8f3a7c2b1e4
Revises: 8050864d5dbc
Create Date: 2026-04-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd8f3a7c2b1e4'
down_revision = '8050864d5dbc'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('MERMA', schema=None) as batch_op:
        batch_op.add_column(sa.Column('producto_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_merma_producto_id_product', 'product', ['producto_id'], ['id'])
        batch_op.create_index(batch_op.f('ix_merma_producto_id'), ['producto_id'], unique=False)


def downgrade():
    with op.batch_alter_table('MERMA', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_merma_producto_id'))
        batch_op.drop_constraint('fk_merma_producto_id_product', type_='foreignkey')
        batch_op.drop_column('producto_id')
