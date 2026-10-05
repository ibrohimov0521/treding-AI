"""Long-only, event-time backtesting with explicit trading costs."""

from dataclasses import asdict, dataclass
from datetime import timedelta
from decimal import Decimal

from trading_platform.core.enums import MarketType
from trading_platform.domain.candle import Candle
from trading_platform.features.engineering import compute_features
from trading_platform.risk.engine import RiskEngine, RiskLimits
from trading_platform.signals.engine import SignalEngine
from trading_platform.strategies.base import TargetExposureStrategy

ZERO = Decimal("0")
ONE = Decimal("1")
BPS = Decimal("10000")


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """Simulation assumptions; amounts are denominated in the quote asset."""

    starting_cash: Decimal = Decimal("10000")
    fee_bps: Decimal = Decimal("10")
    spread_bps: Decimal = Decimal("2")
    slippage_bps: Decimal = Decimal("5")
    stop_loss_pct: Decimal | None = None

    def __post_init__(self) -> None:
        if self.starting_cash <= ZERO:
            raise ValueError("starting_cash must be positive")
        if not ZERO <= self.fee_bps < BPS:
            raise ValueError("fee_bps must be in [0, 10000)")
        if not ZERO <= self.spread_bps < BPS:
            raise ValueError("spread_bps must be in [0, 10000)")
        if not ZERO <= self.slippage_bps < BPS:
            raise ValueError("slippage_bps must be in [0, 10000)")
        if self.spread_bps / 2 + self.slippage_bps >= BPS:
            raise ValueError("combined per-side spread and slippage must be below 10000 bps")
        if self.stop_loss_pct is not None and (
            not self.stop_loss_pct.is_finite() or not ZERO < self.stop_loss_pct < Decimal("100")
        ):
            raise ValueError("stop_loss_pct must be in (0, 100)")


@dataclass(frozen=True, slots=True)
class Fill:
    """A simulated fill at the next candle's open; it is not an exchange order."""

    side: str
    time: str
    quantity: str
    price: str
    notional: str
    fee: str


@dataclass(frozen=True, slots=True)
class EquityPoint:
    time: str
    cash: str
    base_quantity: str
    close_price: str
    equity: str


@dataclass(frozen=True, slots=True)
class BacktestResult:
    strategy: str
    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    starting_cash: str
    ending_equity: str
    total_return_pct: str
    max_drawdown_pct: str
    risk_halted: bool
    risk_halt_reason: str | None
    fees_paid: str
    stop_exits: int
    ending_cash: str
    ending_base_quantity: str
    fills: tuple[Fill, ...]
    equity_curve: tuple[EquityPoint, ...]

    @property
    def trade_count(self) -> int:
        return len(self.fills)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe report without converting money to binary floats."""
        result = asdict(self)
        result["trade_count"] = self.trade_count
        return result


def run_backtest(
    candles: list[Candle],
    strategy: TargetExposureStrategy,
    config: BacktestConfig | None = None,
    *,
    risk_limits: RiskLimits | None = None,
) -> BacktestResult:
    """Simulate a strategy over one complete, contiguous spot candle series.

    Strategy decisions use features available after candle ``t`` closes. A
    changed target exposure fills at candle ``t+1`` open. Buys pay half-spread,
    slippage, and commission; sells pay the same costs in the opposite direction.
    The final signal remains pending because there is no next candle to fill it.
    """
    if len(candles) < 2:
        raise ValueError("Backtest requires at least two candles")
    settings = config or BacktestConfig()
    limits = risk_limits or RiskLimits()
    risk_engine = RiskEngine(limits)
    signal_engine = SignalEngine(risk_engine)
    _validate_series(candles)
    if candles[0].market_type != MarketType.SPOT:
        raise ValueError("This backtest implementation supports Spot markets only")

    # close_time is inclusive; move the cutoff one microsecond ahead so the last
    # historical candle is complete deterministically.
    feature_rows = compute_features(
        candles, as_of=candles[-1].close_time + timedelta(microseconds=1)
    )

    cash = settings.starting_cash
    quantity = ZERO
    fees_paid = ZERO
    stop_exits = 0
    entry_price: Decimal | None = None
    stopped_out = False
    pending_target: Decimal | None = None
    fills: list[Fill] = []
    equity_curve: list[EquityPoint] = []
    peak_equity = settings.starting_cash
    max_drawdown = ZERO
    daily_utc_date = candles[0].open_time.date().isoformat()
    daily_start_equity = settings.starting_cash
    halted = False
    halt_reason: str | None = None
    fee_rate = settings.fee_bps / BPS
    market_impact = settings.spread_bps / Decimal("20000") + settings.slippage_bps / BPS

    for index, (candle, feature) in enumerate(zip(candles, feature_rows, strict=True)):
        if index > 0 and pending_target is not None:
            cash, quantity, fill = rebalance_spot(
                candle,
                cash,
                quantity,
                pending_target,
                fee_rate,
                market_impact,
            )
            if fill is not None:
                fills.append(fill)
                fees_paid += Decimal(fill.fee)
                if fill.side == "BUY":
                    entry_price = Decimal(fill.price)
                elif quantity == ZERO:
                    entry_price = None
            pending_target = None

        # A resting virtual stop is checked against the candle low. A gap below
        # the trigger fills at the open, never at the better trigger price.
        # This is an OHLC research approximation, not an actual exchange order.
        if quantity > ZERO and entry_price is not None and settings.stop_loss_pct is not None:
            stop_price = entry_price * (ONE - settings.stop_loss_pct / Decimal("100"))
            if candle.low <= stop_price:
                raw_exit = min(candle.open, stop_price)
                exit_price = raw_exit * (ONE - market_impact)
                notional = quantity * exit_price
                fee = notional * fee_rate
                fills.append(
                    Fill(
                        side="STOP_SELL",
                        time=candle.open_time.isoformat(),
                        quantity=str(quantity),
                        price=str(exit_price),
                        notional=str(notional),
                        fee=str(fee),
                    )
                )
                cash += notional - fee
                fees_paid += fee
                quantity = ZERO
                entry_price = None
                stopped_out = True
                stop_exits += 1

        close_price = candle.close
        equity = cash + quantity * close_price
        equity_curve.append(
            EquityPoint(
                time=candle.close_time.isoformat(),
                cash=str(cash),
                base_quantity=str(quantity),
                close_price=str(close_price),
                equity=str(equity),
            )
        )
        utc_date = candle.open_time.date().isoformat()
        if utc_date != daily_utc_date:
            daily_utc_date = utc_date
            daily_start_equity = equity
        peak_equity = max(peak_equity, equity)
        if peak_equity > ZERO:
            max_drawdown = max(max_drawdown, ONE - equity / peak_equity)

        current_exposure = min(ONE, quantity * close_price / equity) if equity > ZERO else ZERO
        signal = signal_engine.evaluate(
            feature,
            strategy,
            current_exposure=current_exposure,
            equity=equity,
            daily_start_equity=daily_start_equity,
            peak_equity=peak_equity,
            already_halted=halted,
        )
        if signal.status == "HALTED":
            halted = True
            if halt_reason is None:
                halt_reason = signal.risk_reason
            pending_target = ZERO
        else:
            target = (
                Decimal(signal.effective_target) if signal.effective_target is not None else None
            )
            # Wait for the strategy to turn flat before another long entry.
            if stopped_out and target == ZERO:
                stopped_out = False
            pending_target = ZERO if stopped_out else target

    ending_equity = cash + quantity * candles[-1].close
    total_return_pct = (ending_equity / settings.starting_cash - ONE) * Decimal("100")
    return BacktestResult(
        strategy=strategy.name,
        exchange=candles[0].exchange,
        market_type=candles[0].market_type.value,
        symbol=candles[0].symbol,
        timeframe=candles[0].timeframe.value,
        starting_cash=str(settings.starting_cash),
        ending_equity=str(ending_equity),
        total_return_pct=str(total_return_pct),
        max_drawdown_pct=str(max_drawdown * Decimal("100")),
        risk_halted=halted,
        risk_halt_reason=halt_reason,
        fees_paid=str(fees_paid),
        stop_exits=stop_exits,
        ending_cash=str(cash),
        ending_base_quantity=str(quantity),
        fills=tuple(fills),
        equity_curve=tuple(equity_curve),
    )


def _validate_series(candles: list[Candle]) -> None:
    first = candles[0]
    previous: Candle | None = None
    for candle in candles:
        if (
            candle.exchange != first.exchange
            or candle.market_type != first.market_type
            or candle.symbol != first.symbol
            or candle.timeframe != first.timeframe
        ):
            raise ValueError("Backtest input must contain exactly one market series")
        if (
            previous is not None
            and candle.open_time != previous.open_time + first.timeframe.duration
        ):
            raise ValueError(
                "Backtest requires a contiguous series; validate and backfill data first"
            )
        previous = candle


def rebalance_spot(
    candle: Candle,
    cash: Decimal,
    quantity: Decimal,
    target_weight: Decimal,
    fee_rate: Decimal,
    market_impact: Decimal,
) -> tuple[Decimal, Decimal, Fill | None]:
    """Update a virtual Spot portfolio at a simulated price; never sends an order."""
    raw_price = candle.open
    current_equity = cash + quantity * raw_price
    target_quantity = current_equity * target_weight / raw_price
    difference = target_quantity - quantity
    if abs(difference) <= max(Decimal("1e-24"), abs(quantity) * Decimal("1e-22")):
        return cash, quantity, None

    if difference > ZERO:
        fill_price = raw_price * (ONE + market_impact)
        buy_quantity = min(difference, cash / (fill_price * (ONE + fee_rate)))
        if buy_quantity <= ZERO:
            return cash, quantity, None
        notional = buy_quantity * fill_price
        fee = notional * fee_rate
        remaining_cash = cash - notional - fee
        # Decimal division can round the affordability limit upward by a few
        # ulps. Clamp only that arithmetic dust; a material overspend is a bug.
        rounding_tolerance = max(Decimal("1e-28"), abs(cash) * Decimal("1e-24"))
        if remaining_cash < ZERO:
            if -remaining_cash > rounding_tolerance:
                raise ArithmeticError("Simulated Spot buy exceeded available cash")
            remaining_cash = ZERO
        return (
            remaining_cash,
            quantity + buy_quantity,
            Fill(
                side="BUY",
                time=candle.open_time.isoformat(),
                quantity=str(buy_quantity),
                price=str(fill_price),
                notional=str(notional),
                fee=str(fee),
            ),
        )

    sell_quantity = min(-difference, quantity)
    fill_price = raw_price * (ONE - market_impact)
    notional = sell_quantity * fill_price
    fee = notional * fee_rate
    return (
        cash + notional - fee,
        quantity - sell_quantity,
        Fill(
            side="SELL",
            time=candle.open_time.isoformat(),
            quantity=str(sell_quantity),
            price=str(fill_price),
            notional=str(notional),
            fee=str(fee),
        ),
    )
