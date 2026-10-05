"""Auditable strategy signals passed through the independent risk engine."""

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal

from trading_platform.features.engineering import FeatureRow
from trading_platform.risk.engine import RiskDecision, RiskEngine
from trading_platform.strategies.base import TargetExposureStrategy

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class SignalDecision:
    """A deterministic strategy request and its independent risk outcome."""

    signal_id: str
    feature_hash: str
    as_of: str
    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    strategy: str
    status: str
    requested_target: str | None
    approved_target: str | None
    effective_target: str | None
    risk_reason: str | None
    daily_loss_pct: str
    drawdown_pct: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class SignalEngine:
    """Create a reproducible signal and ask risk for approval on every candle."""

    def __init__(self, risk_engine: RiskEngine | None = None) -> None:
        self.risk_engine = risk_engine or RiskEngine()

    def evaluate(
        self,
        feature: FeatureRow,
        strategy: TargetExposureStrategy,
        *,
        current_exposure: Decimal,
        equity: Decimal,
        daily_start_equity: Decimal,
        peak_equity: Decimal,
        already_halted: bool = False,
    ) -> SignalDecision:
        requested = strategy.target_exposure(feature)
        risk_target = current_exposure if requested is None else requested
        risk = self.risk_engine.assess(
            desired_target=risk_target,
            equity=equity,
            daily_start_equity=daily_start_equity,
            peak_equity=peak_equity,
            already_halted=already_halted,
        )
        return self._decision(feature, strategy, requested, risk, equity)

    @staticmethod
    def _decision(
        feature: FeatureRow,
        strategy: TargetExposureStrategy,
        requested: Decimal | None,
        risk: RiskDecision,
        equity: Decimal,
    ) -> SignalDecision:
        if risk.halted:
            status = "HALTED"
            approved = ZERO
            effective = ZERO
        elif requested is None:
            status = "HOLD"
            approved = None
            effective = None
        elif risk.approved_target < requested:
            status = "CAPPED"
            approved = risk.approved_target
            effective = risk.approved_target
        else:
            status = "APPROVED"
            approved = risk.approved_target
            effective = risk.approved_target

        feature_payload = asdict(feature)
        feature_hash = _digest(feature_payload)
        identity = {
            "feature_hash": feature_hash,
            "strategy": strategy.name,
            "requested_target": str(requested) if requested is not None else None,
            "approved_target": str(approved) if approved is not None else None,
            "effective_target": str(effective) if effective is not None else None,
            "status": status,
            "risk_reason": risk.reason,
            "equity": str(equity),
            "daily_loss_pct": str(risk.daily_loss_pct),
            "drawdown_pct": str(risk.drawdown_pct),
        }
        return SignalDecision(
            signal_id=_digest(identity),
            feature_hash=feature_hash,
            as_of=feature.close_time.isoformat(),
            exchange=feature.exchange,
            market_type=feature.market_type,
            symbol=feature.symbol,
            timeframe=feature.timeframe,
            strategy=strategy.name,
            status=status,
            requested_target=str(requested) if requested is not None else None,
            approved_target=str(approved) if approved is not None else None,
            effective_target=str(effective) if effective is not None else None,
            risk_reason=risk.reason,
            daily_loss_pct=str(risk.daily_loss_pct),
            drawdown_pct=str(risk.drawdown_pct),
        )


def _digest(value: object) -> str:
    def encode(item: object) -> str:
        if isinstance(item, datetime):
            return item.isoformat()
        raise TypeError(f"Unsupported signal value: {type(item).__name__}")

    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=encode,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["SignalDecision", "SignalEngine"]
