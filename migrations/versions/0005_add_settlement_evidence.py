"""Add settlement evidence without changing execution snapshots or precision."""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("bets", sa.Column("settlement_home_score", sa.Integer(), nullable=True))
    op.add_column("bets", sa.Column("settlement_away_score", sa.Integer(), nullable=True))
    op.add_column("bets", sa.Column("settlement_game_status", sa.String(50), nullable=True))
    op.create_check_constraint("ck_bets_settlement_scores", "bets",
                               "settlement_home_score >= 0 AND settlement_away_score >= 0")
    op.create_check_constraint(
        "ck_bets_settlement_consistency", "bets",
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
    )


def downgrade():
    op.drop_constraint("ck_bets_settlement_consistency", "bets", type_="check")
    op.drop_constraint("ck_bets_settlement_scores", "bets", type_="check")
    op.drop_column("bets", "settlement_game_status")
    op.drop_column("bets", "settlement_away_score")
    op.drop_column("bets", "settlement_home_score")
