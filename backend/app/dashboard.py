"""Read-only totals across independent local-user simulations, including history."""
from decimal import Decimal, ROUND_HALF_UP, localcontext

from sqlalchemy import Date, cast, func, select, text

from app.models import Bet, Run
from app.runs import bet_response, local_user
from app.schemas import DashboardResponse, PerformancePoint


def read_dashboard(session):
    # Set isolation before the first query, including local-user resolution.
    # All subsequent statements see the same committed state without row locks.
    session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
    session.execute(text("SET TRANSACTION READ ONLY"))
    owner = local_user(session)
    zero = Decimal("0.00")
    run_count, active, completed, starting = session.execute(select(
        func.count(Run.id),
        func.count().filter(Run.status == "open"),
        func.count().filter(Run.status == "completed"),
        func.sum(Run.starting_bankroll),
    ).where(Run.user_id == owner)).one()
    owned_bets = (Bet.run_id == Run.id, Run.user_id == owner)
    counts = [func.count().filter(Bet.status == status)
              for status in ("open", "won", "lost", "pushed", "void")]
    bet_count, opened, wins, losses, pushes, voids, committed, profit = session.execute(
        select(func.count(), *counts,
               func.sum(Bet.stake).filter(Bet.status == "open"),
               func.sum(Bet.profit).filter(Bet.status != "open"))
        .select_from(Bet).join(Run, Bet.run_id == Run.id).where(Run.user_id == owner)
    ).one()
    recent = session.scalars(select(Bet).join(Run, Bet.run_id == Run.id)
        .where(*owned_bets, Bet.status != "open")
        .order_by(Bet.settled_at.desc(), Bet.id).limit(10)).all()
    day = cast(func.timezone("UTC", Bet.settled_at), Date)
    daily = session.execute(select(day, func.sum(Bet.profit))
        .select_from(Bet).join(Run, Bet.run_id == Run.id)
        .where(Run.user_id == owner, Bet.status != "open")
        .group_by(day).order_by(day)).all()
    with localcontext() as context:
        context.prec = 50
        starting, committed, profit = starting or zero, committed or zero, profit or zero
        current = starting + profit
        cumulative = zero
        performance = []
        for date, amount in daily:
            cumulative += amount
            performance.append(PerformancePoint(date=date, profit=amount, cumulative_profit=cumulative))
        return DashboardResponse(
            run_count=run_count, active_run_count=active, completed_run_count=completed,
            starting_bankroll_total=starting, current_bankroll_total=current,
            available_bankroll_total=current - committed, committed_stake_total=committed,
            realized_profit=profit,
            roi=(profit / starting).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP) if run_count else None,
            bet_count=bet_count, open_bet_count=opened, win_count=wins, loss_count=losses,
            push_count=pushes, void_count=voids,
            recent_results=[bet_response(bet) for bet in recent], performance=performance,
        )
