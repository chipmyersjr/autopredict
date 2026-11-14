"""Persist local ownership, simulation requests, and immutable bet snapshots."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('users',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.create_table('runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('strategy_id', sa.Uuid(), nullable=False),
    sa.Column('request_id', sa.Uuid(), nullable=False),
    sa.Column('request_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('starting_bankroll', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('stake_per_bet', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('end_time', sa.DateTime(timezone=True), nullable=True),
    sa.Column('final_bankroll', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('total_profit', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('roi', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('open', 'completed')", name='ck_runs_status'),
    sa.CheckConstraint('starting_bankroll > 0 AND stake_per_bet > 0', name='ck_runs_money'),
    sa.ForeignKeyConstraint(['strategy_id'], ['strategies.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'request_id', name='uq_runs_user_request')
    )
    op.create_index(op.f('ix_runs_start_time'), 'runs', ['start_time'], unique=False)
    op.create_index(op.f('ix_runs_strategy_id'), 'runs', ['strategy_id'], unique=False)
    op.create_index(op.f('ix_runs_user_id'), 'runs', ['user_id'], unique=False)
    op.create_table('run_games',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('game_id', sa.Uuid(), nullable=False),
    sa.Column('included_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('skip_reason', sa.String(length=50), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("skip_reason IN ('game_not_scheduled', 'kickoff_reached', 'spread_unavailable')", name='ck_run_games_skip'),
    sa.CheckConstraint('position >= 0', name='ck_run_games_position'),
    sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id', 'game_id', name='uq_run_games_game'),
    sa.UniqueConstraint('run_id', 'position', name='uq_run_games_position')
    )
    op.create_index(op.f('ix_run_games_game_id'), 'run_games', ['game_id'], unique=False)
    op.create_index(op.f('ix_run_games_run_id'), 'run_games', ['run_id'], unique=False)
    op.create_table('bets',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('selection_id', sa.Uuid(), nullable=False),
    sa.Column('game_id', sa.Uuid(), nullable=False),
    sa.Column('market_id', sa.Uuid(), nullable=False),
    sa.Column('side', sa.String(length=100), nullable=False),
    sa.Column('line', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('home_team', sa.String(length=255), nullable=False),
    sa.Column('away_team', sa.String(length=255), nullable=False),
    sa.Column('kickoff_at_placement', sa.DateTime(timezone=True), nullable=False),
    sa.Column('observation_id', sa.Uuid(), nullable=True),
    sa.Column('bookmaker', sa.String(length=255), nullable=True),
    sa.Column('source_timestamp', sa.DateTime(timezone=True), nullable=True),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('stake', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('price', sa.Numeric(precision=10, scale=4), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('result', sa.String(length=50), nullable=True),
    sa.Column('profit', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('placed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('settled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("result IN ('won', 'lost', 'pushed', 'void')", name='ck_bets_result'),
    sa.CheckConstraint("status IN ('open', 'won', 'lost', 'pushed', 'void')", name='ck_bets_status'),
    sa.CheckConstraint('stake > 0 AND price > 1', name='ck_bets_money'),
    sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['market_id'], ['markets.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['selection_id'], ['selections.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id', 'game_id', name='uq_bets_run_game')
    )
    op.create_index(op.f('ix_bets_game_id'), 'bets', ['game_id'], unique=False)
    op.create_index(op.f('ix_bets_market_id'), 'bets', ['market_id'], unique=False)
    op.create_index(op.f('ix_bets_run_id'), 'bets', ['run_id'], unique=False)
    op.create_index(op.f('ix_bets_selection_id'), 'bets', ['selection_id'], unique=False)

def downgrade():
    for table in ("bets", "run_games", "runs", "users"):
        op.drop_table(table)
