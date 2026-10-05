"""Restartable long-only paper portfolio with latched risk stops."""

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from trading_platform.backtesting.engine import BacktestConfig, Fill, rebalance_spot
from trading_platform.core.enums import MarketType, Timeframe
from trading_platform.domain.candle import Candle
from trading_platform.features.engineering import compute_features
from trading_platform.risk.engine import RiskEngine, RiskLimits
from trading_platform.signals.engine import SignalDecision, SignalEngine
from trading_platform.strategies.base import TargetExposureStrategy

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
HISTORY_LIMIT = 100
STATE_VERSION = 1
DECIMAL_ROUNDING_EPSILON = Decimal("1e-24")


@dataclass(frozen=True, slots=True)
class PaperUpdate:
    status: str
    candle_time: str
    equity: str
    cash: str
    base_quantity: str
    signal_target: str | None
    pending_target: str | None
    daily_loss_pct: str
    drawdown_pct: str
    halted: bool
    risk_reason: str | None
    fill: Fill | None
    signal: SignalDecision | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class PaperTrader:
    """Process closed candles into a virtual account and persistable state.

    This class only updates local Decimal balances. It has no provider or order
    API reference, so it cannot submit a live order.
    """

    def __init__(
        self,
        *,
        exchange: str,
        market_type: MarketType,
        symbol: str,
        timeframe: Timeframe,
        strategy: TargetExposureStrategy,
        config: BacktestConfig | None = None,
        risk_limits: RiskLimits | None = None,
        snapshot: dict[str, object] | None = None,
    ) -> None:
        if market_type != MarketType.SPOT:
            raise ValueError("PaperTrader currently supports Spot only")
        self.exchange = exchange.upper()
        self.market_type = market_type
        self.symbol = symbol.upper()
        self.timeframe = timeframe
        self.strategy = strategy
        self.config = config or BacktestConfig()
        self.risk_limits = risk_limits or RiskLimits()
        self.risk_engine = RiskEngine(self.risk_limits)
        self.signal_engine = SignalEngine(self.risk_engine)

        self.cash = self.config.starting_cash
        self.base_quantity = ZERO
        self.fees_paid = ZERO
        self.last_processed_open: datetime | None = None
        self.pending_target: Decimal | None = None
        self.daily_utc_date: str | None = None
        self.daily_start_equity = self.config.starting_cash
        self.peak_equity = self.config.starting_cash
        self.halted = False
        self.halt_reason: str | None = None
        self.history: list[Candle] = []
        if snapshot is not None:
            self._restore(snapshot)

    @property
    def bootstrapped(self) -> bool:
        return self.last_processed_open is not None

    def bootstrap(self, candles: list[Candle]) -> PaperUpdate:
        """Seed indicators from recent closed candles without replaying trades."""
        if self.bootstrapped:
            raise ValueError("Paper state is already bootstrapped")
        if not candles:
            raise ValueError("Bootstrap requires recent closed candles")
        self._validate_identity(candles[0])
        previous: Candle | None = None
        for candle in candles:
            self._validate_identity(candle)
            if candle.close_time >= datetime.now(UTC):
                raise ValueError("Bootstrap accepts closed candles only")
            if (
                previous is not None
                and candle.open_time != previous.open_time + self.timeframe.duration
            ):
                raise ValueError("Bootstrap data must be contiguous; validate and backfill first")
            previous = candle
        latest = candles[-1]
        self.history = candles[-HISTORY_LIMIT:]
        self.last_processed_open = latest.open_time
        self.daily_utc_date = latest.open_time.date().isoformat()
        equity = self.cash + self.base_quantity * latest.close
        self.daily_start_equity = equity
        self.peak_equity = equity
        return self._update("BOOTSTRAPPED", latest, None, None, ZERO, ZERO)

    def process_closed(self, candle: Candle) -> PaperUpdate | None:
        """Process one newly closed candle; duplicate timestamps are idempotent."""
        self._validate_identity(candle)
        if candle.close_time >= datetime.now(UTC):
            raise ValueError("PaperTrader accepts closed candles only")
        if self.last_processed_open is None:
            return self.bootstrap([candle])
        if candle.open_time <= self.last_processed_open:
            return None
        if candle.open_time != self.last_processed_open + self.timeframe.duration:
            raise ValueError("Paper data has a gap; backfill before resuming")

        fill: Fill | None = None
        if self.pending_target is not None:
            fee_rate = self.config.fee_bps / Decimal("10000")
            market_impact = self.config.spread_bps / Decimal(
                "20000"
            ) + self.config.slippage_bps / Decimal("10000")
            self.cash, self.base_quantity, fill = rebalance_spot(
                candle,
                self.cash,
                self.base_quantity,
                self.pending_target,
                fee_rate,
                market_impact,
            )
            if fill is not None:
                self.fees_paid += Decimal(fill.fee)
            self.pending_target = None

        self.history.append(candle)
        self.history = self.history[-HISTORY_LIMIT:]
        self.last_processed_open = candle.open_time
        feature = compute_features(
            self.history, as_of=candle.close_time + timedelta(microseconds=1)
        )[-1]
        equity = self.cash + self.base_quantity * candle.close
        utc_date = candle.open_time.date().isoformat()
        if utc_date != self.daily_utc_date:
            self.daily_utc_date = utc_date
            self.daily_start_equity = equity
        self.peak_equity = max(self.peak_equity, equity)
        current_weight = (
            min(ONE, self.base_quantity * candle.close / equity) if equity > ZERO else ZERO
        )
        signal = self.signal_engine.evaluate(
            feature,
            self.strategy,
            current_exposure=current_weight,
            equity=equity,
            daily_start_equity=self.daily_start_equity,
            peak_equity=self.peak_equity,
            already_halted=self.halted,
        )
        if signal.status == "HALTED":
            self.halted = True
            if self.halt_reason is None:
                self.halt_reason = signal.risk_reason
            self.pending_target = ZERO
        elif signal.effective_target is not None:
            self.pending_target = Decimal(signal.effective_target)

        return self._update(
            "PROCESSED",
            candle,
            Decimal(signal.requested_target) if signal.requested_target is not None else None,
            self.pending_target,
            Decimal(signal.daily_loss_pct),
            Decimal(signal.drawdown_pct),
            fill=fill,
            signal=signal,
        )

    def snapshot(self) -> dict[str, object]:
        """Serialize account and indicator state for an atomic local checkpoint."""
        return {
            "schema_version": STATE_VERSION,
            "exchange": self.exchange,
            "market_type": self.market_type.value,
            "symbol": self.symbol,
            "timeframe": self.timeframe.value,
            "strategy": self.strategy.name,
            "starting_cash": str(self.config.starting_cash),
            "fee_bps": str(self.config.fee_bps),
            "spread_bps": str(self.config.spread_bps),
            "slippage_bps": str(self.config.slippage_bps),
            "max_daily_loss_pct": str(self.risk_limits.max_daily_loss_pct),
            "max_drawdown_pct": str(self.risk_limits.max_drawdown_pct),
            "max_exposure": str(self.risk_limits.max_exposure),
            "cash": str(self.cash),
            "base_quantity": str(self.base_quantity),
            "fees_paid": str(self.fees_paid),
            "last_processed_open": (
                self.last_processed_open.isoformat() if self.last_processed_open else None
            ),
            "pending_target": str(self.pending_target) if self.pending_target is not None else None,
            "daily_utc_date": self.daily_utc_date,
            "daily_start_equity": str(self.daily_start_equity),
            "peak_equity": str(self.peak_equity),
            "halted": self.halted,
            "halt_reason": self.halt_reason,
            "history": [candle.model_dump(mode="json") for candle in self.history],
        }

    def save(self, path: Path) -> None:
        """Atomically persist the paper state with restrictive file permissions."""
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix=".paper-state-",
                suffix=".tmp",
                dir=path.parent,
                delete=False,
            ) as temporary_file:
                temporary_path = temporary_file.name
                json.dump(self.snapshot(), temporary_file, indent=2)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, path)
            os.chmod(path, 0o600)
        except OSError as exc:
            if temporary_path is not None:
                Path(temporary_path).unlink(missing_ok=True)
            raise OSError(f"Could not save paper state to {path}: {exc}") from exc

    def _restore(self, snapshot: dict[str, object]) -> None:
        if snapshot.get("schema_version") != STATE_VERSION:
            raise ValueError("Unsupported paper state schema version")
        expected = {
            "exchange": self.exchange,
            "market_type": self.market_type.value,
            "symbol": self.symbol,
            "timeframe": self.timeframe.value,
            "strategy": self.strategy.name,
            "starting_cash": str(self.config.starting_cash),
            "fee_bps": str(self.config.fee_bps),
            "spread_bps": str(self.config.spread_bps),
            "slippage_bps": str(self.config.slippage_bps),
            "max_daily_loss_pct": str(self.risk_limits.max_daily_loss_pct),
            "max_drawdown_pct": str(self.risk_limits.max_drawdown_pct),
            "max_exposure": str(self.risk_limits.max_exposure),
        }
        for key, value in expected.items():
            if snapshot.get(key) != value:
                raise ValueError(f"Paper state {key} does not match the current configuration")
        self.cash = _snapshot_decimal(snapshot, "cash")
        self.base_quantity = _snapshot_decimal(snapshot, "base_quantity")
        self.fees_paid = _snapshot_decimal(snapshot, "fees_paid")
        self.daily_start_equity = _snapshot_decimal(snapshot, "daily_start_equity")
        self.peak_equity = _snapshot_decimal(snapshot, "peak_equity")
        if self.cash < ZERO:
            rounding_tolerance = max(
                Decimal("1e-28"), self.config.starting_cash * DECIMAL_ROUNDING_EPSILON
            )
            if -self.cash > rounding_tolerance:
                raise ValueError("Paper state cash cannot be negative")
            self.cash = ZERO
        if self.base_quantity < ZERO or self.fees_paid < ZERO:
            raise ValueError("Paper state balances and fees cannot be negative")
        if self.daily_start_equity <= ZERO or self.peak_equity <= ZERO:
            raise ValueError("Paper state risk reference equity must be positive")
        pending_target = snapshot.get("pending_target")
        self.pending_target = Decimal(str(pending_target)) if pending_target is not None else None
        if self.pending_target is not None and (
            not self.pending_target.is_finite() or not ZERO <= self.pending_target <= ONE
        ):
            raise ValueError("Paper state pending_target must be between 0 and 1")
        self.last_processed_open = _snapshot_time(snapshot, "last_processed_open")
        daily_date = snapshot.get("daily_utc_date")
        self.daily_utc_date = str(daily_date) if daily_date is not None else None
        halted = snapshot.get("halted", False)
        if not isinstance(halted, bool):
            raise ValueError("Paper state halted must be a boolean")
        self.halted = halted
        halt_reason = snapshot.get("halt_reason")
        if halt_reason is not None and not isinstance(halt_reason, str):
            raise ValueError("Paper state halt_reason must be a string or null")
        self.halt_reason = str(halt_reason) if halt_reason is not None else None
        if self.halted and not self.halt_reason:
            raise ValueError("A halted paper state must include its reason")
        raw_history = snapshot.get("history")
        if not isinstance(raw_history, list):
            raise ValueError("Paper state history must be a list")
        self.history = [Candle.model_validate(item) for item in raw_history]
        if len(self.history) > HISTORY_LIMIT:
            raise ValueError("Paper state history exceeds the supported limit")
        for candle in self.history:
            self._validate_identity(candle)
        for previous, candle in zip(self.history, self.history[1:], strict=False):
            if candle.open_time != previous.open_time + self.timeframe.duration:
                raise ValueError("Paper state history must be contiguous")
        if self.last_processed_open is None:
            if self.history:
                raise ValueError("Unbootstrapped paper state cannot include candle history")
        elif not self.history or self.history[-1].open_time != self.last_processed_open:
            raise ValueError("Paper state history does not end at last_processed_open")
        elif self.daily_utc_date != self.last_processed_open.date().isoformat():
            raise ValueError("Paper state daily_utc_date does not match last_processed_open")

    def _validate_identity(self, candle: Candle) -> None:
        if (
            candle.exchange != self.exchange
            or candle.market_type != self.market_type
            or candle.symbol != self.symbol
            or candle.timeframe != self.timeframe
        ):
            raise ValueError("Paper candle does not match the configured market series")

    def _update(
        self,
        status: str,
        candle: Candle,
        signal_target: Decimal | None,
        pending_target: Decimal | None,
        daily_loss_pct: Decimal,
        drawdown_pct: Decimal,
        *,
        fill: Fill | None = None,
        signal: SignalDecision | None = None,
    ) -> PaperUpdate:
        equity = self.cash + self.base_quantity * candle.close
        return PaperUpdate(
            status=status,
            candle_time=candle.close_time.isoformat(),
            equity=str(equity),
            cash=str(self.cash),
            base_quantity=str(self.base_quantity),
            signal_target=str(signal_target) if signal_target is not None else None,
            pending_target=str(pending_target) if pending_target is not None else None,
            daily_loss_pct=str(daily_loss_pct),
            drawdown_pct=str(drawdown_pct),
            halted=self.halted,
            risk_reason=self.halt_reason,
            fill=fill,
            signal=signal,
        )


def _snapshot_decimal(snapshot: dict[str, object], key: str) -> Decimal:
    value = snapshot.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Paper state {key} must be a decimal string")
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Paper state {key} is invalid") from exc


def _snapshot_time(snapshot: dict[str, object], key: str) -> datetime | None:
    value = snapshot.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Paper state {key} must be an ISO datetime string")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"Paper state {key} must include a timezone")
    return parsed.astimezone(UTC)


__all__ = ["PaperTrader", "PaperUpdate"]
