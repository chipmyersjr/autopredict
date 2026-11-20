"""Canonical games and spreads; schema changes are managed by Alembic."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, UniqueConstraint, CheckConstraint, DateTime, ForeignKey, Identity, Index, Integer, Numeric, String, Text, Uuid, func, text, true
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB


class Base(DeclarativeBase):
    pass


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Game(Timestamps, Base):
    __tablename__ = "games"
    __table_args__ = (
        CheckConstraint("status IN ('scheduled', 'in_progress', 'completed', 'canceled')", name="ck_games_status"),
        CheckConstraint("home_score >= 0", name="ck_games_home_score"),
        CheckConstraint("away_score >= 0", name="ck_games_away_score"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    season: Mapped[int] = mapped_column(Integer)
    week: Mapped[int] = mapped_column(Integer)
    home_team: Mapped[str] = mapped_column(String(255))
    away_team: Mapped[str] = mapped_column(String(255))
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(50))
    home_score: Mapped[int | None] = mapped_column(Integer)
    away_score: Mapped[int | None] = mapped_column(Integer)
    venue: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    markets: Mapped[list["Market"]] = relationship(back_populates="game", order_by="Market.id")


class Market(Timestamps, Base):
    __tablename__ = "markets"
    __table_args__ = (
        CheckConstraint("type = 'spread'", name="ck_markets_type"),
        CheckConstraint("status IN ('active', 'closed', 'settled')", name="ck_markets_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(ForeignKey("games.id"), index=True)
    type: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)
    game: Mapped[Game] = relationship(back_populates="markets")
    selections: Mapped[list["Selection"]] = relationship(back_populates="market", order_by="Selection.id")


class Selection(Timestamps, Base):
    __tablename__ = "selections"
    __table_args__ = (CheckConstraint("price > 1", name="ck_selections_price"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    market_id: Mapped[UUID] = mapped_column(ForeignKey("markets.id"), index=True)
    side: Mapped[str] = mapped_column(String(100))
    line: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    market: Mapped[Market] = relationship(back_populates="selections")


class Strategy(Timestamps, Base):
    __tablename__ = "strategies"
    __table_args__ = (
        CheckConstraint("type IN ('random', 'agent')", name="ck_strategies_type"),
        CheckConstraint("length(trim(name)) > 0", name="ck_strategies_name"),
        CheckConstraint("(type = 'random' AND (config IS NULL OR config = '{}'::jsonb)) OR (type = 'agent' AND config IS NOT NULL AND config = '{\"profile\":\"FootballAnalysisExpert\"}'::jsonb)", name="ck_strategies_config"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    config: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))


class User(Timestamps, Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(255))


class Run(Timestamps, Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("user_id", "request_id", name="uq_runs_user_request"),
        CheckConstraint("starting_bankroll > 0 AND stake_per_bet > 0", name="ck_runs_money"),
        CheckConstraint("status IN ('open', 'completed')", name="ck_runs_status"),
        CheckConstraint("execution_status IN ('queued', 'running', 'completed', 'failed')", name="ck_runs_execution_status"),
        CheckConstraint("execution_generation >= 0", name="ck_runs_execution_generation"),
        CheckConstraint("(execution_status = 'running' AND execution_owner_token IS NOT NULL AND execution_lease_expires_at IS NOT NULL AND execution_started_at IS NOT NULL AND execution_generation > 0) OR (execution_status <> 'running' AND execution_owner_token IS NULL AND execution_lease_expires_at IS NULL)", name="ck_runs_execution_owner"),
        CheckConstraint("(execution_status IN ('queued', 'running') AND execution_finished_at IS NULL AND execution_message IS NULL AND status = 'open') OR (execution_status IN ('completed', 'failed') AND execution_finished_at IS NOT NULL)", name="ck_runs_execution_terminal"),
        CheckConstraint("execution_status <> 'queued' OR execution_started_at IS NULL", name="ck_runs_execution_queued"),
        CheckConstraint("execution_status <> 'failed' OR (status = 'open' AND final_bankroll IS NULL AND total_profit IS NULL AND roi IS NULL AND end_time IS NULL)", name="ck_runs_execution_failed"),
        CheckConstraint("execution_finished_at IS NULL OR execution_started_at IS NULL OR execution_finished_at >= execution_started_at", name="ck_runs_execution_times"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    strategy_id: Mapped[UUID] = mapped_column(ForeignKey("strategies.id", ondelete="RESTRICT"), index=True)
    request_id: Mapped[UUID] = mapped_column(Uuid)
    request_payload: Mapped[dict] = mapped_column(JSONB)
    name: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="open")
    execution_status: Mapped[str] = mapped_column(String(20), server_default="completed")
    execution_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    execution_message: Mapped[str | None] = mapped_column(String(255))
    execution_owner_token: Mapped[UUID | None] = mapped_column(Uuid)
    execution_generation: Mapped[int] = mapped_column(BigInteger, server_default="0")
    execution_lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    starting_bankroll: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    stake_per_bet: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    final_bankroll: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    total_profit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    roi: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    games: Mapped[list["RunGame"]] = relationship(order_by="RunGame.position")
    bets: Mapped[list["Bet"]] = relationship()


class RunGame(Timestamps, Base):
    __tablename__ = "run_games"
    __table_args__ = (
        UniqueConstraint("run_id", "game_id", name="uq_run_games_game"),
        UniqueConstraint("run_id", "position", name="uq_run_games_position"),
        CheckConstraint("position >= 0", name="ck_run_games_position"),
        CheckConstraint("skip_reason IN ('game_not_scheduled', 'kickoff_reached', 'spread_unavailable', 'agent_unavailable', 'research_failed', 'invalid_agent_decision', 'quote_changed')", name="ck_run_games_skip"),
        CheckConstraint("state IN ('queued', 'analysing', 'retrying', 'predicted', 'bet_created', 'skipped')", name="ck_run_games_state"),
        CheckConstraint("attempts BETWEEN 0 AND 2", name="ck_run_games_attempts"),
        CheckConstraint("(state = 'skipped' AND skip_reason IS NOT NULL) OR (state <> 'skipped' AND skip_reason IS NULL)", name="ck_run_games_state_skip"),
        CheckConstraint("state NOT IN ('analysing', 'retrying', 'predicted') OR attempts > 0", name="ck_run_games_state_attempts"),
        CheckConstraint("state <> 'retrying' OR attempts = 1", name="ck_run_games_retry"),
        CheckConstraint("prediction_input IS NULL OR jsonb_typeof(prediction_input) = 'object'", name="ck_run_games_input"),
        CheckConstraint("validated_prediction IS NULL OR jsonb_typeof(validated_prediction) = 'object'", name="ck_run_games_prediction"),
        CheckConstraint("state <> 'predicted' OR (prediction_input IS NOT NULL AND validated_prediction IS NOT NULL)", name="ck_run_games_predicted"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="RESTRICT"), index=True)
    game_id: Mapped[UUID] = mapped_column(ForeignKey("games.id", ondelete="RESTRICT"), index=True)
    included_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    position: Mapped[int] = mapped_column(Integer)
    skip_reason: Mapped[str | None] = mapped_column(String(50))
    state: Mapped[str] = mapped_column(String(20), server_default="bet_created")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    prediction_input: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    validated_prediction: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))


class Bet(Timestamps, Base):
    __tablename__ = "bets"
    __table_args__ = (
        UniqueConstraint("run_id", "game_id", name="uq_bets_run_game"),
        CheckConstraint("stake > 0 AND price > 1", name="ck_bets_money"),
        CheckConstraint("status IN ('open', 'won', 'lost', 'pushed', 'void')", name="ck_bets_status"),
        CheckConstraint("result IN ('won', 'lost', 'pushed', 'void')", name="ck_bets_result"),
        CheckConstraint(
            "(status = 'open' AND result IS NULL AND profit IS NULL AND settled_at IS NULL "
            "AND settlement_game_status IS NULL AND settlement_home_score IS NULL AND settlement_away_score IS NULL) OR "
            "(status <> 'open' AND result IS NOT NULL AND result = status AND profit IS NOT NULL "
            "AND profit > '-Infinity'::numeric AND profit < 'Infinity'::numeric AND settled_at IS NOT NULL "
            "AND settlement_game_status IS NOT NULL AND "
            "((status = 'void' AND settlement_game_status = 'canceled' AND profit = 0) OR "
            "(status IN ('won', 'lost', 'pushed') AND settlement_game_status = 'completed' "
            "AND settlement_home_score IS NOT NULL AND settlement_away_score IS NOT NULL "
            "AND ((status = 'won' AND profit >= 0) OR (status = 'lost' AND profit = -stake) "
            "OR (status = 'pushed' AND profit = 0)))))",
            name="ck_bets_settlement_consistency",
        ),
        CheckConstraint("settlement_home_score >= 0 AND settlement_away_score >= 0", name="ck_bets_settlement_scores"),
        CheckConstraint("reasoning IS NULL OR (length(reasoning) BETWEEN 1 AND 1000 AND reasoning !~ '^[[:space:]]|[[:space:]]$')", name="ck_bets_reasoning"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="RESTRICT"), index=True)
    selection_id: Mapped[UUID] = mapped_column(ForeignKey("selections.id", ondelete="RESTRICT"), index=True)
    game_id: Mapped[UUID] = mapped_column(ForeignKey("games.id", ondelete="RESTRICT"), index=True)
    market_id: Mapped[UUID] = mapped_column(ForeignKey("markets.id", ondelete="RESTRICT"), index=True)
    side: Mapped[str] = mapped_column(String(100))
    line: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    reasoning: Mapped[str | None] = mapped_column(String(1000))
    home_team: Mapped[str] = mapped_column(String(255))
    away_team: Mapped[str] = mapped_column(String(255))
    kickoff_at_placement: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    observation_id: Mapped[UUID | None] = mapped_column(Uuid)
    bookmaker: Mapped[str | None] = mapped_column(String(255))
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stake: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    status: Mapped[str] = mapped_column(String(50), default="open")
    result: Mapped[str | None] = mapped_column(String(50))
    profit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settlement_home_score: Mapped[int | None] = mapped_column(Integer)
    settlement_away_score: Mapped[int | None] = mapped_column(Integer)
    settlement_game_status: Mapped[str | None] = mapped_column(String(50))


class WeeklyRefreshBucket(Timestamps, Base):
    __tablename__ = "weekly_refresh_buckets"
    __table_args__ = (
        UniqueConstraint("week_start", name="uq_refresh_bucket_week"),
        CheckConstraint("week_end > week_start", name="ck_refresh_bucket_window"),
        CheckConstraint("accepted_attempts BETWEEN 0 AND 20", name="ck_refresh_bucket_attempts"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    week_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    week_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshRun(Timestamps, Base):
    """Durable ownership and safe stage summaries; never store keys/raw responses."""
    __tablename__ = "refresh_runs"
    __table_args__ = (
        UniqueConstraint("generation", name="uq_refresh_run_generation"),
        CheckConstraint("generation > 0", name="ck_refresh_run_generation"),
        CheckConstraint("status IN ('reserved', 'running', 'succeeded', 'partial_failure', 'failed', 'abandoned', 'rejected')", name="ck_refresh_run_status"),
        CheckConstraint("deadline_at > started_at", name="ck_refresh_run_deadline"),
        CheckConstraint("finished_at IS NULL OR finished_at >= started_at", name="ck_refresh_run_finished"),
        CheckConstraint("jsonb_typeof(stage_outcomes) = 'object' AND jsonb_typeof(item_failures) = 'array'", name="ck_refresh_run_summaries"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    bucket_id: Mapped[UUID] = mapped_column(ForeignKey("weekly_refresh_buckets.id", ondelete="RESTRICT"), index=True)
    # Database-issued monotonic fence; advisory-lock ownership is enforced in BE-07.
    generation: Mapped[int] = mapped_column(BigInteger, Identity())
    status: Mapped[str] = mapped_column(String(32), server_default="reserved")
    reason: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_changed: Mapped[bool] = mapped_column(Boolean, server_default="false")
    stage_outcomes: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    item_failures: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))


class ProviderQuotaPeriod(Timestamps, Base):
    """Provider-defined periods; unknown reset/start times stay null."""
    __tablename__ = "provider_quota_periods"
    __table_args__ = (
        UniqueConstraint("provider", "period_key", name="uq_provider_quota_period"),
        Index("uq_provider_quota_current", "provider", unique=True, postgresql_where=text("is_current")),
        CheckConstraint("provider IN ('cfbd', 'odds')", name="ck_provider_quota_provider"),
        CheckConstraint("allowance > 0 AND used >= 0 AND reserved >= 0", name="ck_provider_quota_counts"),
        CheckConstraint("reserve_fraction >= 0 AND reserve_fraction < 1", name="ck_provider_quota_reserve"),
        CheckConstraint("reported_remaining IS NULL OR reported_remaining >= 0", name="ck_provider_quota_remaining"),
        CheckConstraint("resets_at IS NULL OR starts_at IS NULL OR resets_at > starts_at", name="ck_provider_quota_window"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(16))
    period_key: Mapped[str] = mapped_column(String(128))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resets_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_current: Mapped[bool] = mapped_column(Boolean, server_default=true())
    allowance: Mapped[int] = mapped_column(Integer)
    reserve_fraction: Mapped[Decimal] = mapped_column(Numeric(5, 4), server_default="0.1")
    used: Mapped[int] = mapped_column(Integer, server_default="0")
    reserved: Mapped[int] = mapped_column(Integer, server_default="0")
    reported_remaining: Mapped[int | None] = mapped_column(Integer)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProviderCallReservation(Timestamps, Base):
    __tablename__ = "provider_call_reservations"
    __table_args__ = (
        CheckConstraint("estimated_cost > 0 AND (actual_cost IS NULL OR actual_cost >= 0)", name="ck_provider_call_cost"),
        CheckConstraint("status IN ('reserved', 'dispatched', 'succeeded', 'failed', 'unknown', 'released')", name="ck_provider_call_status"),
        CheckConstraint("http_status IS NULL OR http_status BETWEEN 100 AND 599", name="ck_provider_call_http"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("refresh_runs.id", ondelete="RESTRICT"), index=True)
    quota_period_id: Mapped[UUID] = mapped_column(ForeignKey("provider_quota_periods.id", ondelete="RESTRICT"), index=True)
    # Endpoint label only, never a URL containing an API key.
    endpoint: Mapped[str] = mapped_column(String(64))
    estimated_cost: Mapped[int] = mapped_column(Integer)
    actual_cost: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), server_default="reserved")
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    http_status: Mapped[int | None] = mapped_column(Integer)


class ProviderCalendar(Timestamps, Base):
    __tablename__ = "provider_calendars"
    __table_args__ = (
        UniqueConstraint("provider", "season", name="uq_provider_calendar_season"),
        CheckConstraint("provider = 'cfbd'", name="ck_provider_calendar_provider"),
        CheckConstraint("jsonb_typeof(weeks) = 'array'", name="ck_provider_calendar_weeks"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(16), server_default="cfbd")
    season: Mapped[int] = mapped_column(Integer)
    weeks: Mapped[list] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TeamAlias(Timestamps, Base):
    __tablename__ = "team_aliases"
    __table_args__ = (
        UniqueConstraint("provider", "season", "source_identity", name="uq_team_alias_identity"),
        CheckConstraint("provider IN ('cfbd', 'odds')", name="ck_team_alias_provider"),
        CheckConstraint("length(trim(source_identity)) > 0 AND length(trim(source_name)) > 0 AND length(trim(canonical_team)) > 0", name="ck_team_alias_names"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(16))
    season: Mapped[int] = mapped_column(Integer)
    source_identity: Mapped[str] = mapped_column(String(255))
    source_name: Mapped[str] = mapped_column(String(255))
    canonical_team: Mapped[str] = mapped_column(String(255), index=True)
    classification: Mapped[str | None] = mapped_column(String(32))


class ProviderGameLink(Timestamps, Base):
    __tablename__ = "provider_game_links"
    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_provider_game_identity"),
        CheckConstraint("provider IN ('cfbd', 'odds')", name="ck_provider_game_provider"),
        CheckConstraint("length(trim(external_id)) > 0", name="ck_provider_game_external_id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(128))
    game_id: Mapped[UUID] = mapped_column(ForeignKey("games.id", ondelete="RESTRICT"), index=True)
    season: Mapped[int] = mapped_column(Integer)
    week: Mapped[int | None] = mapped_column(Integer)
    season_type: Mapped[str | None] = mapped_column(String(32))
    home_identity: Mapped[str] = mapped_column(String(255))
    away_identity: Mapped[str] = mapped_column(String(255))
    home_classification: Mapped[str | None] = mapped_column(String(32))
    away_classification: Mapped[str | None] = mapped_column(String(32))
    source_state: Mapped[str | None] = mapped_column(String(64))
    source_kickoff: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    neutral_site: Mapped[bool | None] = mapped_column(Boolean)
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class QuoteObservation(Timestamps, Base):
    """Paired saved prices; changing availability must retain historical rows."""
    __tablename__ = "quote_observations"
    __table_args__ = (
        UniqueConstraint("market_id", "content_hash", name="uq_quote_observation_content"),
        Index("uq_quote_current_game", "game_id", unique=True, postgresql_where=text("is_current")),
        Index("uq_quote_current_market", "market_id", unique=True, postgresql_where=text("is_current")),
        CheckConstraint("home_line = -away_line", name="ck_quote_opposite_lines"),
        CheckConstraint("home_price > 1 AND away_price > 1 AND home_price < 'Infinity'::numeric AND away_price < 'Infinity'::numeric", name="ck_quote_prices"),
        CheckConstraint("home_line > '-Infinity'::numeric AND home_line < 'Infinity'::numeric", name="ck_quote_finite_line"),
        CheckConstraint("length(trim(bookmaker)) > 0 AND length(trim(external_event_id)) > 0 AND content_hash ~ '^[0-9a-f]{64}$'", name="ck_quote_identity"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(ForeignKey("games.id", ondelete="RESTRICT"), index=True)
    market_id: Mapped[UUID] = mapped_column(ForeignKey("markets.id", ondelete="RESTRICT"), index=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("refresh_runs.id", ondelete="RESTRICT"), index=True)
    external_event_id: Mapped[str] = mapped_column(String(128))
    bookmaker: Mapped[str] = mapped_column(String(128))
    home_line: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    away_line: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    home_price: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    away_price: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str] = mapped_column(String(64))
    is_current: Mapped[bool] = mapped_column(Boolean, server_default="false")


class GameResultChange(Timestamps, Base):
    __tablename__ = "game_result_changes"
    __table_args__ = (
        CheckConstraint("old_home_score >= 0 AND old_away_score >= 0 AND new_home_score >= 0 AND new_away_score >= 0", name="ck_result_change_scores"),
        CheckConstraint("new_status != 'completed' OR (new_home_score IS NOT NULL AND new_away_score IS NOT NULL)", name="ck_result_change_final"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(ForeignKey("games.id", ondelete="RESTRICT"), index=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("refresh_runs.id", ondelete="RESTRICT"), index=True)
    old_status: Mapped[str] = mapped_column(String(50))
    new_status: Mapped[str] = mapped_column(String(50))
    old_home_score: Mapped[int | None] = mapped_column(Integer)
    old_away_score: Mapped[int | None] = mapped_column(Integer)
    new_home_score: Mapped[int | None] = mapped_column(Integer)
    new_away_score: Mapped[int | None] = mapped_column(Integer)
    source_state: Mapped[str] = mapped_column(String(64))
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
