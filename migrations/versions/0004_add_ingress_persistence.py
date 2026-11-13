"""Add durable ingress identity, observations, refresh ownership, and quotas.

Existing canonical tables and historical migrations are deliberately unchanged.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('provider_calendars',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('provider', sa.String(length=16), server_default='cfbd', nullable=False),
    sa.Column('season', sa.Integer(), nullable=False),
    sa.Column('weeks', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("jsonb_typeof(weeks) = 'array'", name='ck_provider_calendar_weeks'),
    sa.CheckConstraint("provider = 'cfbd'", name='ck_provider_calendar_provider'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider', 'season', name='uq_provider_calendar_season')
    )
    op.create_table('provider_quota_periods',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('provider', sa.String(length=16), nullable=False),
    sa.Column('period_key', sa.String(length=128), nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resets_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_current', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('allowance', sa.Integer(), nullable=False),
    sa.Column('reserve_fraction', sa.Numeric(precision=5, scale=4), server_default='0.1', nullable=False),
    sa.Column('used', sa.Integer(), server_default='0', nullable=False),
    sa.Column('reserved', sa.Integer(), server_default='0', nullable=False),
    sa.Column('reported_remaining', sa.Integer(), nullable=True),
    sa.Column('checked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('retry_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("provider IN ('cfbd', 'odds')", name='ck_provider_quota_provider'),
    sa.CheckConstraint('allowance > 0 AND used >= 0 AND reserved >= 0', name='ck_provider_quota_counts'),
    sa.CheckConstraint('reported_remaining IS NULL OR reported_remaining >= 0', name='ck_provider_quota_remaining'),
    sa.CheckConstraint('reserve_fraction >= 0 AND reserve_fraction < 1', name='ck_provider_quota_reserve'),
    sa.CheckConstraint('resets_at IS NULL OR starts_at IS NULL OR resets_at > starts_at', name='ck_provider_quota_window'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider', 'period_key', name='uq_provider_quota_period')
    )
    op.create_index('uq_provider_quota_current', 'provider_quota_periods', ['provider'], unique=True, postgresql_where=sa.text('is_current'))
    op.create_table('team_aliases',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('provider', sa.String(length=16), nullable=False),
    sa.Column('season', sa.Integer(), nullable=False),
    sa.Column('source_identity', sa.String(length=255), nullable=False),
    sa.Column('source_name', sa.String(length=255), nullable=False),
    sa.Column('canonical_team', sa.String(length=255), nullable=False),
    sa.Column('classification', sa.String(length=32), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("provider IN ('cfbd', 'odds')", name='ck_team_alias_provider'),
    sa.CheckConstraint('length(trim(source_identity)) > 0 AND length(trim(source_name)) > 0 AND length(trim(canonical_team)) > 0', name='ck_team_alias_names'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider', 'season', 'source_identity', name='uq_team_alias_identity')
    )
    op.create_index(op.f('ix_team_aliases_canonical_team'), 'team_aliases', ['canonical_team'], unique=False)
    op.create_table('weekly_refresh_buckets',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('week_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('week_end', sa.DateTime(timezone=True), nullable=False),
    sa.Column('accepted_attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('accepted_attempts BETWEEN 0 AND 20', name='ck_refresh_bucket_attempts'),
    sa.CheckConstraint('week_end > week_start', name='ck_refresh_bucket_window'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('week_start', name='uq_refresh_bucket_week')
    )
    op.create_table('provider_game_links',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('provider', sa.String(length=16), nullable=False),
    sa.Column('external_id', sa.String(length=128), nullable=False),
    sa.Column('game_id', sa.Uuid(), nullable=False),
    sa.Column('season', sa.Integer(), nullable=False),
    sa.Column('week', sa.Integer(), nullable=True),
    sa.Column('season_type', sa.String(length=32), nullable=True),
    sa.Column('home_identity', sa.String(length=255), nullable=False),
    sa.Column('away_identity', sa.String(length=255), nullable=False),
    sa.Column('home_classification', sa.String(length=32), nullable=True),
    sa.Column('away_classification', sa.String(length=32), nullable=True),
    sa.Column('source_state', sa.String(length=64), nullable=True),
    sa.Column('source_kickoff', sa.DateTime(timezone=True), nullable=True),
    sa.Column('neutral_site', sa.Boolean(), nullable=True),
    sa.Column('source_timestamp', sa.DateTime(timezone=True), nullable=True),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("provider IN ('cfbd', 'odds')", name='ck_provider_game_provider'),
    sa.CheckConstraint('length(trim(external_id)) > 0', name='ck_provider_game_external_id'),
    sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider', 'external_id', name='uq_provider_game_identity')
    )
    op.create_index(op.f('ix_provider_game_links_game_id'), 'provider_game_links', ['game_id'], unique=False)
    op.create_table('refresh_runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('bucket_id', sa.Uuid(), nullable=False),
    sa.Column('generation', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('status', sa.String(length=32), server_default='reserved', nullable=False),
    sa.Column('reason', sa.String(length=64), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('deadline_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('provider_started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('data_changed', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('stage_outcomes', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('item_failures', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("jsonb_typeof(stage_outcomes) = 'object' AND jsonb_typeof(item_failures) = 'array'", name='ck_refresh_run_summaries'),
    sa.CheckConstraint("status IN ('reserved', 'running', 'succeeded', 'partial_failure', 'failed', 'abandoned', 'rejected')", name='ck_refresh_run_status'),
    sa.CheckConstraint('deadline_at > started_at', name='ck_refresh_run_deadline'),
    sa.CheckConstraint('finished_at IS NULL OR finished_at >= started_at', name='ck_refresh_run_finished'),
    sa.CheckConstraint('generation > 0', name='ck_refresh_run_generation'),
    sa.ForeignKeyConstraint(['bucket_id'], ['weekly_refresh_buckets.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('generation', name='uq_refresh_run_generation')
    )
    op.create_index(op.f('ix_refresh_runs_bucket_id'), 'refresh_runs', ['bucket_id'], unique=False)
    op.create_table('game_result_changes',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('game_id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('old_status', sa.String(length=50), nullable=False),
    sa.Column('new_status', sa.String(length=50), nullable=False),
    sa.Column('old_home_score', sa.Integer(), nullable=True),
    sa.Column('old_away_score', sa.Integer(), nullable=True),
    sa.Column('new_home_score', sa.Integer(), nullable=True),
    sa.Column('new_away_score', sa.Integer(), nullable=True),
    sa.Column('source_state', sa.String(length=64), nullable=False),
    sa.Column('source_timestamp', sa.DateTime(timezone=True), nullable=True),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("new_status != 'completed' OR (new_home_score IS NOT NULL AND new_away_score IS NOT NULL)", name='ck_result_change_final'),
    sa.CheckConstraint('old_home_score >= 0 AND old_away_score >= 0 AND new_home_score >= 0 AND new_away_score >= 0', name='ck_result_change_scores'),
    sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['run_id'], ['refresh_runs.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_game_result_changes_game_id'), 'game_result_changes', ['game_id'], unique=False)
    op.create_index(op.f('ix_game_result_changes_run_id'), 'game_result_changes', ['run_id'], unique=False)
    op.create_table('provider_call_reservations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('quota_period_id', sa.Uuid(), nullable=False),
    sa.Column('endpoint', sa.String(length=64), nullable=False),
    sa.Column('estimated_cost', sa.Integer(), nullable=False),
    sa.Column('actual_cost', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=16), server_default='reserved', nullable=False),
    sa.Column('dispatched_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('http_status', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('reserved', 'dispatched', 'succeeded', 'failed', 'unknown', 'released')", name='ck_provider_call_status'),
    sa.CheckConstraint('estimated_cost > 0 AND (actual_cost IS NULL OR actual_cost >= 0)', name='ck_provider_call_cost'),
    sa.CheckConstraint('http_status IS NULL OR http_status BETWEEN 100 AND 599', name='ck_provider_call_http'),
    sa.ForeignKeyConstraint(['quota_period_id'], ['provider_quota_periods.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['run_id'], ['refresh_runs.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_provider_call_reservations_quota_period_id'), 'provider_call_reservations', ['quota_period_id'], unique=False)
    op.create_index(op.f('ix_provider_call_reservations_run_id'), 'provider_call_reservations', ['run_id'], unique=False)
    op.create_table('quote_observations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('game_id', sa.Uuid(), nullable=False),
    sa.Column('market_id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('external_event_id', sa.String(length=128), nullable=False),
    sa.Column('bookmaker', sa.String(length=128), nullable=False),
    sa.Column('home_line', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('away_line', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('home_price', sa.Numeric(precision=10, scale=4), nullable=False),
    sa.Column('away_price', sa.Numeric(precision=10, scale=4), nullable=False),
    sa.Column('source_timestamp', sa.DateTime(timezone=True), nullable=True),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('is_current', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("home_line > '-Infinity'::numeric AND home_line < 'Infinity'::numeric", name='ck_quote_finite_line'),
    sa.CheckConstraint("home_price > 1 AND away_price > 1 AND home_price < 'Infinity'::numeric AND away_price < 'Infinity'::numeric", name='ck_quote_prices'),
    sa.CheckConstraint("length(trim(bookmaker)) > 0 AND length(trim(external_event_id)) > 0 AND content_hash ~ '^[0-9a-f]{64}$'", name='ck_quote_identity'),
    sa.CheckConstraint('home_line = -away_line', name='ck_quote_opposite_lines'),
    sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['market_id'], ['markets.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['run_id'], ['refresh_runs.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('market_id', 'content_hash', name='uq_quote_observation_content')
    )
    op.create_index(op.f('ix_quote_observations_game_id'), 'quote_observations', ['game_id'], unique=False)
    op.create_index(op.f('ix_quote_observations_market_id'), 'quote_observations', ['market_id'], unique=False)
    op.create_index(op.f('ix_quote_observations_run_id'), 'quote_observations', ['run_id'], unique=False)
    op.create_index('uq_quote_current_game', 'quote_observations', ['game_id'], unique=True, postgresql_where=sa.text('is_current'))
    op.create_index('uq_quote_current_market', 'quote_observations', ['market_id'], unique=True, postgresql_where=sa.text('is_current'))


def downgrade():
    op.drop_index('uq_quote_current_market', table_name='quote_observations', postgresql_where=sa.text('is_current'))
    op.drop_index('uq_quote_current_game', table_name='quote_observations', postgresql_where=sa.text('is_current'))
    op.drop_index(op.f('ix_quote_observations_run_id'), table_name='quote_observations')
    op.drop_index(op.f('ix_quote_observations_market_id'), table_name='quote_observations')
    op.drop_index(op.f('ix_quote_observations_game_id'), table_name='quote_observations')
    op.drop_table('quote_observations')
    op.drop_index(op.f('ix_provider_call_reservations_run_id'), table_name='provider_call_reservations')
    op.drop_index(op.f('ix_provider_call_reservations_quota_period_id'), table_name='provider_call_reservations')
    op.drop_table('provider_call_reservations')
    op.drop_index(op.f('ix_game_result_changes_run_id'), table_name='game_result_changes')
    op.drop_index(op.f('ix_game_result_changes_game_id'), table_name='game_result_changes')
    op.drop_table('game_result_changes')
    op.drop_index(op.f('ix_refresh_runs_bucket_id'), table_name='refresh_runs')
    op.drop_table('refresh_runs')
    op.drop_index(op.f('ix_provider_game_links_game_id'), table_name='provider_game_links')
    op.drop_table('provider_game_links')
    op.drop_table('weekly_refresh_buckets')
    op.drop_index(op.f('ix_team_aliases_canonical_team'), table_name='team_aliases')
    op.drop_table('team_aliases')
    op.drop_index('uq_provider_quota_current', table_name='provider_quota_periods', postgresql_where=sa.text('is_current'))
    op.drop_table('provider_quota_periods')
    op.drop_table('provider_calendars')
