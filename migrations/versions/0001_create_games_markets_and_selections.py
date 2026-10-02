"""Create games markets and selections"""
from alembic import op
import sqlalchemy as sa


revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('games',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('season', sa.Integer(), nullable=False),
    sa.Column('week', sa.Integer(), nullable=False),
    sa.Column('home_team', sa.String(length=255), nullable=False),
    sa.Column('away_team', sa.String(length=255), nullable=False),
    sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('home_score', sa.Integer(), nullable=True),
    sa.Column('away_score', sa.Integer(), nullable=True),
    sa.Column('venue', sa.String(length=255), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('scheduled', 'in_progress', 'completed', 'canceled')", name='ck_games_status'),
    sa.CheckConstraint('away_score >= 0', name='ck_games_away_score'),
    sa.CheckConstraint('home_score >= 0', name='ck_games_home_score'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_games_start_time'), 'games', ['start_time'], unique=False)
    op.create_table('markets',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('game_id', sa.Uuid(), nullable=False),
    sa.Column('type', sa.String(length=50), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('active', 'closed', 'settled')", name='ck_markets_status'),
    sa.CheckConstraint("type = 'spread'", name='ck_markets_type'),
    sa.ForeignKeyConstraint(['game_id'], ['games.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_markets_game_id'), 'markets', ['game_id'], unique=False)
    op.create_table('selections',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('market_id', sa.Uuid(), nullable=False),
    sa.Column('side', sa.String(length=100), nullable=False),
    sa.Column('line', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('price', sa.Numeric(precision=10, scale=4), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('price > 1', name='ck_selections_price'),
    sa.ForeignKeyConstraint(['market_id'], ['markets.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_selections_market_id'), 'selections', ['market_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_selections_market_id'), table_name='selections')
    op.drop_table('selections')
    op.drop_index(op.f('ix_markets_game_id'), table_name='markets')
    op.drop_table('markets')
    op.drop_index(op.f('ix_games_start_time'), table_name='games')
    op.drop_table('games')
