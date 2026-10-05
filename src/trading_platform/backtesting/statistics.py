"""Realized trade statistics from virtual Spot fills, after commissions."""

from dataclasses import asdict, dataclass
from decimal import Decimal

from trading_platform.backtesting.engine import Fill

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class ClosedTrade:
    entry_time: str
    exit_time: str
    exit_reason: str
    quantity: str
    entry_cost: str
    exit_proceeds: str
    net_pnl: str
    net_return_pct: str


def summarize_trades(fills: tuple[Fill, ...]) -> dict[str, object]:
    """Match long entries and exits; exclude any still-open position from win rate."""
    held = ZERO
    cost = ZERO
    entry_time = ""
    closed: list[ClosedTrade] = []
    for fill in fills:
        quantity = Decimal(fill.quantity)
        notional = Decimal(fill.notional)
        fee = Decimal(fill.fee)
        if fill.side == "BUY":
            if held == ZERO:
                entry_time = fill.time
            held += quantity
            cost += notional + fee
        elif fill.side in {"SELL", "STOP_SELL"}:
            if held <= ZERO or quantity > held:
                raise ValueError("Exit fill exceeds open position")
            allocated_cost = cost if quantity == held else cost * quantity / held
            proceeds = notional - fee
            pnl = proceeds - allocated_cost
            closed.append(
                ClosedTrade(
                    entry_time=entry_time,
                    exit_time=fill.time,
                    exit_reason="STOP" if fill.side == "STOP_SELL" else "SIGNAL_OR_RISK",
                    quantity=str(quantity),
                    entry_cost=str(allocated_cost),
                    exit_proceeds=str(proceeds),
                    net_pnl=str(pnl),
                    net_return_pct=str(pnl / allocated_cost * 100),
                )
            )
            held -= quantity
            cost -= allocated_cost
        else:
            raise ValueError(f"Unexpected fill side: {fill.side}")

    wins = sum(Decimal(trade.net_pnl) > ZERO for trade in closed)
    losses = sum(Decimal(trade.net_pnl) < ZERO for trade in closed)
    gross_profit = sum(
        (Decimal(trade.net_pnl) for trade in closed if Decimal(trade.net_pnl) > ZERO), ZERO
    )
    gross_loss = -sum(
        (Decimal(trade.net_pnl) for trade in closed if Decimal(trade.net_pnl) < ZERO), ZERO
    )
    net_pnl = gross_profit - gross_loss
    count = len(closed)
    return {
        "closed_trades": count,
        "winning_trades": wins,
        "losing_trades": losses,
        "win_rate_pct": str(Decimal(wins) / count * 100) if count else None,
        "net_realized_pnl": str(net_pnl),
        "average_net_pnl": str(net_pnl / count) if count else None,
        "profit_factor": str(gross_profit / gross_loss) if gross_loss else None,
        "open_quantity": str(held),
        "trades": [asdict(trade) for trade in closed],
    }
