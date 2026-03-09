"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-03-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('username', sa.String(length=50), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('total_points', sa.BigInteger(), nullable=False, server_default='1000000'),
        sa.Column('available_points', sa.BigInteger(), nullable=False, server_default='1000000'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username'),
    )

    op.create_table(
        'markets',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('closes_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.Enum('Open', 'Closed', 'Resolved', name='marketstatus'), nullable=False, server_default='Open'),
        sa.Column('result', sa.Enum('YES', 'NO', name='marketresult'), nullable=True),
        sa.Column('created_by', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'orders',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('market_id', sa.BigInteger(), nullable=False),
        sa.Column('position', sa.Enum('YES', 'NO', name='positionside'), nullable=False),
        sa.Column('order_type', sa.Enum('Bid', 'Ask', name='ordertype'), nullable=False),
        sa.Column('price', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('remaining_quantity', sa.Integer(), nullable=False),
        sa.Column('status', sa.Enum('Pending', 'Open', 'Partial', 'Filled', 'Cancelled', name='orderstatus'), nullable=False, server_default='Pending'),
        sa.Column('locked_points', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint('price >= 1 AND price <= 99', name='ck_orders_price_range'),
        sa.CheckConstraint('quantity > 0', name='ck_orders_quantity_positive'),
        sa.CheckConstraint('remaining_quantity >= 0', name='ck_orders_remaining_non_negative'),
        sa.CheckConstraint('locked_points >= 0', name='ck_orders_locked_points_non_negative'),
        sa.ForeignKeyConstraint(['market_id'], ['markets.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_orders_book',
        'orders',
        ['market_id', 'position', 'order_type', 'status', 'price', 'created_at'],
    )

    op.create_table(
        'positions',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('market_id', sa.BigInteger(), nullable=False),
        sa.Column('position', sa.Enum('YES', 'NO', name='positionside'), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('avg_price', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['market_id'], ['markets.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'market_id', 'position', name='uq_positions_user_market_pos'),
    )

    op.create_table(
        'trades',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('market_id', sa.BigInteger(), nullable=False),
        sa.Column('maker_order_id', sa.BigInteger(), nullable=False),
        sa.Column('taker_order_id', sa.BigInteger(), nullable=False),
        sa.Column('position', sa.Enum('YES', 'NO', name='positionside'), nullable=False),
        sa.Column('price', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['maker_order_id'], ['orders.id']),
        sa.ForeignKeyConstraint(['market_id'], ['markets.id']),
        sa.ForeignKeyConstraint(['taker_order_id'], ['orders.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('trades')
    op.drop_table('positions')
    op.drop_index('ix_orders_book', table_name='orders')
    op.drop_table('orders')
    op.drop_table('markets')
    op.drop_table('users')
    op.execute('DROP TYPE IF EXISTS positionside')
    op.execute('DROP TYPE IF EXISTS ordertype')
    op.execute('DROP TYPE IF EXISTS orderstatus')
    op.execute('DROP TYPE IF EXISTS marketstatus')
    op.execute('DROP TYPE IF EXISTS marketresult')
